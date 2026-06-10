# 021 — Migration from Python Amebo

## Summary

How existing users move from Python amebo (Postgres-backed) to amebo-go. The migration is a one-way, low-downtime import that replays historical state into a new Go cluster, with a compatibility switch for clients that can't be upgraded simultaneously.

## Target audience

Two groups:

1. **Small deployments** (single Python instance, modest event volume): import in one pass, cutover.
2. **Larger deployments** (multiple Python instances behind a load balancer, high event volume): dual-run mode where both stacks accept writes during a transition window, then cutover.

## Migration modes

### Mode A — Cold cutover (simplest)

1. Stand up a new amebo-go cluster (3 nodes).
2. Stop all Python amebo instances.
3. Run `amebo import python` against the Postgres database.
4. Point clients at the new cluster.
5. Decommission Python + Postgres.

Downtime: duration of the import (minutes to ~1 hour for large datasets).

### Mode B — Dual-write with drain

1. Stand up amebo-go alongside Python.
2. Enable `AMEBO_LEGACY_SIG=true` on amebo-go (spec 009) so existing clients work unchanged.
3. Clients begin **dual-writing** (publish to both Python and Go) via a client-side shim or a reverse-proxy fanout. Applications and actions are pre-seeded on Go by the import tool.
4. Subscribers receive from both. Idempotency via `X-Amebo-Event-Id` prevents double-processing.
5. When a soak period passes (e.g., 7 days, no errors), cut reads off Python.
6. Stop Python, stop dual-writes.

Downtime: zero, at the cost of brief double-delivery during soak.

## The `amebo import python` command

```
amebo import python \
    --source-dsn postgresql://user:pass@host:5432/amebo \
    --target-addr http://amebo-1:3310 \
    --secret $AMEBO_CLUSTER_SECRET \
    --include-events --include-gists \
    --batch-size 500 \
    --from 2026-01-01T00:00:00Z
```

Flags:

| Flag | Purpose |
|---|---|
| `--source-dsn` | Postgres DSN of running Python amebo |
| `--source-pgdump <file>` | Alternatively, a pg_dump-produced SQL file |
| `--target-addr` | Leader of the new Go cluster (follows 421 redirects) |
| `--secret` | Cluster admission secret |
| `--include-events` | Import historical events (default: true) |
| `--include-gists` | Import gist delivery records (default: false — usually pointless to import delivery history) |
| `--from` | Only events created at/after this timestamp |
| `--batch-size` | Records per Raft command (default 500) |
| `--dry-run` | Show counts, propose nothing |
| `--resume-from` | Continue a previous import (see Resume below) |

## Ordering of import

The importer walks entities in dependency order:

1. **Credentials** — admin users. Preserves password hashes as-is (bcrypt compatible).
2. **Applications** — including `secret` (re-encrypted at rest in the new cluster), `apikey_hash`, `active`.
3. **Actions** — including `schemata`. Each schema is re-validated; import aborts on a schema that doesn't compile.
4. **Subscriptions** — including `max_retries`, `handler`, `description`.
5. **Redactions** — batch-insert.
6. **Events** — in chronological order (by `timestamped`). UUIDs preserved; see note below.
7. **Gists** — only if `--include-gists`. State (completed/retries/sleep_until) preserved.

## ID preservation

Python uses UUIDv4. amebo-go uses UUIDv7 for new IDs but **stores them as opaque strings**, so v4 IDs import fine. Chronological iteration over imported events is approximate (by CreatedAt timestamp, not by v7's embedded time) — good enough.

## Authentication secrets during import

Application HMAC secrets in Python are stored in plaintext. The importer:

1. Reads the plaintext secret.
2. Encrypts with the new cluster's data-at-rest key (spec 009).
3. Proposes `CMD_APP_UPSERT` with the ciphertext.

The plaintext **never hits disk on the new cluster**. Memory-only during the migration.

## Resume

Imports can fail midway (network blip, target timeout). The importer records progress in a local file `.amebo-import.state.json`:

```json
{
  "started_at": "2026-04-23T10:00:00Z",
  "phase": "events",
  "cursor": {"events_before": "2026-03-15T04:22:11Z"},
  "imported": {"applications": 42, "actions": 217, "events": 1830422}
}
```

`amebo import python --resume-from .amebo-import.state.json` picks up where it left off — the entity order is stable, cursors are monotone, and Raft-level dedupe (command `request_id`) prevents double-apply if a retry happens mid-batch.

## Schema drift

Python amebo's schema is frozen — we don't accept updates that have landed post-fork. The importer expects the schema described in `init-db.sql` and `amebo/constants/scripts.py`. If columns are missing or extra, it errors with instructions.

## Legacy signature support

`AMEBO_LEGACY_SIG=true` accepts body-only HMAC signatures (spec 009). Intended as a temporary switch — log a WARN on every request using legacy sig. Remove the flag in v2.

## API path compatibility

Every `/v1/*` and `/v8/*` path in the Python implementation is served by the Go implementation with matching request/response shapes. Diffs:

| Path | Diff vs Python |
|---|---|
| `POST /v1/events` response | Adds `"fanout": N`; clients can ignore |
| `POST /v1/applications` response | Always returns `api_key` and `secret` on create; Python sometimes returned only one (inconsistent). Tightened. |
| Redaction placeholder string | Configurable; matches `"**redacted**"` by default |
| Error envelopes | Fields renamed (`error.code`, `error.message`) — Python was inconsistent |

A compatibility mode flag `--compat=python` makes error envelopes match the exact Python shape, for clients that parse error bodies. Default off (we want the cleaner shape going forward).

## Throughput during import

The importer batches writes into Raft commands of `--batch-size` items. Practical throughput on a 3-node cluster with NVMe storage: ~20k events/sec import rate. Large imports (100M events) take ~80 minutes — plan accordingly.

Progress reporting:
```
Applications:   42 / 42     ✓
Actions:       217 / 217    ✓
Subscriptions: 1,482 / 1,482 ✓
Redactions:     37 / 37      ✓
Events:     12,830,422 / 48,212,908  [ETA 29 min, 18,230 ev/s]
```

## Verification post-import

`amebo import verify`:

- Compares counts per entity between source and target.
- Samples N random events, re-fetches both sides, diffs payloads.
- Reports any discrepancies.

## Rollback

If the migration is aborted after cutover, the Python database is still intact (read-only during Mode A; live during Mode B). Point clients back.

If the new cluster has accepted writes that don't exist in Python, those writes are lost on rollback — document this trade-off prominently.

## Acceptance criteria

- [ ] `amebo import python --dry-run` reports accurate counts against a real Python Postgres database.
- [ ] Full import of a 10M-event database completes without errors and `import verify` reports zero diffs.
- [ ] `--resume-from` recovers from a killed import and continues exactly where it stopped.
- [ ] `AMEBO_LEGACY_SIG=true` accepts body-only signatures with deprecation WARN.
- [ ] All `/v1/*` paths in the Python implementation respond identically (shapes) on the Go implementation with `--compat=python`.
- [ ] An integration test imports a minimal Python schema dump and verifies the expected state.

## Alternatives considered

- **Live replication via logical decoding**: would need to ship a Postgres CDC tool. Out of scope — the one-shot importer is simpler.
- **Re-key all secrets during import (forcing clients to rotate)**: would be more secure but breaks clients mid-migration. Preserve existing secrets; rotate afterward.
- **Reject invalid schemas during import**: would be more correct, but some Python deployments have schemas that were accepted by the older Python validator and would fail the newer Go validator. Provide a `--lenient-schemas` flag that preserves them as-is without re-validation.
