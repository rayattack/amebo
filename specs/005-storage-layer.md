# 005 — Storage Layer

## Summary

Wrap Badger in a minimal, opinionated package (`internal/storage`) that the FSM and read paths use. Hide Badger specifics behind a `Store` interface so we can swap engines later without touching business logic.

## Interface

```go
package storage

type Store interface {
    // Reads are safe from any goroutine.
    View(func(Txn) error) error

    // Writes must only be called from the Raft FSM apply loop on the leader.
    // The non-leader path must never call Update.
    Update(func(Txn) error) error

    // Snapshot returns a read-only point-in-time view for Raft snapshotting.
    Snapshot() (Snapshot, error)

    // Restore atomically replaces state from a snapshot stream.
    Restore(io.Reader) error

    Close() error

    // RunGC runs value-log GC. Called periodically by a background goroutine.
    RunGC(discardRatio float64) error
}

type Txn interface {
    Get(key []byte) ([]byte, error)           // returns ErrNotFound if absent
    Set(key, value []byte) error
    SetTTL(key, value []byte, ttl time.Duration) error
    Delete(key []byte) error
    Iter(prefix []byte, opts IterOptions) Iterator
}

type Iterator interface {
    Next() bool
    Key() []byte
    Value() ([]byte, error)
    Close()
}

type IterOptions struct {
    Reverse     bool
    StartAfter  []byte   // for pagination cursors
    Limit       int      // 0 = unlimited
}

type Snapshot interface {
    io.Reader   // streams a deterministic byte sequence for Raft
    Close() error
}
```

## Implementation

### Opening

```go
func Open(dir string, log *slog.Logger) (Store, error) {
    opts := badger.DefaultOptions(dir).
        WithLogger(badgerSlog{log}).
        WithSyncWrites(false).              // Raft log already fsyncs
        WithCompactL0OnClose(true).
        WithNumCompactors(4).
        WithValueLogFileSize(256 << 20).    // 256 MB value log segments
        WithBlockCacheSize(256 << 20).
        WithIndexCacheSize(128 << 20).
        WithCompression(options.ZSTD).
        WithZSTDCompressionLevel(3)
    db, err := badger.Open(opts)
    // ...
}
```

**Rationale for `SyncWrites=false`:** Durability is owned by Raft. When the FSM applies a committed log entry, the entry is already fsynced on a quorum of nodes. Double-fsyncing halves our write throughput for zero benefit. A crash between Raft commit and Badger flush is recovered on restart by replaying the Raft log.

### Write path

All writes funnel through the Raft FSM (spec 006). The FSM's `Apply` method calls `store.Update(...)`. No other code path writes.

```go
func (s *BadgerStore) Update(fn func(Txn) error) error {
    return s.db.Update(func(btxn *badger.Txn) error {
        return fn(badgerTxn{btxn})
    })
}
```

### Read path

Reads are served by any node — they hit the local Badger directly. This is how followers serve reads.

**Read consistency model:**
- Default: local read, eventually consistent (may lag the leader by up to one Raft round-trip).
- Linearizable: clients that need read-after-write consistency pass `?consistency=strong`, which forces the handler to issue a Raft `Barrier()` before reading. Rare path; expect ~2× latency.

### Iteration

```go
// Example: fan-out on event ingest
prefix := model.IdxSubsByAction(event.Action)
it := txn.Iter(prefix, storage.IterOptions{})
defer it.Close()
for it.Next() {
    subID := extractSubID(it.Key())
    sub, _ := getSubscription(txn, subID)
    // ... create gist
}
```

### Value-log GC

Badger's value log needs periodic GC. A background goroutine runs:

```go
ticker := time.NewTicker(10 * time.Minute)
for range ticker.C {
    for err := s.db.RunValueLogGC(0.5); err == nil; err = s.db.RunValueLogGC(0.5) {}
}
```

GC runs on every node independently — it's local maintenance.

## Snapshot format

Snapshots are consumed by Raft for log compaction and by followers catching up after falling behind. Format:

```
magic:       "AMEBOSN1" (8 bytes)
version:     uint32 big-endian
count:       uint64 big-endian (number of key-value pairs)
repeated:
  key_len:   uint32 big-endian
  key:       bytes
  val_len:   uint32 big-endian
  val:       bytes
checksum:    sha256 over everything above (32 bytes)
```

We stream directly from a Badger `Stream`:

```go
func (s *BadgerStore) Snapshot() (Snapshot, error) {
    stream := s.db.NewStream()
    stream.NumGo = 4
    // ... pipe into our format writer
}
```

## Restore

Restore is called on a follower that needs to catch up from a snapshot. It:
1. Opens a temp dir alongside the current Badger directory.
2. Writes incoming keys to the temp dir.
3. Closes the current DB.
4. Atomically renames temp → current.
5. Reopens.

This is safe because restore always happens while Raft has us quiesced.

## Error model

Errors returned from the storage package are either:
- `ErrNotFound` (sentinel) — not an error for callers that handle absence.
- `ErrConflict` — dedupe index collision (see spec 011).
- Wrapped Badger errors — propagated with context.

No panics from the storage package except on irrecoverable corruption, which aborts the process.

## Background maintenance

One goroutine, started at `Open`, stopped at `Close`:
- Runs value-log GC every 10 min.
- Emits Prometheus metrics for LSM stats, vlog size, compaction count.

The retention sweeper (spec 004) is a separate concern, in `internal/aproko` — it issues Raft writes, so it cannot live under `internal/storage`.

## Concurrency rules

- `View` is safe from any goroutine.
- `Update` is only called from the FSM apply goroutine. This is a single-threaded path by construction — no internal locking needed in handlers.
- `Snapshot` can be called concurrently with `View` and `Update`; Badger's MVCC handles it.

## Observability

Metrics exposed (spec 017):
- `amebo_storage_lsm_size_bytes`
- `amebo_storage_vlog_size_bytes`
- `amebo_storage_compactions_total`
- `amebo_storage_vlog_gc_total`
- `amebo_storage_writes_total`, `amebo_storage_reads_total`
- `amebo_storage_op_latency_seconds{op="get|set|delete|iter"}` (histogram)

## Testing strategy

- **Unit**: each keyspace operation covered with table-driven tests against an in-memory Badger (`WithInMemory(true)`).
- **Property**: fuzz test that a sequence of writes followed by `Snapshot → Restore` reproduces the same state.
- **Benchmark**: write throughput, read throughput, iteration over 10M keys, snapshot time for 1M keys.
- **Crash**: kill `-9` during a write batch; verify on restart Raft replay reproduces the committed state.

## Acceptance criteria

- [ ] `Store` interface implemented by `BadgerStore`, all methods covered by unit tests.
- [ ] Snapshot round-trip preserves state exactly (byte-for-byte equality of all keys after Restore).
- [ ] Benchmark shows ≥ 50k writes/sec on NVMe with `SyncWrites=false`.
- [ ] Value-log GC loop observable via metrics.
- [ ] A deliberately corrupt snapshot input to `Restore` fails the restore and leaves the existing state intact.

## Alternatives considered

- **Pebble instead of Badger**: higher ceiling, more mature compaction, but requires more glue (no native TTL, no managed transactions). Leaves the option open — see spec 022, we'll benchmark both.
- **bbolt only**: single-writer lock is a non-starter for this write volume (see conversation context).
- **Direct Badger usage without an interface**: faster to ship but locks us in. The interface is ~200 lines of wrapper — cheap insurance.
- **Raw file + mmap**: would reinvent LSM. No.
