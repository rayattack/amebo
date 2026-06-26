# 006 — Raft Consensus

## Summary

Use `github.com/hashicorp/raft` for cluster consensus. All writes to state flow through the Raft log; followers apply the committed log to their local Badger. This spec defines the FSM, log entry format, and the propose-then-wait write path.

## Why hashicorp/raft

See conversation context and spec 001. Summary: it's batteries-included (transport, log store, snapshot store, leadership callbacks), single-group Raft matches our workload (we're a broker, not a sharded DB), and rqlite's source serves as a reference implementation.

## Node topology

- **One Raft group per cluster.** All nodes are peers. One is leader at any time.
- **Voters vs non-voters**: all nodes are voters in v1. Non-voter (learner) support deferred — useful for read-heavy expansion but adds bootstrap complexity we don't need yet.
- **Expected size**: 3 or 5 nodes for HA. 1 node for dev. 7+ works but not recommended (quorum latency).

## Log entry format

Every mutation to state is a serialized `Command`:

```protobuf
message Command {
  CommandType type = 1;
  bytes       payload = 2;     // type-specific payload, protobuf-encoded
  string      request_id = 3;  // idempotency key for retryable proposes
  int64       proposed_at_unix_ns = 4;
}

enum CommandType {
  CMD_UNSPECIFIED = 0;
  CMD_APP_UPSERT = 1;
  CMD_APP_TOGGLE_ACTIVE = 2;
  CMD_APP_SET_SECRET = 3;
  CMD_APP_SET_APIKEY = 4;
  CMD_ACTION_UPSERT = 10;
  CMD_ACTION_DELETE = 11;
  CMD_EVENT_INSERT = 20;
  CMD_SUB_INSERT = 30;
  CMD_SUB_DELETE = 31;
  CMD_GIST_COMPLETE = 40;         // one gist, for small updates
  CMD_GIST_RETRY = 41;
  CMD_GIST_BATCH = 42;            // batched completion/retry from reconciler
  CMD_GIST_ACKNOWLEDGE = 43;
  CMD_GIST_REPLAY = 44;
  CMD_REDACTION_UPSERT = 50;
  CMD_REDACTION_DELETE = 51;
  CMD_CREDENTIAL_UPSERT = 60;
  CMD_RETENTION_SWEEP = 70;       // TTL-driven deletion batch
}
```

**Why typed commands instead of a generic "KV set" log?**
- We can version behavior per command (e.g. schema-evolve how events are inserted without breaking old log replay).
- We can validate at FSM apply time — invariants live with the command type.
- We can add metrics per command type cheaply.

## FSM

```go
package raftfsm

type FSM struct {
    store storage.Store
    log   *slog.Logger
    wake  chan<- struct{}   // signal delivery worker (spec 012)
}

func (f *FSM) Apply(entry *raft.Log) any {
    var cmd pb.Command
    if err := proto.Unmarshal(entry.Data, &cmd); err != nil {
        f.log.Error("corrupt log entry", "index", entry.Index, "err", err)
        return errCorruptLog  // returned to the proposer; Raft still marks applied
    }
    switch cmd.Type {
    case pb.CMD_EVENT_INSERT:
        return f.applyEventInsert(entry.Index, cmd)
    // ... one case per command
    }
}

func (f *FSM) Snapshot() (raft.FSMSnapshot, error) { /* delegates to storage.Snapshot */ }
func (f *FSM) Restore(r io.ReadCloser) error       { /* delegates to storage.Restore */ }
```

### Apply rules

- **Deterministic**. Given the same log entry, every node must produce the same state. Forbidden: `time.Now()`, `rand`, map iteration order (use sorted keys), network I/O.
- **Timestamps come from the command**, not `time.Now()`. The leader stamps `ProposedAtUnixNs` when constructing the command.
- **UUIDs come from the command**, not generated inside Apply. The leader generates them before Propose.
- **Errors returned from Apply go back to the proposer** via `raft.ApplyFuture.Response()`. They do **not** roll back the log entry — Raft already committed. Surface the error in the HTTP response so the client retries with a fresh request_id if appropriate.

### Post-apply side effects

After a successful `CMD_EVENT_INSERT`, signal the delivery worker:

```go
case pb.CMD_EVENT_INSERT:
    if err := f.applyEventInsert(entry.Index, cmd); err != nil {
        return err
    }
    select { case f.wake <- struct{}{}: default: } // non-blocking
    return nil
```

Non-blocking send is important — we never back-pressure the Raft apply loop.

## Write path from HTTP handler

