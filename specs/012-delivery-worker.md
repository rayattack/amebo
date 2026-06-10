# 012 — Delivery Worker (Aproko)

## Summary

The reconciliation loop that drives webhook delivery. This is the Go replacement for Python's `aproko.py`. Ports the logic, drops `FOR UPDATE SKIP LOCKED` (no longer needed — the worker runs only on the leader), replaces `LISTEN/NOTIFY` with an in-process channel, and adds exponential backoff.

## Scope

One reconciler goroutine per cluster — **runs only on the current Raft leader**. On leadership loss it stops; on leadership gain it starts. This eliminates multi-worker contention entirely; no locking or leasing needed because there's only one writer.

## Lifecycle

```go
// internal/aproko/worker.go
type Worker struct {
    store    storage.Store
    raft     *raft.Raft
    propose  ProposeFunc
    client   webhook.Client   // spec 013
    cfg      Config
    log      *slog.Logger
    wake     <-chan struct{}
    stop     chan struct{}
}

func (w *Worker) Run(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        case <-w.stop:
            return
        default:
        }

        n := w.traverse(ctx)

        if n == 0 {
            select {
            case <-w.wake:
            case <-time.After(w.cfg.Idles):
            case <-ctx.Done():
                return
            case <-w.stop:
                return
            }
        }
    }
}
```

The server subscribes to `raft.LeaderCh()` and calls `Start()` / `Stop()` on leadership transitions.

## The traverse phase

```go
func (w *Worker) traverse(ctx context.Context) int {
    now := time.Now()
    batch := w.claimReady(now, w.cfg.Envelope)
    if len(batch) == 0 { return 0 }

    results := w.deliver(ctx, batch)         // fan out via HTTP
    w.reconcile(results)                      // one Raft propose with all outcomes
    return len(batch)
}
```

### Claim phase

Read-only scan of the pending index:

```go
func (w *Worker) claimReady(now time.Time, limit int) []pendingGist {
    batch := make([]pendingGist, 0, limit)
    w.store.View(func(tx storage.Txn) error {
        prefix := []byte("IGP\x00")
        upper  := model.IdxPendingGistUpperBound(now)  // <= now
        it := tx.Iter(prefix, storage.IterOptions{Limit: limit})
        defer it.Close()
        for it.Next() {
            if bytes.Compare(it.Key(), upper) > 0 { break }
            gistID := extractGistID(it.Key())
            g, err := getGist(tx, gistID)
            if err != nil { continue }
            sub, err := getSub(tx, g.SubscriptionId)
            if err != nil { continue }
            ev, err := getEvent(tx, g.EventId)
            if err != nil { continue }
            app, err := getApp(tx, sub.Application)
            if err != nil { continue }
            batch = append(batch, pendingGist{g, sub, ev, app})
        }
        return nil
    })
    return batch
}
```

Notes:
- **No row-level locking.** Leader-only reconciler ensures no other worker claims the same gist.
- **Envelope** is `cfg.Envelope` (default 256). Tunable; larger batches = more throughput, more per-batch Raft commit cost.
- `MaxRetries` comparison lives in the reconcile step — we don't filter it here, so we can observe exhaustion accurately in metrics.

### Delivery phase

```go
func (w *Worker) deliver(ctx context.Context, batch []pendingGist) []result {
    results := make([]result, len(batch))
    sem := make(chan struct{}, w.cfg.ConcurrentDeliveries)  // e.g. 64
    var wg sync.WaitGroup
    for i, p := range batch {
        wg.Add(1)
        sem <- struct{}{}
        go func(i int, p pendingGist) {
            defer wg.Done()
            defer func() { <-sem }()
            results[i] = w.client.Deliver(ctx, p)  // spec 013
        }(i, p)
    }
    wg.Wait()
    return results
}
```

- Bounded concurrency via semaphore.
- Each delivery is independent — a slow subscriber doesn't block others.
- Per-delivery timeout configured on the HTTP client, not here.

### Reconcile phase

One batched Raft command per cycle:

