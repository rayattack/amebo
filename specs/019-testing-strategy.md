# 019 — Testing Strategy

## Summary

Four tiers of tests, each with a clear purpose and a hard budget. Tests that cross tiers are an anti-pattern we actively prevent.

## Tiers

| Tier | Scope | Tool | Runtime budget | Runs when |
|---|---|---|---|---|
| Unit | One package, pure | `go test` | < 30s total | every commit (pre-commit hook + CI) |
| Integration | Multi-package, in-process cluster | `go test -tags=integration` | < 3 min | CI on PR |
| End-to-end | Real binary, real network | `go test -tags=e2e` | < 10 min | CI on PR + nightly |
| Chaos | Real binary, fault injection | custom harness | open-ended | nightly |

## Tier 1 — Unit

- Every package has a `_test.go` file.
- Table-driven tests are the default idiom.
- Mocks are local to the test file, written by hand — no mocking frameworks.
- Test time advances via a fake clock (`github.com/benbjohnson/clock`) in code that reads time.
- Goal: 80% line coverage on `internal/*`; 95% on `internal/model`, `internal/redact`, `internal/storage/keys`.

**Examples:**
- `internal/model/keys_test.go`: key encoding round-trips, sort-order properties.
- `internal/redact/path_test.go`: path parser acceptance + rejection cases.
- `internal/aproko/backoff_test.go`: exponential backoff with fake clock.

## Tier 2 — Integration

Run a full amebo process in the test binary using `raft.NewInmemTransport` for Raft and `badger.WithInMemory(true)` for storage. Three-node clusters spin up in a few hundred ms.

Scaffolding in `internal/testutil`:

```go
type Cluster struct {
    Nodes []*Node
    T     *testing.T
}

func NewCluster(t *testing.T, size int) *Cluster { ... }
func (c *Cluster) Leader() *Node                  { ... }
func (c *Cluster) KillLeader()                    { ... }
func (c *Cluster) HealPartition()                 { ... }
func (c *Cluster) Shutdown()                      { ... }
```

**Scenarios covered:**
- Bootstrap → join → 3-node cluster.
- Publish 10k events, verify all 3 nodes converge.
- Kill leader mid-write, verify new leader, verify no data loss.
- Partition a follower, heal, verify catch-up via snapshot.
- Register schema, publish invalid event, verify rejection.
- Register redaction, list events, verify masked output.
- Deduplicate: two POSTs same deduper → one event.
- Reconciler: publish + mock subscriber returning 500 → retries with backoff → succeeds eventually.
- Reconciler only runs on leader (kill leader, new leader starts reconciler).

Build tag `integration` so `go test ./...` stays under 30s; `go test -tags=integration ./...` is separate.

## Tier 3 — End-to-end

Uses the **real binary** (built once per run), real TCP, real Badger on disk. Spins up 3 processes in goroutines, each with its own dirs and ports.

Test binary is a Go program in `test/e2e/` that:

1. Compiles `cmd/amebo` to a temp dir.
2. Starts three processes (bootstrap + 2 joins).
3. Exercises the full API: create app, register action, subscribe with a local HTTP sink, publish events, verify delivery.
4. Shuts everything down.

**Scenarios:**
- Happy path end-to-end.
- SIGTERM graceful shutdown mid-delivery → pending gists survive restart.
- Config-driven bootstrap (3 nodes same config).
- Rolling restart: stop+start one node at a time, verify continuity.
- Restore from snapshot on a 4th node.

Total runtime cap: 10 minutes.

## Tier 4 — Chaos

Longer-running, runs nightly. Uses `toxiproxy` in front of Raft transports to inject latency, packet loss, partitions.

Scenarios:
- Random kill -9 every 30s for 10 minutes; verify no data loss (compare event counts written vs events observable).
- 30% packet loss on Raft port for 5 minutes; verify cluster recovers.
- Clock skew (±2 minutes across nodes); verify correctness of signatures and timestamps.
- Disk full simulation on leader; verify error path and no corruption.

These tests aren't deterministic and don't block CI, but a regression surfaces within a day.

## Fuzz tests

Go's native fuzzing. Enabled in CI as a 30-second-per-target job on PRs and a 10-minute-per-target job nightly.

Targets:
- `internal/redact.ParsePath` — never crashes on arbitrary input.
- `internal/redact.Apply` — never crashes on arbitrary JSON.
- `internal/model.Decode*` key decoders.
- JWT parser (spec 009).
- HMAC verification (spec 009).
- Protobuf command unmarshal.

Corpus stored under `testdata/fuzz/`; failing seeds committed.

## Benchmarks

`go test -bench=. -benchmem` per package. CI records benchmark results and fails a PR if a benchmark regresses by > 20%.

Key benchmarks:
- Storage: put/get/iterate at 1k/10k/100k keys.
- Raft propose throughput, single-node, 3-node in-memory.
- Event ingest RPS through the full pipeline (handler → Raft → FSM → response) on a 3-node cluster.
- Webhook client throughput to a local mock (should saturate Go's HTTP client, not Amebo).
- Redaction apply over 2KB/10KB/100KB payloads with 1/5/25 paths.

Reference hardware for committed numbers: 4c8g, NVMe. Published in spec 022.

## Race detector

All unit and integration tests run with `-race` in CI. Any data race fails the PR.

## Linting

`golangci-lint` in CI (spec 002). Additionally:
- `gofumpt -l -d .` — stricter than gofmt.
- `errcheck` — all errors must be checked or explicitly `_ = ...`.
- `noctx` — catches `http.NewRequest` without context.

## Test data and fixtures

- `testdata/schemas/` — sample JSON Schemas (valid and invalid).
- `testdata/payloads/` — matching payloads.
- `testdata/python-dump/` — a real Python amebo Postgres dump used by spec 021 tests.
- Golden files for deterministic outputs (`-update` flag regenerates).

## Observability in tests

- Test logger defaults to WARN+ to keep output clean; flip to DEBUG with `AMEBO_TEST_LOG=debug`.
- Test harness exposes metrics via an embedded registry; assertions can check counters/histograms.

## Flakiness policy

- A test failing intermittently in CI is quarantined within 24 hours (moved to a `_quarantine_test.go` with `t.Skip` + bug ticket).
- Quarantine limit: 5 open at any time. Hit the limit, bug-fix work takes priority.

## Acceptance criteria

- [ ] `go test ./...` runs in under 30s and covers every package.
- [ ] `go test -tags=integration ./...` runs in under 3 min.
- [ ] `go test -tags=e2e ./...` runs in under 10 min on CI runners.
- [ ] CI reports benchmark diffs on every PR.
- [ ] Fuzz targets listed above exist and run in CI.
- [ ] Coverage ≥ 80% on `internal/*`, ≥ 95% on listed hot packages.
- [ ] Chaos suite has at least 3 scenarios running nightly with reports archived.

## Alternatives considered

- **testify mocks**: too much magic; rejected in favor of hand-written mocks where needed.
- **Separate test repo**: fragmentation. Tests live with the code.
- **100% coverage as a hard gate**: punishes small refactors. 80% is enough signal.
