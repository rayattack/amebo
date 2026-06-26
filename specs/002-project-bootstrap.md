# 002 — Project Bootstrap

## Summary

Establish the Go module, directory layout, tooling, and baseline dependencies. Output of this spec: a repository that compiles, runs, serves a `/health` endpoint, and has CI green.

## Module and repository

- **Module path**: `github.com/rayattack/amebo-go` (final name TBD — placeholder acceptable in early development).
- **Go version**: 1.23 or later. Pin via `go.mod` `go` directive and enforce in CI.
- **License**: MIT, matching the Python project.
- **Branch model**: `main` is always releasable; feature work on topic branches; squash-merge PRs.

## Directory layout

```
amebo-go/
├── cmd/
│   └── amebo/              # main package — CLI entry point only
│       └── main.go
├── internal/               # everything that is not a public library
│   ├── config/             # spec 003
│   ├── model/              # entities, keyspace encoding (spec 004)
│   ├── storage/            # Badger wrapper (spec 005)
│   ├── raft/               # consensus glue (spec 006)
│   ├── cluster/            # membership, bootstrap (spec 007)
│   ├── server/             # HTTP server, middleware (spec 008)
│   ├── auth/               # JWT, HMAC, API keys (spec 009)
│   ├── schema/             # JSON Schema registry (spec 010)
│   ├── ingest/             # event ingestion pipeline (spec 011)
│   ├── aproko/             # delivery worker (spec 012)
│   ├── webhook/            # outbound HTTP client (spec 013)
│   ├── redact/             # redaction engine (spec 014)
│   ├── api/                # admin JSON handlers (spec 015)
│   ├── ui/                 # web UI handlers + embedded templates (spec 016)
│   ├── obs/                # logging, metrics, tracing (spec 017)
│   └── cli/                # cobra commands (spec 018)
├── pkg/                    # exported helpers (only if genuinely reusable)
│   └── amebosig/           # HMAC signature helpers for client SDKs
├── web/                    # embedded UI assets (templates, CSS, JS)
├── testdata/               # golden files, fixtures
├── scripts/                # dev scripts (lint, bench, release)
├── deploy/
│   ├── docker/             # Dockerfile, compose
│   ├── systemd/
│   └── k8s/
├── specs/                  # these documents
├── go.mod
├── go.sum
├── Makefile
├── .golangci.yml
├── .goreleaser.yaml
└── README.md
```

**Rules:**
- Application code lives under `internal/` so consumers of this module can't depend on internals.
- `cmd/amebo/main.go` is thin — it wires `internal/cli` and exits. No business logic.
- One package per directory; package name matches the directory.
- No cyclic dependencies (enforced by `go vet`).
- Tests are colocated with the code they test (`foo_test.go` next to `foo.go`).

## Baseline dependencies

Pinned in `go.mod`. Replaceable but the starting set:

| Concern | Library | Rationale |
|---|---|---|
| HTTP router | `github.com/go-chi/chi/v5` | stdlib-compatible, middleware-friendly, low magic |
| Config | `github.com/spf13/viper` + `github.com/spf13/cobra` | env + file + flag merging, widely understood |
| Logging | `log/slog` (stdlib) | structured, no external dep |
| Metrics | `github.com/prometheus/client_golang` | de facto standard |
| Raft | `github.com/hashicorp/raft` | see spec 006 |
| Raft log store | `github.com/hashicorp/raft-boltdb/v2` initially; `github.com/rfyiamcool/raft-pebble` later | see spec 006 |
| KV store | `github.com/dgraph-io/badger/v4` | see spec 005 |
| JSON Schema | `github.com/santhosh-tekuri/jsonschema/v5` | fast, draft 7/2020-12 support, no CGo |
| HTTP client | `net/http` + `golang.org/x/net/http2` | stdlib is sufficient; see spec 013 |
| JWT | `github.com/golang-jwt/jwt/v5` | maintained fork, HS256 support |
| Password hashing | `golang.org/x/crypto/bcrypt` | matches Python's bcrypt for migration |
| UUID | `github.com/google/uuid` | v4 and v7 support |
| Testing | stdlib + `github.com/stretchr/testify` + `github.com/google/go-cmp` | |

**Anti-dependencies** (explicitly avoid):
- ORM libraries (gorm, ent) — raw Badger calls only.
- CGo-based libraries unless absolutely required — they break the static-binary story.
- Reflective config libraries beyond viper.

## Tooling

`Makefile` targets:

```
make build        # go build ./cmd/amebo
make test         # go test -race ./...
make bench        # go test -bench=. -benchmem ./...
make lint         # golangci-lint run
make fuzz         # go test -fuzz=. ./... (per-package)
make vet          # go vet ./...
make coverage     # go test -coverprofile, open HTML
make integration  # spec 019 integration suite
make docker       # docker buildx bake
make release      # goreleaser
```

## golangci-lint configuration

Enable at minimum: `govet`, `ineffassign`, `staticcheck`, `unused`, `gosec`, `gocritic`, `errcheck`, `errorlint`, `misspell`, `unconvert`, `bodyclose`, `contextcheck`, `noctx`. Treat all warnings as errors in CI.

## CI pipeline (GitHub Actions)

Jobs, all required before merge to `main`:

1. **lint**: `make lint`
2. **test**: `make test` with `-race` on Linux/macOS, Go 1.23 and tip
3. **integration**: `make integration` — spins up a 3-node cluster (spec 019)
4. **build**: matrix for linux/amd64, linux/arm64, darwin/amd64, darwin/arm64
5. **coverage**: upload to Codecov; fail if delta on a PR is worse than −1%
6. **vuln**: `govulncheck ./...`

## Bootstrap milestone

Acceptance criteria for this spec:

- [ ] `go build ./cmd/amebo` succeeds on a clean checkout with no manual setup.
- [ ] `./amebo serve` starts, logs a structured startup line, binds to `:3310`, serves `GET /health` → `200 {"status":"ok"}`.
- [ ] `./amebo version` prints a version derived from git (via `-ldflags -X`).
- [ ] `make test` passes with at least one unit test per package scaffold (even if it just asserts the package compiles).
- [ ] `make lint` is green.
- [ ] `golangci-lint`, `govulncheck`, and `gofumpt` agree the tree is clean.
- [ ] CI pipeline runs all jobs on PR and on push to main.

## Alternatives considered

- **gorilla/mux**: mature but in maintenance mode. chi is better maintained and lighter.
- **fiber / echo**: faster micro-benchmarks, but they wrap the stdlib server instead of composing with it, breaking middleware reuse. Rejected.
- **zap / zerolog**: faster than slog. `slog` is stdlib — preferred unless benchmarks show it's the bottleneck.
- **spf13/cobra + viper vs urfave/cli**: cobra's subcommand structure fits the CLI shape in spec 018 better.
