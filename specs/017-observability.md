# 017 — Observability

## Summary

Logs, metrics, health checks, and tracing hooks. Consistent shapes across the binary; metrics exposed on a dedicated listener (spec 008); logs in structured JSON by default.

## Logging

### Library

`log/slog` (stdlib). No external dependencies.

### Formats

- `AMEBO_LOG_FORMAT=json` (default): one JSON object per line.
- `AMEBO_LOG_FORMAT=text`: `key=value` text output, for human-readable local dev.

### Levels

`debug`, `info`, `warn`, `error`. Controlled by `AMEBO_LOG_LEVEL` (default `info`). Hot-reloadable via SIGHUP (spec 003).

### Required context keys

Every log line includes:

- `ts`: timestamp in RFC3339Nano UTC.
- `level`: level string.
- `msg`: human-readable message (stable key; no dynamic values).
- `component`: package name (`http`, `raft`, `aproko`, `webhook`, `storage`, ...).
- `node_id`: this node's ID.
- `req_id`: present when a request is in scope.

Example:

```json
{"ts":"2026-04-23T10:00:00.123Z","level":"info","msg":"http.request",
 "component":"http","node_id":"node-1","req_id":"01HXABC...",
 "method":"POST","path":"/v1/events","status":201,"dur_ms":4.2}
```

### Forbidden content

- No secrets in any field (tokens, API keys, HMAC secrets, passwords).
- No full HTTP request/response bodies.
- No raw event payloads (spec 014 redaction is for user-facing display; logs must also not leak payloads).
- Handler URLs may be logged with the query string stripped.

### Log categories (stable `msg` values)

| Category | Emitter | Notes |
|---|---|---|
| `http.request` | HTTP middleware | One per request |
| `raft.leadership` | Raft watcher | `gained`/`lost`/`transfer` |
| `raft.apply.error` | FSM | On failed apply |
| `delivery.cycle` | Aproko | Summary per cycle |
| `delivery.failure` | Webhook client | Per failed attempt |
| `delivery.exhausted` | FSM | Gist reached max retries |
| `storage.corrupt` | Storage | Irrecoverable — aborts process |
| `cluster.join` / `cluster.leave` | Cluster handlers | |
| `schema.validation.failed` | Ingest | Debug level; may be high-volume |

## Metrics

### Library

`github.com/prometheus/client_golang`. Served at `GET /metrics` on the metrics listener.

### Naming

`amebo_<subsystem>_<what>_<unit>`:

- `_total` counters cumulative over process lifetime.
- `_seconds` durations in histograms with default buckets `[.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]`.
- `_bytes` sizes.

### Catalog

**HTTP:**
- `amebo_http_requests_total{method, path, status}` (counter)
- `amebo_http_request_duration_seconds{method, path}` (histogram)
- `amebo_http_requests_in_flight` (gauge)

**Raft:**
- `amebo_raft_state{state="leader|follower|candidate"}` (gauge, 0/1)
- `amebo_raft_last_applied_index` (gauge)
- `amebo_raft_last_committed_index` (gauge)
- `amebo_raft_term` (gauge)
- `amebo_raft_apply_duration_seconds` (histogram)
- `amebo_raft_propose_total{type}` (counter)
- `amebo_raft_leadership_changes_total{type="gained|lost"}` (counter)
- `amebo_raft_snapshot_duration_seconds` (histogram)

**Storage:**
- `amebo_storage_lsm_size_bytes`, `amebo_storage_vlog_size_bytes` (gauge)
- `amebo_storage_compactions_total` (counter)
- `amebo_storage_vlog_gc_total` (counter)
- `amebo_storage_op_duration_seconds{op}` (histogram)

**Ingest:**
- `amebo_events_ingested_total{action, result}` (counter)
- `amebo_events_fanout` (histogram of subscribers per event)
- `amebo_event_ingest_duration_seconds` (histogram)

