# 008 — HTTP Server

## Summary

Specifies the HTTP server framework, middleware stack, graceful shutdown, TLS, and the split between the public event-ingress port, the admin port, and the metrics port.

## Framework

`github.com/go-chi/chi/v5`. Stdlib-compatible (`http.Handler`), composable middleware, mature.

Rejected: fiber (wraps net/http incompatibly), gin (too opinionated), fasthttp (no HTTP/2, breaks stdlib compatibility).

## Listeners

Three separate listeners by default, all configurable:

| Listener | Default addr | Purpose | Auth |
|---|---|---|---|
| Main | `0.0.0.0:3310` | Event ingress + admin API + UI | Per-route |
| Metrics | `0.0.0.0:9310` | Prometheus `/metrics`, `/debug/pprof/*` | None by default; bind to loopback or restrict via reverse proxy |
| Health | Same port as Main | `/health`, `/ready` | None |

**Why split metrics:** so you can firewall-expose `:3310` to the internet while keeping `:9310` on a private interface or `127.0.0.1` only.

## Middleware order (outermost → innermost)

Applied to all routes:

1. **Recoverer** — `chi/middleware.Recoverer` — panic → 500 + log.
2. **RequestID** — inject or propagate `X-Request-Id`; attach to logger context.
3. **RealIP** — honor `X-Forwarded-For` from trusted proxies only (config).
4. **Logger** — structured access log (spec 017).
5. **Metrics** — per-route Prometheus histograms: `amebo_http_requests_total`, `amebo_http_request_duration_seconds`.
6. **Timeout** — per-route default 30s via `http.Server.WriteTimeout`.
7. **CORS** — permissive on `/v1/*`, strict same-origin on `/p/*` and `/w/*` UI routes.
8. **Body limit** — 1 MB default, overridable per route (events/ingest gets the configured `MAX_PAYLOAD`).

Route-specific:

- **Auth**: admin routes get cookie-auth middleware; app API routes get HMAC-signature middleware; cluster-admin routes get secret-auth (spec 009).
- **LeaderOnly**: write routes. If not leader, respond 421 with `X-Amebo-Leader` header.

## Route registration

```go
// internal/server/routes.go
func Routes(deps Deps) http.Handler {
    r := chi.NewRouter()
    r.Use(
        middleware.Recoverer,
        middleware.RequestID,
        middleware.RealIP,
        obs.Logger(deps.Log),
        obs.Metrics(deps.Metrics),
    )

    // Public health
    r.Get("/health", handleHealth)
    r.Get("/ready", handleReady)

    // JSON API
    r.Route("/v1", func(r chi.Router) {
        r.Use(middleware.Timeout(30*time.Second))
        r.Use(cors.API())

        // Auth
        r.Post("/tokens", auth.IssueToken(deps))
        r.Post("/v8/tokens", auth.IssueToken(deps))  // legacy alias

        // Applications — mixed auth per route (see spec 015)
        r.Route("/applications", func(r chi.Router) { /* ... */ })

        // ... actions, events, subscriptions, gists, redactions

        // Cluster
        r.Route("/cluster", func(r chi.Router) { /* ... */ })
    })

    // Web UI
    r.Route("/p", func(r chi.Router) { /* ... */ })
    r.Route("/w", func(r chi.Router) { /* ... */ })
    r.Get("/", ui.Login)

    // Embedded static assets
    r.Handle("/public/*", ui.StaticHandler())

    return r
}
```

## Graceful shutdown

```go
func Run(ctx context.Context, srv *http.Server) error {
    errCh := make(chan error, 1)
    go func() { errCh <- srv.ListenAndServe() }()

    select {
    case <-ctx.Done():
        shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
        defer cancel()
        return srv.Shutdown(shutdownCtx)
    case err := <-errCh:
        return err
    }
}
```

- SIGTERM / SIGINT triggers cancellation.
- During shutdown: stop accepting new connections, drain in-flight requests up to 30s (configurable).
- Raft shutdown happens **after** HTTP shutdown completes — handlers must not hang on a dead Raft.

## Readiness vs liveness

- `GET /health` (liveness): always 200 if the process is alive and not shutting down.
- `GET /ready` (readiness): 200 only if:
  - Storage is open.
  - Raft has applied the initial configuration (for a fresh node, this means the join completed).
  - This node has heard from the leader within the last 2× heartbeat interval (for followers).
  - If this node is the leader: reconciler is running.
