# 009 — Authentication & Authorization

## Summary

Three authentication schemes coexist, mirroring the Python implementation:

1. **Admin cookie (JWT)** — for the web UI and admin JSON routes.
2. **HMAC signature** — for application → broker API calls (event publish, subscription registration).
3. **API key (Bearer)** — for application self-service (secret rotation).

Plus a **cluster secret** for cluster membership operations.

This spec also defines the admin credential bootstrap and password reset flow.

## Scheme 1 — Admin JWT cookie

**Who uses it:** the web UI, and any admin-level API operations that don't fit the HMAC model.

**Token issuance:**
- `POST /v1/tokens` with JSON body `{"username": "...", "password": "..."}`.
- Server verifies password against `Credential.PasswordHash` (bcrypt).
- On success: set cookie `Authentication=<jwt>`, `HttpOnly`, `SameSite=Strict`, `Secure` (when TLS), `Path=/`, `Max-Age=900` (15 min).

**JWT claims:**
```json
{
  "iss": "amebo",
  "sub": "admin",
  "iat": 1712345678,
  "exp": 1712346578,
  "nid": "node-1"   // node that issued; informational only
}
```

- Algorithm: HS256.
- Signing key: `AMEBO_SECRET` (must be ≥ 32 bytes).
- No refresh tokens in v1 — clients re-authenticate on expiry (simple, matches Python).

**Verification middleware:**
```go
func AdminCookie(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        c, err := r.Cookie("Authentication")
        if err != nil { http401(w); return }
        claims, err := verifyJWT(c.Value, secret)
        if err != nil { http401(w); return }
        ctx := context.WithValue(r.Context(), ctxAdmin, claims.Subject)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}
```

**Logout:** `POST /v1/logout` sets cookie with `Max-Age=0`.

## Scheme 2 — HMAC request signature

**Who uses it:** applications publishing events, registering actions, registering subscriptions.

**Header:** `X-Amebo-Signature: <hex>`

**Algorithm:**
- Canonical string = `<http_method>\n<path>\n<sha256_hex_of_body>\n<timestamp>`
- Timestamp = `X-Amebo-Timestamp` header (RFC3339).
- Signature = `HMAC_SHA256(canonical, app_secret)` → hex.

**Why include method + path + timestamp?**
- Python amebo signs only the body. That's vulnerable to replay and to verb-confusion (POSTing a body to a DELETE endpoint). We tighten this for v1 while keeping a compatibility flag `AMEBO_LEGACY_SIG=true` that accepts body-only sigs for clients not yet updated.

**Verification:**
1. Reject if `Timestamp` is absent, malformed, or skews > 5 minutes from server clock.
2. Extract `X-Amebo-Application` header (new, required) to locate the app — Python relied on inferring from the payload, which doesn't work for all routes.
3. Fetch application; if inactive, 403.
4. Decrypt `SecretCipher` using the data-at-rest key.
5. Compute expected signature; compare with `crypto/subtle.ConstantTimeCompare`.
6. Attach `application` identity to request context.

**Replay protection:** client includes `X-Amebo-Nonce` (random 16 bytes hex). Server caches `(app, nonce, timestamp)` for 5 min and rejects duplicates. Cache is per-node; crossing nodes, a replay would succeed within 5 min — acceptable given the timestamp window is tight.

**Legacy mode (`AMEBO_LEGACY_SIG=true`):** accept body-only signatures without timestamp/nonce. Logs a WARN for observability. Off by default in v1; enabled during migration (spec 021).

## Scheme 3 — API key (Bearer)

**Who uses it:** `PUT /v1/applications/:id/secret` — rotating an app's HMAC secret. This is the chicken-and-egg endpoint: if you've lost your HMAC secret, you can't re-sign a request that sets a new one. API key gives you a second credential.

**Header:** `Authorization: Bearer <api_key>`

**Storage:** `Application.APIKeyHash` (bcrypt).

**Issuance:** 
- On application create (admin auth), the response includes a freshly generated 32-byte-hex API key — shown **once**.
- `POST /v1/applications/:id/apikey` (admin auth) rotates; response shows the new key once.

**Verification:** middleware loads the application by path param, bcrypt-compares the bearer token to the stored hash.

## Scheme 4 — Cluster secret