**Delivery:**
- `amebo_delivery_batch_size` (histogram)
- `amebo_delivery_cycle_duration_seconds` (histogram)
- `amebo_delivery_attempted_total{result}` (counter)
- `amebo_webhook_requests_total{status, action}` (counter)
- `amebo_webhook_request_duration_seconds{action}` (histogram)
- `amebo_gists_pending` (gauge, scraped from index size)
- `amebo_gists_completed_total`, `amebo_gists_exhausted_total` (counter)

**Schema:**
- `amebo_schema_compile_total{action}` (counter)
- `amebo_schema_validation_total{action, result}` (counter)

**Redaction:**
- `amebo_redactions_applied_total{action}` (counter)

**Process:**
- Standard `go_*` and `process_*` collectors from the Prometheus client.

### Cardinality hygiene

- `action` labels can explode — cap to 1000 unique values, hash the rest into `action="_overflow"`.
- Never use raw URL paths as labels. chi's `RoutePattern` gives us the template (`/v1/events/:id`) which is bounded.
- Never use request IDs or UUIDs as labels.

## Tracing

- OpenTelemetry traces **optional**, enabled with `AMEBO_OTEL_ENDPOINT=<otlp-endpoint>`.
- Spans emitted for:
  - Each HTTP request.
  - Each Raft propose (child of HTTP when applicable).
  - Each webhook delivery.
  - Each schema validation (debug level — sampled at 1% by default).
- Trace context propagated via `traceparent` header on outbound webhooks — subscribers can correlate.
- Default sampler: ratio 0.1 (10%). Override via `AMEBO_OTEL_SAMPLE_RATIO`.

When `AMEBO_OTEL_ENDPOINT` is unset, the tracer is a no-op — zero cost.

## Health checks

Already covered in spec 008:

- `GET /health` — liveness. Returns 200 if process is alive.
- `GET /ready` — readiness. Returns 200 only if storage open + Raft caught up + (if leader) reconciler running.

Readiness details:

```json
{
  "status": "ready",
  "storage": "ok",
  "raft": {"state": "leader", "last_applied": 12345, "last_contact_ms": 0},
  "reconciler": "running"
}
```

On unready, same shape with `status: "not_ready"` and HTTP 503.

## Debug endpoints

`/debug/pprof/*` on the metrics listener. Standard net/http/pprof handlers. Disabled by default in production via `AMEBO_PPROF=false`.

Additional:
- `/debug/raft` — Raft internal stats (useful for troubleshooting; admin auth).
- `/debug/config` — effective config (secrets redacted; admin auth).
- `/debug/vars` — expvar (Go runtime stats).

## Alerting recipes

Not in spec, but recommended alerts documented in `deploy/prometheus/alerts.yaml`:

- `AmeboLeaderless`: no leader for > 30s.
- `AmeboReconcilerStalled`: `amebo_gists_pending` rising while `amebo_delivery_attempted_total` flat for > 5m.
- `AmeboHighFailureRate`: `rate(amebo_webhook_requests_total{status=~"5..|0"}[5m]) / rate(amebo_webhook_requests_total[5m]) > 0.5`.
- `AmeboStorageGrowing`: `amebo_storage_lsm_size_bytes` growing faster than retention should permit.

## Acceptance criteria

- [ ] Every metric in the catalog is registered and increments/sets correctly.
- [ ] `GET /metrics` on the metrics listener returns a valid Prometheus exposition.
- [ ] `GET /metrics` on the main listener returns 404.
- [ ] Changing `AMEBO_LOG_LEVEL` via SIGHUP takes effect within one second.
- [ ] A request with `traceparent` header shows up in the exported trace with the incoming trace ID.
- [ ] No log line in any code path contains `$AMEBO_SECRET`, bcrypt hashes, or raw API keys (grep test in CI).
- [ ] Cardinality test: feeding 10k unique actions results in ≤ 1001 `action` label values (overflow hashing works).

## Alternatives considered

- **OpenMetrics instead of Prometheus**: close enough; Prom format is universal.
- **zap instead of slog**: faster, but slog is stdlib; only switch if slog becomes a bottleneck.
- **StatsD**: old, cardinality-unfriendly; rejected.
- **Enable pprof in production by default**: exposes attack surface. Default off.
