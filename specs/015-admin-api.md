# 015 — Admin JSON API

## Summary

The complete JSON HTTP surface. Ports the Python endpoints with path-compatible semantics, tightens auth, and adds cluster-management routes. Every response carries a uniform error envelope (spec 008) and respects leader-redirect (spec 006).

## Conventions

- All successful responses are `application/json; charset=utf-8`.
- Pagination: `?page=1&size=50` (1-indexed; size capped at 200).
- Filtering: per-resource query params, documented per route.
- Cursor-based alternative: `?cursor=<opaque>` for deep pagination (preferred for large sets; page-based has known skew issues).
- Timestamps: RFC3339 in UTC.

## Error codes (stable)

Grouped for reference:

- **auth**: `unauthorized`, `token_expired`, `signature_required`, `signature_invalid`, `signature_skew`, `signature_replay`, `app_inactive`, `apikey_invalid`, `cluster_secret_invalid`
- **validation**: `bad_request`, `schema_validation_failed`, `body_too_large`, `invalid_name`
- **not-found**: `application_not_found`, `action_not_found`, `subscription_not_found`, `event_not_found`, `gist_not_found`, `redaction_not_found`
- **conflict**: `already_exists`, `deduplicated` (200, not error)
- **cluster**: `not_leader`, `apply_timeout`, `cluster_not_ready`, `bootstrap_conflict`
- **internal**: `storage_error`, `internal_error`

## Routes

### Authentication

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/tokens` | username/password | Issue admin JWT cookie |
| POST | `/v8/tokens` | username/password | Legacy alias |
| POST | `/v1/logout` | cookie | Invalidate cookie |

### Applications

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/applications` | admin cookie | Create application — returns one-time `api_key` and `secret` |
| GET | `/v1/applications` | admin cookie | List — filters: `?active=true&name=<substr>` |
| GET | `/v1/applications/:name` | admin cookie | Fetch one |
| PUT | `/v1/applications/:name` | admin cookie | Update address |
| PUT | `/v1/applications/:name/secret` | api_key | Rotate HMAC secret — response shows new secret once |
| POST | `/v1/applications/:name/apikey` | admin cookie | Rotate API key — response shows new key once |
| PATCH | `/v1/applications/:name` | admin cookie | Toggle `active` |
| DELETE | `/v1/applications/:name` | admin cookie | Delete — cascades to actions, subscriptions, events |

### Actions

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/actions` | HMAC (app) or admin | Register action + schema |
| GET | `/v1/actions` | admin cookie | List — filters: `?application=<name>` |
| GET | `/v1/actions/:name` | admin cookie | Fetch one incl. schema |
| PUT | `/v1/actions/:name` | HMAC (app) or admin | Update schema |
| DELETE | `/v1/actions/:name` | admin cookie | Delete — cascades to subscriptions, events, gists |

### Events

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/events` | HMAC (publishing app) | Publish event |
| GET | `/v1/events` | admin cookie | List (redacted) — filters: `?action=...&from=...&to=...` |
| GET | `/v1/events/:id` | admin cookie | Fetch one (redacted) |

### Subscriptions

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/subscriptions` | HMAC (subscribing app) | Register webhook |
| GET | `/v1/subscriptions` | admin cookie | List — filters: `?application=...&action=...` |
| GET | `/v1/subscriptions/:id` | admin cookie | Fetch one |
| PUT | `/v1/subscriptions/:id` | HMAC (subscriber) or admin | Update handler / max_retries / description |
| DELETE | `/v1/subscriptions/:id` | HMAC (subscriber) or admin | Unsubscribe |

### Gists (delivery records)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/v1/gists` | admin cookie | List — filters: `?event=...&subscription=...&completed=true` |
| GET | `/v1/gists/:id` | admin cookie | Fetch one |
| POST | `/v1/gists/:id/replay` | admin cookie | Force redelivery |
| POST | `/v1/regists/:id` | admin cookie | Legacy alias for replay |
| POST | `/v1/gists/:id/acknowledge` | HMAC (subscriber) | Mark as acknowledged by receiver |

### Redactions

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/redactions` | admin cookie | Register redaction rule |
| GET | `/v1/redactions` | admin cookie | List — filters: `?action=...` |
| DELETE | `/v1/redactions/:id` | admin cookie | Remove rule |

### Credentials

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/credentials/change-password` | admin cookie | Change admin password |

### Cluster

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/cluster/join` | cluster secret | Add voter (leader only) |
| POST | `/v1/cluster/leave` | cluster secret | Remove voter (leader only) |
| GET | `/v1/cluster/status` | none | Topology |
| POST | `/v1/cluster/snapshot` | admin cookie | Trigger snapshot |
| GET | `/v1/cluster/snapshot/stream` | admin cookie | Stream snapshot for backup |
| POST | `/v1/cluster/transfer-leadership` | admin cookie | Transfer to a target node |

### Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/ready` | none | Readiness |
| GET | `/version` | none | Build info |

