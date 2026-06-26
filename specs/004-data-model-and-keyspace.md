# 004 — Data Model & Keyspace

## Summary

Port the relational schema (applications, actions, events, subscriptions, gists, redactions, credentials) onto a Badger KV keyspace. Define key encoding, secondary indexes, and iteration patterns. This spec is the contract between the FSM (spec 006) and everything that reads state (specs 011, 012, 015).

## Entities

All entities are stored as protobuf-serialized values (see "Serialization" below). Primary keys mirror the Python schema for migration fidelity.

### Application
```go
type Application struct {
    Name         string    // PK
    Address      string    // base URL of the app
    SecretHash   string    // bcrypt hash of HMAC secret for signing verification — see note
    APIKeyHash   string    // bcrypt hash of bearer API key
    Active       bool
    CreatedAt    time.Time
}
```
> **Note on `SecretHash`:** Python amebo stores the HMAC secret in plaintext because HMAC verification requires the raw secret. We preserve that for wire compatibility: `Secret` is stored encrypted-at-rest with a key derived from `AMEBO_SECRET` + node UUID, not hashed. The field is named `SecretCipher` to make that explicit.

```go
type Application struct {
    Name         string
    Address      string
    SecretCipher []byte   // AES-GCM encrypted HMAC secret
    APIKeyHash   string   // bcrypt
    Active       bool
    CreatedAt    time.Time
}
```

### Action
```go
type Action struct {
    Name         string    // PK, e.g. "v1.customers.created"
    Application  string    // FK -> Application.Name
    Schema       []byte    // raw JSON Schema (bytes, as stored)
    CreatedAt    time.Time
}
```

### Event
```go
type Event struct {
    ID           string    // UUID v7, PK (sortable by time)
    Action       string    // FK -> Action.Name
    Deduper      string    // idempotency key (client-supplied)
    Payload      []byte    // raw JSON payload
    Metadata     []byte    // raw JSON metadata (may be nil)
    CreatedAt    time.Time
}
```

### Subscription
```go
type Subscription struct {
    ID           string    // UUID v7, PK
    Application  string    // FK — subscriber
    Action       string    // FK — action being subscribed to
    Handler      string    // webhook URL
    MaxRetries   int
    Description  string
    CreatedAt    time.Time
}
```

### Gist (delivery attempt record)
```go
type Gist struct {
    ID             string    // UUID v7
    EventID        string
    SubscriptionID string
    Completed      bool
    Acknowledged   bool
    Retries        int
    SleepUntil     time.Time  // zero value = eligible now
    CreatedAt      time.Time
}
```

### Redaction
```go
type Redaction struct {
    Action    string
    FieldPath string  // dot path, e.g. "address.zip" or "items[].serial"
    CreatedAt time.Time
}
```

### Credential (admin)
```go
type Credential struct {
    Username     string  // PK
    PasswordHash string  // bcrypt
    UpdatedAt    time.Time
}
```

## Serialization

- **Format**: protobuf (proto3), generated from `internal/model/model.proto`.
- **Why not JSON in Badger**: protobuf is faster, smaller, and versionable. JSON payloads inside events are still stored as `[]byte` verbatim — we don't re-encode user data.
- **Why not gob**: gob is Go-only, protobuf keeps the door open to cross-language clients consuming snapshots.

Timestamps serialize as `google.protobuf.Timestamp`. UUIDs as strings (v7, lexicographically sortable by creation time — this matters for iteration, see below).

## Keyspace design

Keys are byte slices with structured prefixes. Design principles:

- Prefix bytes identify entity and index kind.
- Keys sort lexicographically; we use this to range-scan time windows and index buckets.
- All keys start with a 2-byte prefix so we can add new entities without collision.

### Primary keys

| Entity | Key | Value |
|---|---|---|
| Application | `AP\x00<name>` | protobuf Application |
| Action | `AC\x00<name>` | protobuf Action |
| Event | `EV\x00<uuidv7>` | protobuf Event |
| Subscription | `SU\x00<uuidv7>` | protobuf Subscription |
| Gist | `GS\x00<uuidv7>` | protobuf Gist |
| Redaction | `RD\x00<action>\x00<field_path>` | protobuf Redaction |
| Credential | `CR\x00<username>` | protobuf Credential |

The `\x00` separator is safe because none of our identifiers (UUIDs, slug-style action names, field paths) contain NUL bytes. We validate this on insert.

### Secondary indexes

Indexes are keys that point to primary keys — the pattern is `index_prefix → primary_key`. Writing an entity writes primary + all indexes atomically in a Badger transaction.

**Actions by application** (list actions an app owns):
```
IAA\x00<application>\x00<action> → \x00
```
Range-scan prefix `IAA\x00<app>\x00` to enumerate.

**Subscriptions by action** (fan-out lookup on event ingest):
```
ISA\x00<action>\x00<subscription_id> → \x00
```
This is the hot path. Range-scan prefix `ISA\x00<action>\x00` on every event.