**Who uses it:** `POST /v1/cluster/join`, `POST /v1/cluster/leave`.

**Mechanism:** header `X-Amebo-Cluster-Secret: <AMEBO_SECRET>`. Constant-time compare.

- This is not as flexible as per-client credentials, but cluster ops are a narrow, admin-only surface. Keeping it simple avoids a credential-rotation lifecycle for cluster membership.
- Revisit if operators demand per-node join tokens.

## Admin credential lifecycle

**First boot:**
- `AMEBO_USERNAME` (default `admin`) + `AMEBO_PASSWORD` (required) → bcrypt-hash → propose `CMD_CREDENTIAL_UPSERT` via Raft → committed across cluster.
- Write `data/.initialized`.

**Subsequent boots (same node):**
- If `AMEBO_PASSWORD` is set in env/config, propose `CMD_CREDENTIAL_UPSERT` to update. This matches Python's "reset admin on restart" convenience for operators who store the password in config management.
- If unset, leave existing hash untouched.

**Password change via UI:**
- `POST /v1/credentials/change-password` (admin cookie auth).
- Body: `{"current": "...", "new": "..."}`.
- Verifies current, proposes `CMD_CREDENTIAL_UPSERT` with new hash.

**Password reset (root):**
- There is a CLI command `amebo admin reset-password` that runs on the same host as the data dir. It:
  1. Reads the admin username from env (default `admin`).
  2. Prompts for a new password (stdin).
  3. Connects to the local Raft instance via an admin socket (unix domain socket at `$DATA_DIR/admin.sock`).
  4. Proposes `CMD_CREDENTIAL_UPSERT`.
- Must run on the leader; if local node is not leader, prints the leader address.

## Secret-at-rest encryption

Application HMAC secrets are stored encrypted:

- **KEK**: derived via HKDF-SHA256 from `AMEBO_SECRET` + per-cluster salt (stored in Raft under a fixed key on first boot).
- **DEK**: per-secret random 32-byte key encrypted with KEK (AES-256-GCM).
- **Ciphertext**: `DEK_wrapped || nonce || AES-GCM(secret)`.

Rotation of `AMEBO_SECRET` requires unwrapping with the old key and rewrapping with the new — a `amebo admin rotate-master-key --old $OLD` command handles it.

## Failure modes and responses

| Condition | Response |
|---|---|
| Missing/invalid JWT | 401 `{"code": "unauthorized"}` |
| Expired JWT | 401 `{"code": "token_expired"}` |
| Missing HMAC signature | 401 `{"code": "signature_required"}` |
| Invalid HMAC signature | 401 `{"code": "signature_invalid"}` |
| Timestamp skew > 5 min | 401 `{"code": "signature_skew"}` |
| Nonce reused | 401 `{"code": "signature_replay"}` |
| Inactive application | 403 `{"code": "app_inactive"}` |
| Bad API key | 401 `{"code": "apikey_invalid"}` |
| Wrong cluster secret | 401 `{"code": "cluster_secret_invalid"}` |

All include `request_id` and a human message.

## Audit

Auth failures log at WARN level with reason + path + remote IP, without ever logging secrets. Successful admin auths log at INFO.

## Acceptance criteria

- [ ] `POST /v1/tokens` with valid creds sets the `Authentication` cookie; with invalid creds returns 401 with no body hints.
- [ ] A request to a protected admin route with no cookie → 401.
- [ ] A request with a valid HMAC signature including timestamp/nonce passes; one with skewed timestamp → 401.
- [ ] Replaying the same nonce within 5 min → 401; after 5 min, the signature is stale regardless of nonce.
- [ ] `AMEBO_LEGACY_SIG=true` accepts body-only sigs; logs a deprecation warning.
- [ ] Admin password reset via CLI succeeds on leader and prints redirect address on follower.
- [ ] Rotating the master key via `amebo admin rotate-master-key` preserves the ability to sign-verify existing applications.

## Alternatives considered

- **OAuth2/OIDC**: overkill for v1. Target for v1.1 (SSO via external IdP).
- **Signed URLs** for one-shot admin ops: nice for CLI, but adds complexity. Deferred.
- **Keep Python's body-only signing forever**: loses replay protection. Added the tightened scheme but kept a legacy switch for migration.
