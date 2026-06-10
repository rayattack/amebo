# 014 — Redaction Engine

## Summary

Field-level redaction of event payloads on the **read path only**. The stored payload is never altered — the raw bytes in `Event.Payload` remain intact. Redaction is applied when rendering admin API responses and UI views.

## Scope of redaction

- Applied in `GET /v1/events`, `GET /v1/gists` (when including payload), `GET /p/events` UI.
- **Not applied** on outbound webhook delivery — subscribers see the raw payload. Redaction is an operator-visibility concern, not a subscriber-visibility one.
- Admin users with a `--show-raw` token flag (future) may bypass redaction; v1 always redacts.

## Data model

See spec 004: `Redaction{Action, FieldPath, CreatedAt}` stored at key `RD\x00<action>\x00<field_path>`, indexed at `IRA\x00<action>\x00<field_path>`.

## Field path grammar

```
path        := segment ("." segment)*
segment     := identifier | identifier "[]"
identifier  := [a-zA-Z_][a-zA-Z0-9_]*
```

Examples:
- `address.zip` — nested object field.
- `items[].serial` — apply to every element of array `items`, then its `serial` field.
- `payments[].card.number` — two levels, with array traversal.
- `tags[]` — redact each element of array `tags` directly (primitive values).

**Not supported in v1:**
- Wildcard matches (`*`, `**`).
- JSONPath expressions (`$.items[*].serial`).
- Filtering (`items[type=='cc'].number`).

## Parser

`internal/redact/path.go`:

```go
type PathSegment struct {
    Name      string
    IsArray   bool     // trailing []
}

type Path []PathSegment

func ParsePath(s string) (Path, error)
```

Unit tests cover: empty, leading dot, trailing dot, double dot, invalid chars, unbalanced brackets, deeply nested, malformed array syntax. Fuzz test rejects crashes.

## Applicator

Works on parsed JSON (`map[string]any` / `[]any`) — not on raw bytes.

```go
package redact

func Apply(payload []byte, paths []Path) ([]byte, bool, error) {
    if len(paths) == 0 { return payload, false, nil }
    var doc any
    if err := json.Unmarshal(payload, &doc); err != nil {
        return payload, false, err
    }
    for _, p := range paths {
        redactPath(doc, p)
    }
    out, err := json.Marshal(doc)
    return out, true, err
}

func redactPath(node any, p Path) {
    if len(p) == 0 { return }
    seg := p[0]
    rest := p[1:]
    switch v := node.(type) {
    case map[string]any:
        child, ok := v[seg.Name]
        if !ok { return }
        if seg.IsArray {
            arr, ok := child.([]any)
            if !ok { return }
            for i := range arr {
                if len(rest) == 0 {
                    arr[i] = redactedValue
                } else {
                    redactPath(arr[i], rest)
                }
            }
        } else {
            if len(rest) == 0 {
                v[seg.Name] = redactedValue
            } else {
                redactPath(child, rest)
            }
        }
    }
}

var redactedValue = "**redacted**"
```

**Mismatched types are silently ignored** — if a path expects an array but finds a string, we do nothing rather than erroring. Redaction is best-effort; a malformed path is the operator's problem to fix.

## Loading redactions for a response

```go
func LoadForAction(tx storage.Txn, action string) ([]Path, error) {
    it := tx.Iter(model.IdxRedactionsByAction(action), storage.IterOptions{})
    defer it.Close()
    var paths []Path
    for it.Next() {
        fp := extractFieldPath(it.Key())
        p, err := redact.ParsePath(fp)
        if err != nil { continue }   // logged, not fatal
        paths = append(paths, p)
    }
    return paths, nil
}
```

## Batch optimization

When listing events across a page, we avoid repeated lookups:

```go
cache := map[string][]Path{}
for _, ev := range page.Events {
    paths, ok := cache[ev.Action]
    if !ok {
        paths, _ = LoadForAction(tx, ev.Action)
        cache[ev.Action] = paths
    }
    ev.Payload, _, _ = redact.Apply(ev.Payload, paths)
}
```

This is the pattern the Python implementation uses — we preserve it.

## Registration API

**Create:** `POST /v1/redactions`
```json
{ "action": "v1.customers.created", "field_path": "address.zip" }
```
Auth: admin cookie.

**List:** `GET /v1/redactions?action=...` — paginated.

**Delete:** `DELETE /v1/redactions/:id` where `id` is `base64(action+"\x00"+field_path)` (since there's no synthetic PK).

**Bulk register via action header:** `POST /v1/actions` accepts `X-Amebo-Redact: path1 path2 path3` (see spec 010). Internally emits multiple `CMD_REDACTION_UPSERT` commands.

## Special-case paths

- **Root redaction (`""`)**: disallowed — that would erase the whole payload; operators should delete the action instead.
- **Redacting a schema-required field**: allowed. The schema validates the **raw** payload at ingest, so redaction applied at read time doesn't affect validation.

## Replacement value

- Default: the string `"**redacted**"`.
- Configurable per-server via `AMEBO_REDACT_PLACEHOLDER` (e.g. `"***"`, `null`, `""`).
- Per-redaction override is not supported in v1 (could add a `replacement` field to `Redaction` in v1.1).

## Performance

- Parsing paths: cached at package-scope keyed by action (lifetime = process; invalidated when `CMD_REDACTION_UPSERT` or `CMD_REDACTION_DELETE` applies).
- Applying: O(payload size × paths). For typical 2KB payloads and ≤10 paths, submicrosecond.

## Observability

Metrics:
- `amebo_redactions_applied_total{action}`
- `amebo_redactions_cache_hits_total`
- `amebo_redactions_cache_misses_total`
- `amebo_redactions_parse_errors_total` — signals operator misconfiguration.

## Acceptance criteria

- [ ] Given an action with redaction `address.zip`, `GET /v1/events` for an event containing `address.zip` returns the redacted placeholder instead of the real value.
- [ ] Path `items[].serial` redacts each element's `serial` field; non-array `items` silently ignored.
- [ ] Registering a new redaction invalidates the cache within one Raft round-trip on all nodes (verified by listing events on a follower immediately after registration).
- [ ] Outbound webhook delivery retains the raw, unredacted payload (inspect with a mock sink).
- [ ] Fuzz test of `ParsePath` over 1M inputs produces no crashes.
- [ ] A payload size benchmark shows redaction adds < 10% overhead for 5-path / 2KB payloads.

## Alternatives considered

- **Store redacted payload instead of applying at read time**: saves CPU on read but loses ability to change redaction rules without rewriting history. Rejected.
- **JSONPath for paths**: more powerful, but heavier runtime and confusing for most users. Deferred.
- **Per-subscription redaction (redact when delivering to subscribers)**: useful for multi-tenant subscribers but a significant feature on its own. Deferred to v1.1.