**Subscriptions by application** (an app's outgoing webhooks):
```
ISAP\x00<application>\x00<subscription_id> → \x00
```

**Events by action** (admin listing, replay):
```
IEA\x00<action>\x00<event_id> → \x00
```
Event IDs are UUIDv7, so iteration is chronological.

**Gists by event** (replay a single event to all subscribers):
```
IGE\x00<event_id>\x00<gist_id> → \x00
```

**Gists by subscription** (replay all gists for a subscription):
```
IGS\x00<subscription_id>\x00<gist_id> → \x00
```

**Pending-delivery index** (spec 012 reads this every cycle):
```
IGP\x00<sleep_until_unix_nanos_be>\x00<gist_id> → \x00
```
- `sleep_until_unix_nanos_be` is an 8-byte big-endian encoding of Unix nanoseconds — sorts naturally.
- Only gists with `Completed=false AND Retries < MaxRetries` have an entry here. Completion or retry exhaustion deletes the index entry.
- The reconciler scans prefix `IGP\x00` up to the current time, yielding ready-to-deliver gists in order.

**Redactions by action** (event read path):
```
IRA\x00<action>\x00<field_path> → \x00
```

### Deduper index
```
IED\x00<action>\x00<sha256(deduper||payload)> → <event_id>
```
The Python schema has a unique constraint on `(deduper, payload)`. We mirror it with an index key whose value is the existing event ID — on conflict the handler returns the existing event (see spec 011).

## Key encoding helpers

```go
package model

type Key []byte

func AppKey(name string) Key            { return join("AP", name) }
func ActionKey(name string) Key         { return join("AC", name) }
func EventKey(id string) Key            { return join("EV", id) }
func SubKey(id string) Key              { return join("SU", id) }
func GistKey(id string) Key             { return join("GS", id) }

func IdxSubsByAction(action string) Key { return joinPrefix("ISA", action) }
func IdxPendingGist(sleepUntil time.Time, gistID string) Key {
    ts := make([]byte, 8)
    binary.BigEndian.PutUint64(ts, uint64(sleepUntil.UnixNano()))
    return joinRaw("IGP", ts, gistID)
}
// etc.
```

All encoding lives in `internal/model/keys.go` with exhaustive unit tests. No other package concatenates keys manually.

## UUID choice

- **UUIDv7** for all IDs (events, subscriptions, gists).
- Rationale: v7 is time-ordered, so iteration is chronological and Badger's LSM compaction is friendlier than with random v4 keys.
- Library: `github.com/google/uuid` (v1.4+ supports v7).

## Migration compatibility

Python amebo uses v4 UUIDs. During import (spec 021) we preserve them as-is — v4 and v7 are both 128-bit and our keys treat them as opaque strings. Chronological iteration is approximate for imported data, which is acceptable.

## Access patterns reference

| Pattern | Implementation |
|---|---|
| "Fetch application by name" | Get `AP\x00<name>` |
| "List all apps, paginated" | Range `AP\x00` with cursor = last key seen |
| "Fan out new event" | Range `ISA\x00<action>\x00` |
| "List events for an action" | Range `IEA\x00<action>\x00`, newest last (reverse iterate) |
| "Find pending gists ready now" | Range `IGP\x00` up to `IGP\x00<now_be>\xff` |
| "Mark gist completed" | Write `GS\x00<id>` with `Completed=true`; delete `IGP\x00...` entry |
| "Replay all gists for a subscription" | Range `IGS\x00<sub_id>\x00`, re-queue each |
| "Load redactions for action" | Range `IRA\x00<action>\x00` |

## Cardinality and storage estimates

For 220M events/day retained 30 days, 10 subscribers per action average:
- Events: ~6.6B rows × ~2KB avg = ~13 TB. **Clearly infeasible to retain in-process** — see TTL below.
- Gists: ~66B rows × ~200B = ~13 TB. Same problem.

**Retention is a first-class concern.** Without it, a self-contained broker collapses under its own history.

## Retention and TTL

Spec 012 and spec 017 expand on this; the data model support:

- **Events**: configurable TTL (default 7 days). Implemented as a background sweeper that deletes `EV\x00<id>` + all index entries when `now > CreatedAt + TTL`.
- **Completed gists**: configurable TTL (default 24 hours). Failed gists past `max_retries` have a separate TTL (default 7 days, for audit).
- **Badger TTL**: Badger supports per-key TTL natively. We use it for the primary row; index cleanup is done by the sweeper to keep indexes consistent.

## Size limits

Enforced at ingest (spec 011):
- Event payload ≤ 1 MB (configurable via `AMEBO_MAX_PAYLOAD`).
- Metadata ≤ 64 KB.
- Schema ≤ 256 KB.
- Deduper ≤ 256 bytes.
- Names (action, application) ≤ 128 bytes, ASCII alphanumeric + `.` + `-` + `_`.

## Acceptance criteria

- [ ] `internal/model/keys.go` exposes typed constructors for every key above with table-driven tests covering round-trips and sort order.
- [ ] A property-based test verifies that `IdxPendingGist` keys sort by `sleep_until` ascending.
- [ ] A benchmark measures the Badger range-scan cost for `IdxSubsByAction` across 1k, 10k, 100k subscriptions on a single action — the event fan-out hot path.
- [ ] Proto definitions in `internal/model/model.proto` generate Go code reproducibly (committed + `go generate` reproduces them).

## Alternatives considered

- **msgpack instead of protobuf**: smaller than JSON, no schema; rejected because protobuf's schema-as-code makes migrations safer.
- **Flat keys without prefixes (just UUIDs)**: loses range-scan capability for indexes. Rejected.
- **Storing indexes in a separate Badger database**: complicates transactional atomicity. Rejected.
- **Random UUIDs (v4) for primary keys**: simpler, but hurts LSM locality and loses time-ordering. Rejected in favor of v7.
