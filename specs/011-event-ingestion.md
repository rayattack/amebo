# 011 — Event Ingestion Pipeline

## Summary

The happy path for `POST /v1/events` — from HTTP handler to Raft commit to fan-out. This spec ties together spec 004 (keyspace), 006 (Raft), 009 (auth), and 010 (schema validation).

## Endpoint

`POST /v1/events`

**Headers:** HMAC auth (see spec 009).

**Body:**
```json
{
  "action": "v1.customers.created",
  "deduper": "cust-123-v1",        // idempotency key; optional but strongly recommended
  "payload": { /* user JSON */ },
  "metadata": { /* optional JSON */ },
  "sleep_until": "2026-04-23T12:00:00Z"  // optional; delay delivery until this time
}
```

**Success response (201):**
```json
{
  "event": "01HXABCDEF...",
  "action": "v1.customers.created",
  "deduper": "cust-123-v1",
  "created_at": "2026-04-23T10:00:00Z",
  "fanout": 7,                      // number of subscriptions matched
  "redacted": false                 // whether response payload is redacted
}
```

**Idempotent conflict (200):**
If a prior event with the same `(action, deduper, payload_sha256)` exists, return 200 with the existing event's id and `"deduplicated": true`. No new state.

## Handler pipeline

```
┌────────────────────┐
│ 1. HMAC auth       │ → reject 401 on bad sig
├────────────────────┤
│ 2. Body parse      │ → reject 400 on malformed JSON
├────────────────────┤
│ 3. Size check      │ → reject 413 if payload > MAX_PAYLOAD
├────────────────────┤
│ 4. Action lookup   │ → reject 404 if unknown, 403 if inactive app
├────────────────────┤
│ 5. Schema validate │ → reject 400 with details (spec 010)
├────────────────────┤
│ 6. Leader check    │ → 421 redirect if follower
├────────────────────┤
│ 7. Dedupe probe    │ → short-circuit 200 if collision
├────────────────────┤
│ 8. Propose to Raft │ → wait for apply; 504 on timeout
├────────────────────┤
│ 9. Respond 201     │
└────────────────────┘
```

Step 7 is a local read — it's a cache-miss optimization, not a correctness check. The real dedupe check happens inside FSM Apply (step 8b below).

## Proposing the event

The handler constructs:

```go
cmd := &pb.Command{
    Type:      pb.CMD_EVENT_INSERT,
    RequestId: requestID,
    ProposedAtUnixNs: time.Now().UnixNano(),
    Payload: mustMarshal(&pb.EventInsertPayload{
        EventId:    uuidv7.String(),        // generated here, leader-side
        Action:     req.Action,
        Deduper:    req.Deduper,
        Payload:    req.PayloadRaw,          // raw bytes, not re-encoded
        Metadata:   req.MetadataRaw,
        SleepUntil: req.SleepUntil,          // default zero
    }),
}
```

Important:
- **The leader generates the event ID.** Followers must not — replay would diverge.
- **`time.Now()` only at the handler** (leader-side). The FSM uses `ProposedAtUnixNs` deterministically.

## FSM apply for `CMD_EVENT_INSERT`

Executed on all nodes when the log entry commits:

```go
func (f *FSM) applyEventInsert(idx uint64, cmd *pb.Command) error {
    var p pb.EventInsertPayload
    if err := proto.Unmarshal(cmd.Payload, &p); err != nil { return errCorruptLog }

    return f.store.Update(func(tx storage.Txn) error {
        // 8a. Re-check action (may have been deleted between propose and apply)
        action, err := getAction(tx, p.Action)
        if err != nil { return apiErr("action_not_found") }

        // 8b. Dedupe index check
        dedupeKey := model.IdxEventDedupe(p.Action, p.Deduper, sha256Hex(p.Payload))
        if existing, err := tx.Get(dedupeKey); err == nil {
            // Return existing ID; handler translates to 200 response
            return &DedupeHit{ExistingID: string(existing)}
        }

        // 8c. Write event
        ev := &pb.Event{
            Id: p.EventId, Action: p.Action, Deduper: p.Deduper,
            Payload: p.Payload, Metadata: p.Metadata,
            CreatedAt: cmd.ProposedAtUnixNs,
        }
        if err := putProto(tx, model.EventKey(p.EventId), ev); err != nil { return err }

        // 8d. Indexes
        tx.Set(model.IdxEventsByAction(p.Action, p.EventId), nil)
        tx.Set(dedupeKey, []byte(p.EventId))

        // 8e. Fan out: scan subscriptions for this action, write a gist each
        prefix := model.IdxSubsByAction(p.Action)
        it := tx.Iter(prefix, storage.IterOptions{})
        defer it.Close()
        count := 0
        for it.Next() {
            subID := extractSubID(it.Key())
            gist := &pb.Gist{
                Id: uuidv7FromSeed(p.EventId, subID),  // DETERMINISTIC
                EventId: p.EventId, SubscriptionId: subID,
                Completed: false, Retries: 0,
                SleepUntil: p.SleepUntil,
                CreatedAt: cmd.ProposedAtUnixNs,
            }
            putProto(tx, model.GistKey(gist.Id), gist)
            tx.Set(model.IdxGistsByEvent(p.EventId, gist.Id), nil)
            tx.Set(model.IdxGistsBySub(subID, gist.Id), nil)
            tx.Set(model.IdxPendingGist(time.Unix(0, gist.SleepUntil), gist.Id), nil)
            count++
        }

        // 8f. Record fanout count in response
        return &EventInsertResult{EventID: p.EventId, Fanout: count}
    })
}
```