```go
// internal/ingest/propose.go
func (p *Proposer) Propose(ctx context.Context, cmd *pb.Command) error {
    data, _ := proto.Marshal(cmd)
    if len(data) > 1<<20 {
        return ErrCommandTooLarge
    }
    future := p.raft.Apply(data, 5*time.Second)
    if err := future.Error(); err != nil {
        return fmt.Errorf("raft apply: %w", err)
    }
    if resp := future.Response(); resp != nil {
        if err, ok := resp.(error); ok {
            return err
        }
    }
    return nil
}
```

### Not-the-leader handling

- The handler first checks `p.raft.State() == raft.Leader`.
- If not leader, the handler returns HTTP 421 Misdirected Request with header `X-Amebo-Leader: <leader_addr>` so clients can redirect.
- An optional client-side middleware in our Go SDK follows the redirect automatically. No proxy/forwarding on the server side — we keep the hop explicit so operators see it in metrics.

**Alternative considered**: transparent forwarding from follower to leader. Rejected for v1 because it complicates auth propagation and hides load asymmetry. Revisit if clients find the redirect UX painful.

## Log store and snapshot store

- **LogStore** (Raft log of pending/committed entries): `raft-boltdb/v2` in v1. Simple, proven. Path: `<data_dir>/raft/log.bolt`.
- **StableStore** (Raft metadata: current term, voted-for): same boltdb file, different bucket.
- **SnapshotStore**: `raft.FileSnapshotStore` at `<data_dir>/raft/snapshots/`.

**Upgrade path**: once workload stresses boltdb, swap to `raft-pebble`. The interface is the same — configurable via `AMEBO_RAFT_LOG_BACKEND`. Deferred to v1.1.

## Transport

- TCP with optional mTLS.
- Bind to `AMEBO_RAFT_ADDR` (default `:3410`).
- Advertise `AMEBO_RAFT_ADVERTISE` (for NAT / docker scenarios).
- mTLS: when `AMEBO_TLS_CERT`/`AMEBO_TLS_KEY` are set, the Raft transport uses the same cert. Peers verify by CA. This is all the security model we need for v1 — simple and consistent with HTTP.

## Snapshotting policy

hashicorp/raft config:
- `SnapshotInterval = 2 * time.Minute`
- `SnapshotThreshold = 8192` log entries
- `TrailingLogs = 10240`

Tuned so a fresh follower catching up can usually do so from snapshot + recent log rather than the full log replay.

## Leadership changes

The server layer subscribes to `raft.LeaderCh()`:

- **On become leader**: start the reconciler goroutine (spec 012). Emit `amebo_leadership_changes_total{type="gained"}`.
- **On lose leadership**: stop the reconciler. Emit `amebo_leadership_changes_total{type="lost"}`. Any in-flight webhook deliveries complete, but no new batches are claimed.

Writes attempted during a leadership transition return HTTP 503 with `Retry-After: 1` — clients retry and get the new leader via the 421 path.

## Barrier (linearizable read)

```go
if strong {
    if err := p.raft.Barrier(5*time.Second).Error(); err != nil {
        return httpErr(503, "not linearizable: "+err.Error())
    }
}
// proceed with local read
```

`Barrier` is only meaningful on the leader. If a follower receives `?consistency=strong`, it 421-redirects.

## Testing

- **Unit**: FSM apply each command type against a fake store; golden-file the resulting state.
- **Cluster**: 3-node cluster in a single process using `raft.NewInmemTransport`, verify commits replicate and leader election works under partition simulation.
- **Jepsen-lite**: a test harness that kills nodes during writes and checks durability. Full Jepsen is a stretch goal for v1.1.

## Acceptance criteria

- [ ] `FSM.Apply` handles every `CommandType` with test coverage.
- [ ] Proposing from a follower fails with `ErrNotLeader`; the HTTP layer translates this to 421 with the leader address.
- [ ] A 3-node in-process cluster test commits 10k `CMD_EVENT_INSERT` commands and all three FSMs converge.
- [ ] Snapshot + Restore round-trip on a cluster with 100k events preserves all state.
- [ ] Leader failover happens within 3× election timeout; reconciler restarts on new leader.

## Alternatives considered

- **etcd/raft**: more control, more code. Revisit only if we hit a hashicorp/raft limitation (e.g., batching Apply for throughput).
- **dragonboat**: multi-group — unnecessary for a broadcaster with a single log.
- **No Raft, just Badger replication (e.g., litestream-style)**: async, not strongly consistent. Rejected — we want durable committed writes.