```go
func (w *Worker) reconcile(results []result) {
    updates := make([]*pb.GistUpdate, 0, len(results))
    for _, r := range results {
        u := &pb.GistUpdate{GistId: r.GistID, AttemptedAtUnixNs: r.At.UnixNano()}
        if r.Success {
            u.Completed = true
        } else {
            u.Retries = r.PriorRetries + 1
            u.SleepUntil = w.backoff(r.PriorRetries, r.Sub.MaxRetries).UnixNano()
            u.LastError = truncate(r.Err.Error(), 512)
        }
        updates = append(updates, u)
    }
    cmd := &pb.Command{
        Type: pb.CMD_GIST_BATCH,
        Payload: mustMarshal(&pb.GistBatchPayload{Updates: updates}),
        ProposedAtUnixNs: time.Now().UnixNano(),
    }
    if err := w.propose(cmd); err != nil {
        w.log.Error("reconcile propose failed", "err", err, "n", len(updates))
        // Do not retry inline — next traverse cycle will pick up the same gists.
    }
}
```

## Backoff policy

Replaces Python's "client sets sleep_until" with server-side exponential backoff, **additive to any client-provided `sleep_until`**:

```go
func (w *Worker) backoff(retries, maxRetries int) time.Time {
    if retries >= maxRetries { return time.Time{} }       // no retry
    base := 5 * time.Second
    cap  := 1 * time.Hour
    d := base * time.Duration(1<<retries)                  // 5s, 10s, 20s, 40s, ...
    if d > cap { d = cap }
    jitter := time.Duration(rand.Int63n(int64(d / 4)))     // ±25%
    return time.Now().Add(d + jitter)
}
```

**But wait** — the FSM must be deterministic, and `rand` is not. Resolution: backoff is computed **on the leader, at propose time**, not inside Apply. The `SleepUntil` value is part of the command payload. All followers observe the same value.