### Determinism note

Every FSM node must produce the same state. Points of concern:

- **Gist IDs**: UUIDv7 normally includes a random component. For deterministic FSM replay, we generate them as `uuidv7FromSeed(event_id, sub_id)` — a UUIDv5-style hash inside the v7 timestamp. All nodes derive the same gist ID.
- **Iteration order over subscriptions**: Badger range iteration is deterministic (lexicographic on key). All nodes write the same set of gists in the same order.
- **`time.Now()`**: never used inside Apply. `CreatedAt`/`SleepUntil` come from the command.

## Response path

The FSM returns a value through `raft.ApplyFuture.Response()`:

- `*EventInsertResult{EventID, Fanout}` → handler responds 201.
- `*DedupeHit{ExistingID}` → handler responds 200 with `"deduplicated": true`.
- `error` → handler responds 4xx/5xx based on error type.

## Wake signal

After FSM Apply commits a `CMD_EVENT_INSERT`, the FSM sends a non-blocking signal to the wake channel consumed by the delivery worker (spec 012):

```go
select { case f.wake <- struct{}{}: default: }
```

This is how we get "instant" delivery without the Postgres `LISTEN/NOTIFY` machinery — it's a bare channel in the same process.

## Redacted response

When the handler formats the 201 response, if the action has any redactions registered, payload echo in the response body is redacted (spec 014). The stored payload is unchanged.

## Concurrency and ordering

- Events with the same action are totally ordered (by Raft log index). Gist fan-out per event is also ordered.
- Different actions may interleave — Raft serializes all writes but semantically there's no ordering promise across actions.
- Two concurrent POSTs with the same deduper produce one event: whichever Raft commits first wins; the second collides at step 8b.

## Failure modes

| Condition | Handler response |
|---|---|
| Raft apply times out (5s) | 504 `{"code": "apply_timeout"}` — client retries with same request_id for idempotency |
| Not leader | 421 with `X-Amebo-Leader` |
| Storage error inside FSM | 500 `{"code": "storage_error"}` — operator alerts, data inspection needed |
| Action deleted mid-propose | 404 `{"code": "action_not_found"}` |

## Rate shape

- 10k events/sec ingest target (spec 001, 022).
- Each event's fan-out work is bounded by number of subscribers for that action. A million-subscriber action would destabilize the system — we cap subscriptions per action at 10,000 (configurable via `AMEBO_MAX_SUBS_PER_ACTION`), rejecting `POST /v1/subscriptions` above the cap.

## Batched ingest (future)

Not in v1. `POST /v1/events:batch` that takes an array and produces one Raft log entry for N events is planned for v1.1 if single-event RTT becomes a bottleneck.

## Observability

Metrics:
- `amebo_events_ingested_total{action, result="ok|dedup|invalid|error"}`
- `amebo_events_fanout` (histogram of subscribers per event)
- `amebo_event_ingest_duration_seconds` (end-to-end, including Raft)
- `amebo_event_propose_duration_seconds` (Raft propose-to-apply)
- `amebo_gists_created_total`

## Acceptance criteria

- [ ] Publishing an event with a valid schema and one subscriber creates one gist and triggers delivery within 100 ms.
- [ ] Re-publishing the exact same event (same action/deduper/payload) returns 200 with `"deduplicated": true` and does not create a second gist.
- [ ] Different payload, same deduper: creates a new event (payload is part of the dedupe key).
- [ ] Follower-side POST returns 421; the client retry against the leader succeeds.
- [ ] Deterministic gist IDs: a three-node cluster converges to the same gist IDs for the same event.
- [ ] Cap of `AMEBO_MAX_SUBS_PER_ACTION` enforced at subscription creation time.

## Alternatives considered

- **Gist IDs generated at Apply time with random component**: breaks determinism. Rejected.
- **Event ID generated at Apply time**: would require the leader's handler to wait for apply before responding — doable but adds latency. Generating at handler is cheaper.
- **Keep payload dedupe as `(deduper, payload)` SQL unique constraint literal port**: requires a secondary index we already have (`IdxEventDedupe`). Preserved.
- **Validate schema inside Apply (on all nodes)**: safer for replay but makes the leader's 400 response path impossible — by the time we know it's invalid, the log is committed. Validation at the handler before propose is correct.
