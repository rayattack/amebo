# 022 — Performance Targets & Benchmarks

## Summary

Quantitative goals for v1 and the methodology for measuring them. These targets guide implementation choices; regressions are tracked as first-class bugs.

## Reference hardware

All targets assume:

- **Node**: 4 vCPU, 8 GB RAM, NVMe SSD (~1 GB/s write).
- **Network**: 10 Gb/s within cluster, ≤ 1 ms RTT between nodes.
- **Cluster**: 3 nodes, all voters.
- **OS**: Linux 6.x, `ulimit -n` ≥ 65k, default TCP tuning.

Benchmarks on different hardware are reported separately; targets track this reference.

## Throughput targets

| Workload | Target (per cluster) | Notes |
|---|---|---|
| Event ingest (sustained, 3 replicas) | ≥ 10,000 events/sec | Single action, single publisher, 2KB payload, no subscribers |
| Event ingest (with 10 subs) | ≥ 8,000 events/sec | Fan-out cost included |
| Event ingest (with 100 subs) | ≥ 4,000 events/sec | Fan-out cost dominates |
| Webhook delivery | ≥ 20,000 deliveries/sec to fast mock sinks | Reconciler-bound |
| Read (local, eventually consistent) | ≥ 50,000 req/sec per node | Cached admin list |
| Read (linearizable via Barrier) | ≥ 5,000 req/sec cluster-wide | One Raft RTT per read |

## Latency targets

Measured at 50% of throughput target:

| Operation | P50 | P99 | P99.9 |
|---|---|---|---|
| `POST /v1/events` end-to-end | < 5 ms | < 25 ms | < 100 ms |
| Raft propose → apply | < 3 ms | < 15 ms | < 50 ms |
| Webhook delivery one-hop | < 10 ms | < 50 ms | < 200 ms |
| Schema validation (2KB, simple) | < 50 µs | < 200 µs | < 1 ms |
| Redaction apply (5 paths, 2KB) | < 50 µs | < 200 µs | < 1 ms |

## Durability guarantees at target load

- No committed event lost under any single-node failure (kill -9).
- No committed event lost under a symmetric network partition that resolves.
- Data-at-rest encryption of secrets is intact after snapshot/restore.

## Footprint targets

| Resource | Target |
|---|---|
| Idle RSS | < 200 MB |
| RSS at 5k events/sec sustained | < 1 GB |
| Goroutines at rest | < 200 |
| Goroutines under load | < 5,000 (bounded by delivery concurrency + HTTP) |
| Raft log file size | < 1 GB before snapshot threshold |
| Badger LSM + vlog at 10M events retained 7 days | ≤ 50 GB per node |

## Startup targets

| Event | Target |
|---|---|
| Fresh bootstrap → accepting writes | < 3 seconds |
| Cold start with 10M events in data dir → `/ready` 200 | < 30 seconds |
| Follower join → caught up from snapshot | < 60 seconds for 1 GB state |
| Leader election after leader loss | < 3 seconds (typical), < 10 seconds (worst case) |

## Failure-mode targets

- **Kill leader under load**: delivery pauses for ≤ 5 seconds, resumes.
- **Kill follower under load**: no visible effect.
- **Kill two of three nodes**: cluster unavailable until quorum restored (expected).
- **Fill data disk**: clean error responses (not crash); readiness goes red.

## Measurement methodology

All targets measured with the following harness, committed under `test/bench/`:

- **Load generator**: Go program issuing `POST /v1/events` concurrently with a configurable deduper space and payload template.
- **Sink**: Go program accepting POSTs, recording latency + status, returning 200. Configurable for injected latency/errors.
- **Runner**: script that starts a 3-node cluster, runs load + sinks, collects Prometheus metrics, emits a JSON report.

Reports include:
- Throughput (p50/p95/p99 per second).
- Latency histograms from server and client.
- CPU, memory, disk I/O (via `bench` system-level sampler).
- Raft metrics (apply latency, log growth).

## CI enforcement

A `make bench` target runs a reduced version of the benchmark (1-minute run) on CI reference runners. A result worse than 80% of the targets above fails the build — not a raw regression check but a floor guarantee.

Full benchmark suite runs nightly on dedicated hardware; reports published to a static site.

## Known sacrifices

Things we explicitly give up to hit these targets:

- **Exactly-once delivery**: we provide at-least-once. Idempotency is the subscriber's job (the `X-Amebo-Event-Id` header supports this).
- **Synchronous follower reads**: local reads may be stale up to one Raft RTT. `?consistency=strong` is available but slower.
- **Ordered cross-action delivery**: events across different actions have no ordering promise. Per-action order is preserved.
- **Unbounded retention**: default TTL of 7 days on events. Longer retention requires more disk and periodic compaction cost.

## Stretch targets (v1.1)

Not required for v1, aspirational for v1.1:

- 50k events/sec with batched `POST /v1/events:batch`.
- Cross-region Raft (with tuned election timeouts) supported as a documented topology.
- Follower-local linearizable reads via lease-based read optimization (saves the Barrier RTT).
- Per-subscription circuit breakers (reduces wasted delivery attempts to a broken subscriber).

## Anti-targets (NOT goals)

We explicitly do **not** optimize for:

- Single-node throughput > 50k events/sec (a single-node deployment is a dev workflow, not production).
- First-byte latency under 1 ms (we can get there, but the cost is alignment with the Raft round-trip which is more important for correctness).
- Sub-100ms failover (Raft protocol floors this; we don't try to beat it).

## Acceptance criteria

- [ ] Benchmark harness under `test/bench/` reproduces each target on reference hardware.
- [ ] CI `make bench` enforces the 80%-of-target floor.
- [ ] Published nightly benchmark report shows historical trend, flags regressions.
- [ ] Each target has a corresponding Grafana panel on the bundled dashboard.

## Alternatives considered

- **Target only ingest throughput (ignore delivery throughput)**: misleading — delivery is the user-visible output.
- **Publish only averages**: p99/p99.9 matter more for broker workloads.
- **Scale targets with cluster size (e.g. linear with N nodes)**: Raft is not linearly scalable — writes don't speed up with more voters. 3-node targets are the right floor.