- During graceful shutdown, `/ready` returns 503 immediately so load balancers drain traffic.

## TLS

- If `AMEBO_TLS_CERT` and `AMEBO_TLS_KEY` are set, the main listener uses TLS with those files.
- HTTP/2 enabled by default under TLS.
- Auto-cert (Let's Encrypt via `acme/autocert`) is **not** in v1 — production users put Amebo behind a reverse proxy.

## HTTP/2 and keep-alive

- HTTP/2 enabled on TLS.
- `Keep-Alive` timeout: 60s.
- `ReadHeaderTimeout`: 10s (defense against slowloris).
- Max header size: 1 MB.

## CORS

- `/v1/*`: allow all origins (`*`), standard methods, headers `Content-Type, Authorization, X-Amebo-Signature, X-Amebo-Event-Id`. No credentials.
- `/p/*`, `/w/*` (UI): allow only same-origin (config: `AMEBO_UI_ORIGIN`). Credentials allowed (cookie auth).

## Body size limits

- Default: 1 MB for all routes.
- `POST /v1/events`: limited by `AMEBO_MAX_PAYLOAD` (default 1 MB, see spec 004).
- `POST /v1/actions`: schema up to 256 KB.
- Enforced via `http.MaxBytesReader` — produces a clean 413 on excess.

## Request logging

Every request logs one structured line at completion:

```json
{
  "ts": "2026-04-23T10:00:00.123Z",
  "level": "info",
  "msg": "http.request",
  "method": "POST",
  "path": "/v1/events",
  "status": 201,
  "bytes": 412,
  "dur_ms": 4.2,
  "req_id": "01HX...",
  "remote": "10.0.0.5",
  "app": "billing"    // when HMAC auth identifies the app
}
```

No request bodies, no response bodies, no tokens — they contain secrets. Headers logged only for debug log level.

## Error response format

Uniform JSON envelope for all errors:

```json
{
  "error": {
    "code": "schema_validation_failed",
    "message": "payload does not match schema: required field 'customer_id' missing",
    "request_id": "01HX...",
    "details": { "path": "customer_id", "keyword": "required" }
  }
}
```

Error codes are stable (spec 015 lists them). Messages are human-readable and may change.

## 421 Misdirected Request (leader redirect)

```
HTTP/1.1 421 Misdirected Request
X-Amebo-Leader: 10.0.0.1:3310
Content-Type: application/json

{"error": {"code": "not_leader", "message": "write request sent to follower",
           "leader": "10.0.0.1:3310"}}
```

Clients in our Go SDK auto-follow. Other clients must handle explicitly.

## Rate limiting

Not in v1. Operators put Amebo behind a reverse proxy (nginx, Traefik) if they need per-client limits. Spec 015 notes the endpoints that would benefit most if added later.

## pprof and debug

Mounted on the metrics listener only:

```go
metrics.Handle("/debug/pprof/", pprof.Index)
metrics.Handle("/debug/pprof/cmdline", pprof.Cmdline)
metrics.Handle("/debug/pprof/profile", pprof.Profile)
metrics.Handle("/debug/pprof/symbol", pprof.Symbol)
metrics.Handle("/debug/pprof/trace", pprof.Trace)
```

## Acceptance criteria

- [ ] `GET /health` returns 200 always; `GET /ready` returns 503 until node is fully initialized.
- [ ] SIGTERM drains in-flight requests up to 30s then exits cleanly; verified with a test that issues a long-running request during shutdown.
- [ ] A follower receiving `POST /v1/events` returns 421 with `X-Amebo-Leader` pointing at the current leader.
- [ ] Request over the body limit returns 413 with the standard error envelope.
- [ ] `/metrics` on the metrics listener is not reachable from the main listener.
- [ ] Access logs contain `req_id` and that id propagates in error responses.

## Alternatives considered

- **gRPC for the admin API**: easier evolution, but most amebo clients are webhook-driven HTTP — doubling the server surface isn't worth it for v1.
- **Single listener for everything**: simpler but conflates security zones. Rejected.
- **Rate limiting built in**: tempting but duplicates reverse-proxy functionality. Deferred.