If we need cross-cluster deterministic jitter later (we don't), switch to a hash-based jitter keyed on gist ID.

## FSM apply for `CMD_GIST_BATCH`

```go
func (f *FSM) applyGistBatch(cmd *pb.Command) error {
    var p pb.GistBatchPayload
    if err := proto.Unmarshal(cmd.Payload, &p); err != nil { return errCorruptLog }

    return f.store.Update(func(tx storage.Txn) error {
        for _, u := range p.Updates {
            g, err := getGist(tx, u.GistId)
            if err != nil { continue }  // may have been deleted
            g.Retries = u.Retries
            if u.Completed {
                g.Completed = true
                g.SleepUntil = 0
            } else {
                g.SleepUntil = u.SleepUntil
            }
            g.LastError = u.LastError

            putProto(tx, model.GistKey(g.Id), g)

            // Pending index maintenance
            oldPending := model.IdxPendingGist(time.Unix(0, u.PriorSleepUntil), g.Id)
            tx.Delete(oldPending)
            if !g.Completed && g.Retries < u.MaxRetries && g.SleepUntil > 0 {
                tx.Set(model.IdxPendingGist(time.Unix(0, g.SleepUntil), g.Id), nil)
            }
        }
        return nil
    })
}
```

Hint: `PriorSleepUntil` and `MaxRetries` are carried in the per-update payload to keep Apply deterministic without re-reading (they're part of what the leader observed at claim time).

## Manual replay

`POST /v1/gists/:id/replay` (admin auth):
- Loads the gist.
- Resets `SleepUntil = 0`, `Retries = 0` (preserves `Completed = false`).
- Writes a `CMD_GIST_REPLAY` to Raft; FSM reinserts into pending index.
- Reconciler picks it up next cycle.

`POST /v1/regists/:id` in the Python API maps to this.

`POST /v1/gists/:id/acknowledge` is a receipt endpoint — sets `Acknowledged = true` for audit/UI purposes; does not change delivery state.

## Retention sweeper

A second goroutine (also leader-only) periodically deletes expired state:

```go
// Every retention_sweep_interval (default 5 min)
func (w *Worker) sweep() {
    var expiredEvents []string
    var expiredGists  []string
    w.store.View(func(tx storage.Txn) error {
        // find events older than EventTTL
        // find completed gists older than CompletedGistTTL
        // find failed gists past MaxRetries older than FailedGistTTL
        return nil
    })
    if len(expiredEvents)+len(expiredGists) == 0 { return }

    // Chunk to keep Raft entries < 1MB
    for _, chunk := range chunks(expiredEvents, expiredGists, 1000) {
        w.propose(&pb.Command{
            Type: pb.CMD_RETENTION_SWEEP,
            Payload: mustMarshal(chunk),
            ProposedAtUnixNs: time.Now().UnixNano(),
        })
    }
}
```

Spec 004 defines the TTLs.

## Handling subscription changes mid-flight

If a subscription is deleted while a gist for it is in flight:
- The FSM's `CMD_SUB_DELETE` apply leaves existing gists intact (they're historical records), just removes the index entry so new events stop fanning out.
- The next reconciler cycle may still pick up pending gists for the deleted sub. We handle this in `claimReady` by checking subscription existence — if missing, we propose `CMD_GIST_COMPLETE` with a synthesized "subscription deleted" result.

## Config

| Key | Default | Purpose |
|---|---|---|
| `AMEBO_ENVELOPE` | 256 | Batch size per traverse cycle |
| `AMEBO_IDLES` | 5s | Idle sleep when no work and no wake signal |
| `AMEBO_CONCURRENT_DELIVERIES` | 64 | Semaphore size for parallel webhook POSTs |
| `AMEBO_BACKOFF_BASE` | 5s | Base of exponential backoff |
| `AMEBO_BACKOFF_CAP` | 1h | Cap per attempt |
| `AMEBO_RETENTION_EVENTS` | 168h | Event TTL |
| `AMEBO_RETENTION_GISTS_OK` | 24h | Completed gist TTL |
| `AMEBO_RETENTION_GISTS_FAIL` | 168h | Failed (exhausted) gist TTL |
| `AMEBO_RETENTION_SWEEP_INTERVAL` | 5m | How often the sweeper runs |

## Observability

Metrics:
- `amebo_delivery_batch_size` (histogram)
- `amebo_delivery_cycle_duration_seconds`
- `amebo_delivery_attempted_total{result="ok|fail"}`
- `amebo_delivery_retry_count{attempt="1|2|3|..."}`
- `amebo_gists_pending` (gauge, scraped from index size)
- `amebo_gists_completed_total`
- `amebo_gists_exhausted_total` (reached max retries)
- `amebo_reconciler_running` (gauge 0/1; 1 on leader)

Log lines:
- `delivery.cycle` (INFO) — batch size, successes, failures, duration.
- `delivery.exhausted` (WARN) — per gist, when max retries reached.

## Acceptance criteria

- [ ] Reconciler runs only on the leader; gauge goes 0→1 on election, 1→0 on lose.
- [ ] A down subscriber recovers all events once it comes back, bounded by retries.
- [ ] Exponential backoff observed: 5s, 10s, 20s, 40s (+ jitter) across consecutive attempts.
- [ ] Retention sweep deletes events past TTL and the corresponding index entries.
- [ ] Killing the leader mid-delivery does not lose in-flight gists — next leader's reconciler re-claims them from the pending index.
- [ ] Benchmark: a cycle delivering 256 webhooks to a mock sink completes in < 200 ms on a 3-node cluster.

## Alternatives considered

- **Keep multi-worker + lease-based claiming** (Python model): works, but introduces locking and duplicate-delivery risk. Leader-only is simpler and correct.
- **Backoff inside FSM Apply with deterministic jitter**: possible, but cleaner to compute on the leader and carry in the command.
- **One Raft commit per delivery outcome**: crushes throughput (256× more log entries). Batched commits in `CMD_GIST_BATCH` are essential.
- **Store `last_error` forever**: noisy and unbounded. Truncate to 512 bytes and rotate.
