# 007 — Cluster Membership & Operations

## Summary

Defines how nodes form a cluster, join an existing one, leave gracefully, recover from failure, and how the operator interacts with all of the above.

## Lifecycle

```
  ┌────────┐  amebo serve --bootstrap  ┌──────────┐
  │ fresh  ├──────────────────────────►│ single-  │
  │  node  │                           │ node     │
  └────────┘                           │ leader   │
                                       └────┬─────┘
                                            │ other nodes join
                                            ▼
                                       ┌──────────┐
                                       │ multi-   │
                                       │ node     │
                                       │ cluster  │
                                       └────┬─────┘
                                            │ amebo leave
                                            ▼
                                       ┌──────────┐
                                       │ departed │
                                       └──────────┘
```

## Bootstrap (first node of a new cluster)

```
amebo serve --bootstrap --node-id node-1 --raft-addr 10.0.0.1:3410 \
            --bind-addr 0.0.0.0:3310 --data-dir /var/lib/amebo \
            --secret $SECRET --admin-pass $ADMIN_PASS
```

**Behavior:**
1. Open Badger; if `data/.initialized` exists, `--bootstrap` is a no-op (idempotent restart).
2. Construct Raft config with `BootstrapCluster` including only self.
3. `raft.BootstrapCluster(...)` writes the initial configuration.
4. Apply an initial `CMD_CREDENTIAL_UPSERT` with the admin credentials.
5. Write `data/.initialized`.
6. Begin serving HTTP.

**Guardrails:**
- Refuse `--bootstrap` if `data/.initialized` exists AND the stored cluster config has peers beyond self (prevents split-brain on accidental re-bootstrap).
- Log a prominent warning on any bootstrap that includes `--force-bootstrap` (operator-only escape hatch for disaster recovery).

## Join (add a node to an existing cluster)

```
amebo serve --node-id node-2 --raft-addr 10.0.0.2:3410 \
            --bind-addr 0.0.0.0:3310 --data-dir /var/lib/amebo \
            --join-addrs http://10.0.0.1:3310 --secret $SECRET
```

**Behavior:**
1. Open Badger (empty).
2. Start Raft in follower-of-nothing state.
3. POST `/v1/cluster/join` to one of the `JoinAddrs`:
   ```json
   {"node_id": "node-2", "raft_addr": "10.0.0.2:3410"}
   ```
   Signed with `AMEBO_SECRET` — cluster admission is cluster-wide-secret-authenticated.
4. The receiving node forwards to the leader if necessary (or responds 421).
5. Leader calls `raft.AddVoter(node_id, raft_addr, 0, 0)`.
6. The new node receives a snapshot + log, catches up, begins applying.
7. New node writes `data/.initialized` after its first successful apply.

**Failure modes:**
- Join times out (60s default) → the joining node exits non-zero. Operator re-runs.
- Node ID collision → leader rejects; joining node exits with clear error.

## Leave (graceful departure)

```
amebo leave --node-id node-2 --addr http://10.0.0.1:3310 --secret $SECRET
```

or from the leaving node itself:

```
amebo leave --self
```

**Behavior:**
1. CLI POSTs `/v1/cluster/leave` to the leader with the target node_id.
2. Leader calls `raft.RemoveServer(node_id, 0, 0)`.
3. The leaving node's Raft goroutine detects it's no longer a voter and shuts down gracefully.
4. The node's HTTP server continues serving read-only traffic until SIGTERM (configurable grace period, default 30s). This lets a rolling-restart drain cleanly.

**Not supported in v1:** automatic leave on SIGTERM. Departure is always explicit — mass sigterm during a crash should **not** shrink the cluster.

## Forced removal (failed node)

```
amebo force-remove --node-id node-2 --addr http://10.0.0.1:3310 --secret $SECRET
```

For nodes that have died and won't come back. Requires `--yes` flag for scripting safety. Dangerous if used on a live node — leader will cut it off from the cluster; the removed node continues to think it's a member until it observes it's been removed.

## Cluster status

```
amebo status --addr http://10.0.0.1:3310
```

Calls `GET /v1/cluster/status`:

```json
{
  "leader": "node-1",
  "nodes": [
    {"id": "node-1", "raft_addr": "10.0.0.1:3410", "http_addr": "10.0.0.1:3310",
     "state": "Leader", "last_contact": "2026-04-23T10:00:00Z", "applied_index": 12345},
    {"id": "node-2", "raft_addr": "10.0.0.2:3410", "http_addr": "10.0.0.2:3310",
     "state": "Follower", "last_contact": "2026-04-23T10:00:00Z", "applied_index": 12345},
    {"id": "node-3", "raft_addr": "10.0.0.3:3410", "http_addr": "10.0.0.3:3310",
     "state": "Follower", "last_contact": "2026-04-23T09:59:58Z", "applied_index": 12340}
  ],
  "term": 4,
  "commit_index": 12345
}
```

Reachable from any node (no auth required for `status` in v1 — revisit if this leaks sensitive topology data).

## Snapshot management

```
amebo snapshot create --addr ...   # trigger an out-of-band snapshot
amebo snapshot list --addr ...     # list snapshots on this node
amebo snapshot restore --file ...  # restore from file (node must be stopped)
```

- `create` calls `raft.Snapshot()` on the local node.
- `list` returns snapshots from the local `FileSnapshotStore`.
- `restore` is an offline operation; requires `--yes` and overwrites local state.

## Backup & restore

Because we own the data dir, backup is simple:
- **Hot backup**: `GET /v1/cluster/snapshot` streams a fresh snapshot over HTTP (auth: admin). Operators can pipe to S3.
- **Cold backup**: stop the node, `tar czf` the `data/` dir.

Restore is always cold — stop the node, replace `data/`, start.

## Disaster recovery

**All nodes dead, but data dir intact on at least one:**
1. Start that node with `--recover-from-state`. This tells Raft to re-bootstrap a single-node cluster from the existing state.
2. Other fresh nodes join normally.

**All data dirs lost:**
- Restore from backup (see above). No alternative — there is no external source of truth in our architecture.

## Config-driven cluster definition (alternative startup mode)

For Kubernetes deployments where pods come and go, auto-bootstrap from a peer list in config:

```yaml
# amebo.yaml on all three nodes, identical
cluster:
  expected_peers:
    - node-1:10.0.0.1:3410
    - node-2:10.0.0.2:3410
    - node-3:10.0.0.3:3410
```

At startup, each node waits (up to `cluster_bootstrap_timeout`, default 2 min) until all peers are reachable, then performs a coordinated bootstrap: the node with the lowest node_id issues `BootstrapCluster` with all peers; others start as followers.

This avoids the `--bootstrap` vs `--join` split for static clusters. First-class supported mode for k8s (spec 020).

## Operator API (summary)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/v1/cluster/join` | Secret | Add a peer |
| POST | `/v1/cluster/leave` | Secret | Remove a peer |
| GET | `/v1/cluster/status` | None (v1) | Topology |
| POST | `/v1/cluster/snapshot` | Admin | Trigger snapshot |
| GET | `/v1/cluster/snapshot/stream` | Admin | Stream snapshot for backup |
| POST | `/v1/cluster/transfer-leadership` | Admin | Forcibly transfer leadership (for rolling restarts) |

## Acceptance criteria

- [ ] `amebo serve --bootstrap` on a clean data dir forms a single-node cluster and accepts writes.
- [ ] Two more nodes `--join` and the cluster becomes 3-node within 30 seconds.
- [ ] Killing the leader triggers election within 3× election timeout; writes resume via the new leader.
- [ ] `amebo leave --self` cleanly removes the node; cluster shrinks to 2; remaining nodes retain quorum.
- [ ] `amebo force-remove` of a dead node is accepted and the cluster continues.
- [ ] Config-driven bootstrap works with three pods in docker-compose.
- [ ] `GET /v1/cluster/status` returns accurate state from any node.
- [ ] Hot backup → restore round-trip preserves all data.

## Alternatives considered

- **Serf/memberlist for discovery**: adds a gossip layer. Unnecessary for v1; static peer lists or explicit joins are fine.
- **Automatic leave on SIGTERM**: dangerous (rolling restarts would shrink the cluster). Rejected.
- **DNS SRV records for peer discovery**: nice for k8s. Deferred to v1.1 — the config-driven path covers the same need.