## Representative request/response shapes

### Create application

```
POST /v1/applications
Cookie: Authentication=...

{ "name": "billing", "address": "https://billing.internal" }
```

**201**:
```json
{
  "name": "billing",
  "address": "https://billing.internal",
  "active": true,
  "api_key": "a8f3...<64 hex>",        // shown ONCE
  "secret": "b6c1...<64 hex>",          // shown ONCE
  "created_at": "2026-04-23T10:00:00Z"
}
```

Subsequent `GET` never returns `api_key` or `secret`.

### Register action

```
POST /v1/actions
X-Amebo-Signature: ...
X-Amebo-Timestamp: ...
X-Amebo-Application: billing
X-Amebo-Nonce: ...
X-Amebo-Redact: address.zip

{ "action": "v1.customers.created",
  "application": "billing",
  "schema": { "$schema": "...", "type": "object", ... } }
```

**201**:
```json
{
  "action": "v1.customers.created",
  "application": "billing",
  "created_at": "2026-04-23T10:00:01Z",
  "redactions": ["address.zip"]
}
```

### Publish event

Shown in spec 011.

### List gists (admin)

```
GET /v1/gists?subscription=<id>&completed=false&page=1&size=50
```

**200**:
```json
{
  "items": [
    {
      "id": "01HX...",
      "event": "01HX...",
      "subscription": "01HX...",
      "completed": false,
      "acknowledged": false,
      "retries": 2,
      "sleep_until": "2026-04-23T10:00:40Z",
      "last_error": "500: internal server error",
      "created_at": "2026-04-23T09:59:00Z"
    }
  ],
  "page": 1,
  "size": 50,
  "total": 237,
  "next_cursor": "..."
}
```

## Cascade deletes

| Parent deleted | Cascades to |
|---|---|
| Application | Its actions → their events/subscriptions/gists; its subscriptions; its credentials |
| Action | Its events; subscriptions on it; gists for those subscriptions |
| Subscription | Its gists |

Cascades execute in a single Raft command (`CMD_ACTION_DELETE` walks the indexes and batches deletes). Bounded to avoid oversized log entries — a delete that would emit > 10k sub-entries is executed in chunks via multiple sequential commands (the HTTP handler drives this).

## Pagination implementation

- Internal implementation always uses cursor (next-key iteration).
- The `page`/`size` params are translated: `page=N` means "skip (N-1)*size items", implemented as cursor iteration. Slow for deep pages — documented in the response with a warning header on page > 100.
- Preferred form: `cursor=...&size=50` (returned in `next_cursor` of each response).

## Caching headers

- Admin GETs: `Cache-Control: no-store`.
- Static UI assets: `Cache-Control: public, max-age=31536000, immutable` (embedded with content-hash filenames).

## Idempotency for writes

- `POST /v1/events`: idempotency via `deduper` in the body (spec 011).
- Other writes: clients may send `Idempotency-Key: <uuid>` header. The server dedupes by (route, app identity, key) for 24h. Duplicate returns the cached response. Deferred to v1.1 — v1 documents the header as reserved.

## Versioning

- URL path is the version (`/v1`). `/v2` is the next contract-breaking revision — deferred indefinitely.
- Additive changes (new fields, new endpoints) do not bump the version.
- `/v8/tokens` is preserved as an alias for Python compatibility.

## Open API spec

Generated from handler annotations (via `swaggo/swag` or hand-maintained YAML — TBD). Served at `/openapi.json` and `/docs` (Swagger UI). Spec 016 references this for the UI's "API docs" link.

## Acceptance criteria

- [ ] Every route in the tables above has a handler, a unit test, and an integration test against a 3-node cluster.
- [ ] Error codes in the Error Codes section are exhaustive and covered by tests.
- [ ] `POST /v1/applications` response shows secret and api_key once; subsequent GET omits them.
- [ ] Cascade delete of an application removes all related data in under 10 seconds for a 10k-event application (bounded chunking).
- [ ] Leader-only writes return 421 from followers with correct `X-Amebo-Leader`.
- [ ] OpenAPI spec serves a valid document that lints clean.

## Alternatives considered

- **PATCH with JSON Patch/Merge Patch**: more correct but complex; stick with Python's "PUT partial fields" for compatibility.
- **GraphQL**: superset of what we need; too heavy. Rejected.
- **Per-resource nested routes** (`/applications/:name/actions`): nicer but diverges from Python. Rejected for compatibility.
- **Return secrets/keys forever**: security anti-pattern. Show-once is correct.
