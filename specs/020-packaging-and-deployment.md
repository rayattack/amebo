# 020 — Packaging & Deployment

## Summary

How amebo is built, released, and deployed. Single static binary is the primary distribution unit. Docker, systemd, and Kubernetes recipes follow.

## Release artifacts

Produced by `goreleaser` on every tagged release:

- **Static binaries** for `linux/amd64`, `linux/arm64`, `darwin/amd64`, `darwin/arm64`, `windows/amd64`. Pure Go, `CGO_ENABLED=0`.
- **Tarballs** (`amebo_<version>_linux_amd64.tar.gz`) with binary + LICENSE + README.
- **Debian/RPM packages** for Linux architectures.
- **Docker images** pushed to Docker Hub and GHCR (multi-arch manifest).
- **Homebrew formula** (published to `rayattack/homebrew-amebo`).
- **Checksums and cosign signatures** for supply-chain verification.

Version injected via `-ldflags`:

```
-X main.version=<tag>
-X main.commit=<sha>
-X main.date=<iso8601>
```

## Docker

### Base image

`gcr.io/distroless/static-debian12:nonroot`. No shell, no package manager, no setuid. Smallest reasonable surface.

### Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VERSION=dev
ARG COMMIT=unknown
RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags "-s -w -X main.version=$VERSION -X main.commit=$COMMIT" \
    -o /out/amebo ./cmd/amebo

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/amebo /amebo
USER nonroot:nonroot
EXPOSE 3310 3410 9310
VOLUME ["/data"]
ENTRYPOINT ["/amebo"]
CMD ["serve", "--config", "/etc/amebo/amebo.yaml"]
```

### docker-compose.yml (three-node cluster)

```yaml
version: "3.9"
x-amebo-common: &amebo-common
  image: ghcr.io/rayattack/amebo:1.0
  restart: unless-stopped
  environment:
    AMEBO_SECRET: ${AMEBO_SECRET:?required}
    AMEBO_PASSWORD: ${AMEBO_PASSWORD:?required}
    AMEBO_LOG_FORMAT: json
  volumes:
    - ./amebo.yaml:/etc/amebo/amebo.yaml:ro

services:
  amebo-1:
    <<: *amebo-common
    hostname: amebo-1
    environment:
      AMEBO_NODE_ID: node-1
      AMEBO_BIND_ADDR: 0.0.0.0:3310
      AMEBO_ADVERTISE_ADDR: amebo-1:3310
      AMEBO_RAFT_ADDR: 0.0.0.0:3410
      AMEBO_RAFT_ADVERTISE: amebo-1:3410
      AMEBO_BOOTSTRAP: "true"    # only on first startup
    volumes:
      - amebo-1-data:/data
    ports:
      - "3311:3310"
      - "9311:9310"

  amebo-2:
    <<: *amebo-common
    hostname: amebo-2
    depends_on: [amebo-1]
    environment:
      AMEBO_NODE_ID: node-2
      AMEBO_RAFT_ADDR: 0.0.0.0:3410
      AMEBO_RAFT_ADVERTISE: amebo-2:3410
      AMEBO_JOIN_ADDRS: http://amebo-1:3310
    volumes:
      - amebo-2-data:/data
    ports:
      - "3312:3310"

  amebo-3:
    # ... mirror of amebo-2 with node-3 ids

  nginx:
    image: nginx:alpine
    ports: ["80:80"]
    volumes: ["./nginx.conf:/etc/nginx/nginx.conf:ro"]
    depends_on: [amebo-1, amebo-2, amebo-3]

volumes:
  amebo-1-data:
  amebo-2-data:
  amebo-3-data:
```

**Bootstrap note:** `AMEBO_BOOTSTRAP=true` on node-1 is only effective on its first start (guarded by `data/.initialized`). Leaving the var set is safe on re-runs.

## systemd

`/etc/systemd/system/amebo.service`:

```ini
[Unit]
Description=Amebo event broker
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=amebo
Group=amebo
ExecStart=/usr/local/bin/amebo serve --config /etc/amebo/amebo.yaml
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536
AmbientCapabilities=
CapabilityBoundingSet=
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/amebo
ReadOnlyPaths=/etc/amebo
PrivateDevices=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
EnvironmentFile=/etc/amebo/amebo.env

[Install]
WantedBy=multi-user.target
```

`amebo` emits systemd readiness notifications (`sd_notify`) via `github.com/coreos/go-systemd/v22/daemon` on `Ready` and `Stopping` events.

## Kubernetes

### StatefulSet

Three replicas, `volumeClaimTemplates` for per-pod state, headless Service for stable DNS:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: amebo
spec:
  serviceName: amebo-headless
  replicas: 3
  selector: { matchLabels: { app: amebo } }
  template:
    metadata:
      labels: { app: amebo }
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: amebo
          image: ghcr.io/rayattack/amebo:1.0
          args: [serve, --config, /etc/amebo/amebo.yaml]
          env:
            - name: AMEBO_NODE_ID
              valueFrom: { fieldRef: { fieldPath: metadata.name } }
            - name: AMEBO_ADVERTISE_ADDR
              valueFrom: { fieldRef: { fieldPath: metadata.name } }  # amebo-N.amebo-headless
            - name: AMEBO_SECRET
              valueFrom: { secretKeyRef: { name: amebo-secret, key: secret } }
            - name: AMEBO_PASSWORD
              valueFrom: { secretKeyRef: { name: amebo-secret, key: admin-password } }
          ports:
            - { name: http,    containerPort: 3310 }
            - { name: raft,    containerPort: 3410 }
            - { name: metrics, containerPort: 9310 }
          readinessProbe:
            httpGet: { path: /ready, port: http }
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /health, port: http }
            periodSeconds: 10
          volumeMounts:
            - { name: data,   mountPath: /data }
            - { name: config, mountPath: /etc/amebo, readOnly: true }
      volumes:
        - name: config
          configMap: { name: amebo-config }
  volumeClaimTemplates:
    - metadata: { name: data }
      spec:
        accessModes: [ReadWriteOnce]
        resources: { requests: { storage: 50Gi } }
        storageClassName: fast-ssd
```

