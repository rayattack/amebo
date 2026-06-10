# Amebo-Go Specifications

This directory contains the specifications for rewriting [amebo](https://github.com/rayattack/amebo) in Go as a **self-contained, self-replicating HTTP event notifications broker**.

The headline change versus the Python implementation is that amebo-go ships as a **single static binary with no external database dependency**. Persistence and replication are provided in-process by embedded Badger (storage) and hashicorp/raft (consensus).

## Reading order

The specs are numbered for reading order. Earlier specs establish concepts later specs depend on.

| # | Spec | Topic |
|---|------|-------|
| 001 | [Overview & Goals](001-overview-and-goals.md) | Vision, non-goals, success criteria |
| 002 | [Project Bootstrap](002-project-bootstrap.md) | Repository layout, tooling, dependencies |
| 003 | [Configuration](003-configuration.md) | Env vars, config file, CLI flag precedence |
| 004 | [Data Model & Keyspace](004-data-model-and-keyspace.md) | Entities, key encoding, secondary indexes |
| 005 | [Storage Layer](005-storage-layer.md) | Badger integration, transactions, iteration |
| 006 | [Raft Consensus](006-raft-consensus.md) | hashicorp/raft integration, FSM, log store |
| 007 | [Cluster Membership](007-cluster-membership.md) | Bootstrap, join, leave, snapshot, recovery |
| 008 | [HTTP Server](008-http-server.md) | Framework, middleware, graceful shutdown |
| 009 | [Authentication](009-authentication.md) | JWT, HMAC signatures, API keys |
| 010 | [Schema Registry](010-schema-registry.md) | JSON Schema registration and validation |
| 011 | [Event Ingestion](011-event-ingestion.md) | Validation → propose → fan-out gists |
| 012 | [Delivery Worker](012-delivery-worker.md) | Reconciler loop, wake signals, backoff |
| 013 | [Webhook Client](013-webhook-client.md) | Outbound HTTP, signatures, timeouts |
| 014 | [Redaction Engine](014-redaction-engine.md) | Field path parser, read-time masking |
| 015 | [Admin API](015-admin-api.md) | Applications, actions, subscriptions, gists, redactions |
| 016 | [Web UI](016-web-ui.md) | Templates, HTMX, static assets |
| 017 | [Observability](017-observability.md) | Logging, Prometheus metrics, health |
| 018 | [CLI](018-cli.md) | Cobra commands: serve, join, leave, snapshot, admin |
| 019 | [Testing Strategy](019-testing-strategy.md) | Unit, integration, cluster, fuzz |
| 020 | [Packaging & Deployment](020-packaging-and-deployment.md) | Binary, Docker, systemd, k8s |
| 021 | [Migration from Python](021-migration-from-python.md) | Data export/import, API compatibility |
| 022 | [Performance Targets](022-performance-targets.md) | SLOs and benchmark methodology |

## Status

These specs are **design-stage**. They describe intent, not shipped behavior. Each spec has its own Acceptance Criteria section — an item is "done" when the criteria are met, not when the code is merged.

## Contributing to the specs

- Change one spec per PR where possible.
- Call out cross-spec impacts explicitly — if changing 006 forces changes in 011, update both.
- Prefer concrete interfaces, types, and keyspace layouts over prose.
- Record rejected alternatives in the "Alternatives considered" section so decisions are auditable.
