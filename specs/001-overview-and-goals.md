# 001 — Overview & Goals

## Summary

Rewrite amebo in Go as a single static binary that replicates itself across nodes without external dependencies. Preserve the Python implementation's HTTP API surface, event semantics, and operational model. Replace the Postgres/SQLite storage + fan-out pattern with embedded Badger + hashicorp/raft.

## Why Go, why now

The Python implementation is functional and has been measured at ~220M events/day. The motivation for a rewrite is not throughput — it is **deployment shape**. Today amebo requires an external Postgres (or sacrifices durability with SQLite). A self-contained broker that replicates itself via Raft is a materially different product: it deploys like NATS, Consul, or etcd — `scp` a binary, bootstrap the first node, `join` the rest.

Go is selected because its ecosystem for embedded distributed systems (hashicorp/raft, etcd/raft, Badger, Pebble, rqlite, dqlite) is unmatched in any other language, and the concurrency model maps cleanly onto amebo's reconciler loop and fan-out.

## Goals

1. **Single-binary deployment.** No external database, no sidecar, no message broker. A working cluster is N copies of the binary plus a config file each.
2. **API compatibility** with the Python implementation for all JSON endpoints listed in spec 015. Existing amebo clients continue to work against amebo-go without changes.
3. **Durable, replicated state** via Raft. A committed event survives the failure of any minority of nodes.
4. **Exactly the same delivery contract** as Python amebo: at-least-once delivery, signed webhooks, retries bounded by `max_retries` per subscription, `sleep_until` for backoff windows.
5. **Operationally boring.** Prometheus metrics, structured logs, health endpoints, graceful shutdown, `/debug/pprof`. No surprises.
6. **Horizontal read scaling** via followers serving reads; writes go through the leader.

## Non-goals

1. **No new features in the first cut.** Every feature not present in the Python version is out of scope until v1.1. Parity first.
2. **Not a queue.** Amebo is a broadcaster — one event fans out to N subscribers. Consumer groups, partitions, ordering guarantees beyond per-event are out of scope.
3. **Not multi-region by design.** Single-region Raft cluster is the supported topology. Cross-region is possible but not a first-class configuration.
4. **Not a schema evolution tool.** Schemas are stored as-is; evolution is the client's responsibility.
5. **No Postgres or SQLite backend.** Storage is Badger + Raft. This is a deliberate departure from the Python implementation.

## Success criteria

- A three-node cluster survives a single-node kill with no data loss and writes continue within 5 seconds of leader loss.
- Throughput on commodity hardware (4-core, 8GB, NVMe) sustains ≥ 10k events/sec ingest with three replicas.
- P99 ingest latency < 25 ms at 5k events/sec sustained.
- Memory footprint idle < 200 MB per node; steady-state < 1 GB under load.
- A webhook subscriber that is down recovers all missed events once it comes back, bounded by `max_retries` and `sleep_until`.
- The Python integration test suite (ported to hit the Go binary) passes unchanged for API-level tests.

## Primary user story

A developer runs `amebo init` on one machine, `amebo serve` on three machines, `amebo join` on two of them. They now have a three-node HA event broker. They register applications and actions via the admin API, wire their services to POST events and receive webhooks. They never touch a database.

## Architectural shape

```
            ┌────────────────────────────────────────────────┐
            │                  amebo node                    │
            │                                                │
  HTTP ───► │  HTTP router ──► auth ──► handlers ──► FSM ──► │──► Badger (state)
            │                              │                 │
            │                              ├──► raft propose ├──► Raft log (Pebble/BoltDB)
            │                              │                 │
            │                   ┌──────────┴──────────┐      │
            │                   │   wake channel      │      │
            │                   └──────────┬──────────┘      │
            │                              ▼                 │
            │               reconciler (aproko) ──► HTTP ──► │──► subscribers
            └────────────────────────────────────────────────┘
                              ▲
                              │ Raft transport (TCP)
                              ▼
                       other nodes in cluster
```

## Explicit trade-offs

- **We lose Postgres's observability and tooling** (psql, pg_dump, external backups) in exchange for operational simplicity.
- **We take on ownership of Raft operational concerns** (snapshot compaction, split-brain recovery, peer replacement) that Postgres would have handled.
- **We lose SQL ad-hoc queries** over event history. Replacement: a richer admin API and a read-only SQL export tool (future, not v1).
- **We lose `FOR UPDATE SKIP LOCKED`** as the concurrency primitive. Replacement: the reconciler runs only on the Raft leader, eliminating multi-worker contention entirely (spec 012).

## Alternatives considered

- **Rust + Tokio + openraft**: ~20% faster, ~3× more engineering effort, weaker ecosystem for dynamic JSON schemas. Rejected for the cost/benefit ratio.
- **Keep Postgres, rewrite only the worker in Go**: incremental but leaves the deployment story unchanged. Rejected — the deployment story is the point.
- **etcd/raft instead of hashicorp/raft**: more powerful but lower-level. Rejected for time-to-first-cluster (see spec 006).
- **Dragonboat (multi-group raft)**: solves sharding we don't need. Rejected as premature.
- **SQLite + Litestream/rqlite**: valid alternative, but rqlite is itself hashicorp/raft under the hood — we'd be reimplementing rqlite's wrapper. Considered re-using rqlite as a library; rejected because we want fine-grained control over FSM state layout.

## Open questions

- Should we expose the Raft log as an admin-readable stream (for external consumers)? Deferred to v1.1.
- Per-subscription rate limiting — in scope? Probably yes but out of v1.
- TLS termination: bundled cert management (like Consul's auto-encrypt) or leave to operator? Defer to spec 020.