### Config-driven bootstrap for k8s

Spec 007 introduced `cluster.expected_peers` for static clusters. The k8s manifest uses it:

```yaml
# amebo-config ConfigMap
cluster:
  expected_peers:
    - node-id: amebo-0
      raft_addr: amebo-0.amebo-headless:3410
    - node-id: amebo-1
      raft_addr: amebo-1.amebo-headless:3410
    - node-id: amebo-2
      raft_addr: amebo-2.amebo-headless:3410
  bootstrap_timeout: 2m
```

Each pod waits for all peers to be reachable, then the lowest-id pod issues `BootstrapCluster` with the full peer list.

### Scaling policy

- **Scaling up**: edit `replicas`; new pod joins via config. Requires updating `expected_peers` in the ConfigMap — avoid scaling up without explicit config change. A `amebo-operator` controller (v1.1) can automate.
- **Scaling down**: explicit `amebo cluster leave` before removing the pod. Kubernetes lifecycle hook calls it on preStop:
  ```yaml
  lifecycle:
    preStop:
      exec:
        command: ["/amebo", "cluster", "leave", "--self",
                  "--addr", "http://amebo-0.amebo-headless:3310",
                  "--secret-file", "/etc/amebo/secret"]
  ```

## Nginx reverse proxy example

`nginx.conf`:

```nginx
upstream amebo_cluster {
    zone upstream_amebo 64k;
    least_conn;
    server amebo-1:3310 max_fails=3 fail_timeout=10s;
    server amebo-2:3310 max_fails=3 fail_timeout=10s;
    server amebo-3:3310 max_fails=3 fail_timeout=10s;
}

server {
    listen 80;
    location / {
        proxy_pass http://amebo_cluster;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Retry on 421 — follow leader redirect
        proxy_next_upstream error timeout http_421;
        proxy_next_upstream_tries 3;
    }
    location /metrics { deny all; }   # metrics not public
}
```

## TLS

Two supported patterns:

1. **Terminate at reverse proxy** (recommended). Amebo runs plain HTTP behind nginx/Traefik/Cloudflare.
2. **Terminate at Amebo** with `AMEBO_TLS_CERT` / `AMEBO_TLS_KEY`. Same cert is reused for Raft mTLS.

ACME / Let's Encrypt automation is **not** built in. Use `caddy` or `cert-manager`.

## Observability integration

- Prometheus: scrape `:9310/metrics`.
- Grafana dashboards: `deploy/grafana/amebo-overview.json`, `amebo-delivery.json`, `amebo-raft.json`.
- Alert rules: `deploy/prometheus/alerts.yaml` (spec 017).

## Supply-chain security

- All releases signed via `cosign` (keyless, Fulcio).
- SLSA provenance attestations attached to GitHub releases.
- SBOM generated by goreleaser, published as `amebo_<version>_sbom.json`.
- `govulncheck` gates the release workflow.

## Version & upgrade policy

- Semantic versioning: `MAJOR.MINOR.PATCH`.
- Within a MAJOR, the Raft log format is forward-compatible: a new binary reads logs written by older binaries in the same MAJOR.
- Downgrades within a MAJOR: supported if the log doesn't use newer command types. In practice, one-step downgrades are supported for the previous MINOR.
- MAJOR upgrades require a documented migration (snapshot + restore).

Rolling upgrade:
1. Check `amebo cluster status` — all nodes healthy.
2. Drain + upgrade + restart one follower at a time; wait for `/ready`.
3. `amebo cluster transfer-leadership` to a freshly upgraded node.
4. Upgrade the old leader last.

Tested in `test/e2e/upgrade_test.go` with binaries from the previous release.

## Acceptance criteria

- [ ] `docker pull` a release image, run on an empty volume, serves `/health` within 10s.
- [ ] docker-compose 3-node cluster converges and survives killing one node.
- [ ] K8s StatefulSet with config-driven bootstrap converges without manual `join` commands.
- [ ] systemd service starts, accepts SIGTERM gracefully, uses `sd_notify` readiness.
- [ ] Release artifacts signed and verifiable with `cosign verify`.
- [ ] Rolling upgrade test from previous version passes.

## Alternatives considered

- **Alpine base image**: smaller but musl-libc inconsistencies with CGo; distroless is safer.
- **Build with CGo for sqlite**: breaks static binary story. Rejected.
- **Helm chart instead of raw manifests**: both valuable. Target a chart for v1.1.
- **Auto-scaling with HPA**: doesn't make sense for stateful Raft members. Omit.
