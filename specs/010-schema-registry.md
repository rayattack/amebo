# 010 — JSON Schema Registry

## Summary

Every action owns a JSON Schema. Every event published against that action is validated before persistence. This spec defines registration, validation, compilation caching, versioning, and the redact-header ergonomic shortcut.

## Library choice

`github.com/santhosh-tekuri/jsonschema/v5`.

- Pure Go, no CGo, no reflection at validation time.
- Supports Draft 7, 2019-09, 2020-12.
- Benchmark-competitive with Python's `fastjsonschema`.

Rejected: `xeipuuv/gojsonschema` (slower, Draft 4 only), `qri-io/jsonschema` (unmaintained).

## Registration

**Endpoint:** `POST /v1/actions`

**Body:**
```json
{
  "action": "v1.customers.created",
  "application": "billing",
  "schema": { /* JSON Schema document */ }
}
```

**Headers:**
- HMAC auth required (the application's own signature) OR admin cookie.
- Optional `X-Amebo-Redact: address.zip items[].serial` — space-separated field paths to auto-register as redactions (spec 014).

**Server steps:**
1. Validate auth; confirm the signer matches `body.application` (apps can only register their own actions; admins can register for anyone).
2. Validate action name format: `^[a-zA-Z][a-zA-Z0-9._-]{1,127}$`. Must contain at least one `.` (convention: `version.resource.event`).
3. Validate schema:
   - Size ≤ 256 KB.
   - Must parse as JSON.
   - **Compile it** (`jsonschema.CompileString(url, schemaJSON)`) to confirm it's a valid schema. Reject with 400 if compilation fails; message includes the error from the library.
   - Must declare a `$schema` (recommended) — warn but don't reject if missing.
4. Propose `CMD_ACTION_UPSERT` to Raft with the raw schema bytes + parsed metadata.
5. Parse `X-Amebo-Redact` and propose one `CMD_REDACTION_UPSERT` per field path.

**Update semantics:**
- Re-registering an existing action **replaces** the schema. This is the Python behavior. Existing events are not re-validated (they were valid against the old schema at ingest time).
- A future v1.1 may support schema versioning with explicit version tags; for v1, "last write wins" is documented and accepted.

## Validation at ingest

Every `POST /v1/events` does:

```go
action, err := getAction(tx, req.Action)
if err != nil { return 404 }

compiled, err := schemaCache.Get(action.Name, action.Schema, action.UpdatedAt)
if err != nil { return 500 }

if err := compiled.Validate(req.PayloadRaw); err != nil {
    return 400 { code: "schema_validation_failed",
                 message: err.Error(),
                 details: extractValidationDetails(err) }
}
```

## Compilation cache

Compilation is expensive (~1ms for a non-trivial schema). Cache by `action.Name` with invalidation on update:

```go
type SchemaCache struct {
    mu    sync.RWMutex
    items map[string]cached   // key: action name
}

type cached struct {
    schema    *jsonschema.Schema
    updatedAt time.Time        // from Action.UpdatedAt
}

func (c *SchemaCache) Get(name string, raw []byte, updatedAt time.Time) (*jsonschema.Schema, error) {
    c.mu.RLock()
    if it, ok := c.items[name]; ok && it.updatedAt.Equal(updatedAt) {
        c.mu.RUnlock()
        return it.schema, nil
    }
    c.mu.RUnlock()

    compiled, err := jsonschema.CompileString(name, string(raw))
    if err != nil { return nil, err }

    c.mu.Lock()
    c.items[name] = cached{compiled, updatedAt}
    c.mu.Unlock()
    return compiled, nil
}
```

- Size bound: 4096 schemas (LRU eviction). Tunable via `AMEBO_SCHEMA_CACHE_SIZE`.
- The cache invalidates when `UpdatedAt` on the action changes — so registering an updated schema is visible immediately on that node.

**Cross-node invalidation:** when `CMD_ACTION_UPSERT` applies via Raft, the FSM also calls `schemaCache.Invalidate(name)` so every node drops its stale entry.

## Error reporting

Validation errors are converted to a structured shape:

```json
{
  "error": {
    "code": "schema_validation_failed",
    "message": "payload does not match schema",
    "details": [
      {"path": "/customer_id", "keyword": "required", "message": "missing required property"},
      {"path": "/amount",      "keyword": "type",     "message": "expected number, got string"}
    ]
  }
}
```

The library's `ValidationError` has a walkable tree; we flatten it with a max of 20 entries (avoid mega-payloads in the response).

## Dialect policy

- Accept schemas in Draft 7, 2019-09, and 2020-12.
- Default dialect when `$schema` is omitted: Draft 2020-12.
- `$ref` resolution: local refs only. External refs (HTTP, file) rejected — schemas are self-contained.

## Custom keywords / formats

None in v1. Operators who need `date`, `email`, `uri` etc. get the library's built-in format validators, opt-in via `jsonschema.Format = true` in the compiler config.

## Size and complexity limits

- Schema size ≤ 256 KB.
- Depth of nested schemas ≤ 16 (protection against recursion bombs).
- `$defs` count ≤ 256.

Enforced before compilation.

## Redact header parsing

`X-Amebo-Redact: address.zip address.street items[].serial`

Grammar (informal):
- Paths are space-separated.
- Each path is dot-separated.
- `[]` denotes array-of-objects; the field inside applies to each element.
- Reject paths with `..`, leading `.`, trailing `.`, or unsupported syntax.

Path parser lives in `internal/redact/path.go`; shared with spec 014.

## CLI helper

```
amebo actions validate --schema my-schema.json
```

Locally compiles and validates the schema file without touching the server. Handy for CI pipelines that want to fail before rollout.

## Observability

Metrics:
- `amebo_schema_compile_total{action=...}` — counter, spikes are expected on schema updates; sustained high values indicate cache thrashing.
- `amebo_schema_validation_total{action=..., result="ok|fail"}`
- `amebo_schema_validation_duration_seconds{action=...}` — histogram.

Logs: validation failures at INFO (not WARN — they're client errors, expected volume).

## Acceptance criteria

- [ ] `POST /v1/actions` with a valid schema is accepted and the schema is retrievable via `GET /v1/actions/:name`.
- [ ] Registering an invalid schema returns 400 with the library's error message.
- [ ] Publishing an event against an action whose schema rejects the payload returns 400 with path-level details.
- [ ] Updating a schema is reflected immediately on the leader and within one Raft round-trip on followers.
- [ ] Benchmark: validating a 2KB payload against a 5KB schema → ≤ 50 µs P99 on a modern CPU.
- [ ] `amebo actions validate` exits non-zero on a bad schema file.

## Alternatives considered

- **CEL or custom DSL**: more expressive but alien to users. JSON Schema is the de facto standard.
- **Protobuf schemas instead of JSON Schema**: forces clients to generate code. Rejected — amebo's users are polyglot and often dynamic.
- **Schema versioning (v1, v2 per action)**: deferred to v1.1. For v1, action names can encode version (`v1.customers.created`, `v2.customers.created`) — a convention, not a feature.
