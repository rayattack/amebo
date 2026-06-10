# 003 — Configuration

## Summary

Define all configuration keys, their types, defaults, validation rules, and precedence order. All config is centralized in one struct and one loader package (`internal/config`).

## Sources and precedence

Highest wins:

1. **CLI flags** (e.g. `--port 3310`)
2. **Environment variables** (e.g. `AMEBO_PORT=3310`)
3. **Config file** (default `./amebo.yaml`, overridable via `--config <path>`)
4. **Hard-coded defaults**

`viper` handles merging. The config file format is YAML (JSON also accepted — viper auto-detects). The Python `amebo.json` format is supported for migration (spec 021).

## Canonical config struct

```go
package config

type Config struct {
    // Server
    NodeID       string        // unique per node; default = hostname
    BindAddr     string        // HTTP bind; default "0.0.0.0:3310"
    AdvertiseAddr string       // address peers reach us on; default = BindAddr
    DataDir      string        // parent of badger/ and raft/; default "./data"

    // Raft
    RaftAddr      string       // raft transport; default "0.0.0.0:3410"
    RaftAdvertise string       // advertised raft address; default = RaftAddr
    Bootstrap     bool         // true on first node of a new cluster; default false
    JoinAddrs     []string     // peers to join on startup (HTTP addresses); empty for single-node

    // Auth
    Secret       string        // JWT signing key; REQUIRED, min 32 bytes
    AdminUser    string        // bootstrap admin username; default "admin"
    AdminPass    string        // bootstrap admin password; REQUIRED on first boot

    // Delivery
    Envelope     int           // aproko batch size; default 256
    Idles        time.Duration // idle poll interval when no wake signal; default 5s
    MaxRetries   int           // fallback max_retries if subscription omits; default 3
    Timeout      time.Duration // webhook request timeout; default 10s

    // Observability
    LogLevel     string        // debug|info|warn|error; default info
    LogFormat    string        // json|text; default json
    MetricsAddr  string        // Prometheus /metrics bind; default ":9310"

    // TLS (optional)
    TLSCert      string        // path to cert; empty = no TLS
    TLSKey       string        // path to key
}
```

## Environment variable mapping

All env vars use the `AMEBO_` prefix. The field name is uppercased and snake-cased (viper handles this):

| Field | Env var |
|---|---|
| NodeID | `AMEBO_NODE_ID` |
| BindAddr | `AMEBO_BIND_ADDR` |
| DataDir | `AMEBO_DATA_DIR` |
| RaftAddr | `AMEBO_RAFT_ADDR` |
| Bootstrap | `AMEBO_BOOTSTRAP` |
| JoinAddrs | `AMEBO_JOIN_ADDRS` (comma-separated) |
| Secret | `AMEBO_SECRET` |
| AdminUser | `AMEBO_USERNAME` |
| AdminPass | `AMEBO_PASSWORD` |
| Envelope | `AMEBO_ENVELOPE` |
| Idles | `AMEBO_IDLES` (Go duration: "5s", "1m") |
| MaxRetries | `AMEBO_MAX_RETRIES` |
| Timeout | `AMEBO_TIMEOUT` |
| LogLevel | `AMEBO_LOG_LEVEL` |
| LogFormat | `AMEBO_LOG_FORMAT` |
| MetricsAddr | `AMEBO_METRICS_ADDR` |

## Validation rules

Fail fast on startup with a clear error message:

- `Secret` is required, must be ≥ 32 bytes of entropy. Reject obviously weak values (`secret`, `changeme`, all-zeros, all-ones).
- `AdminPass` is required on **first boot only** — detected by absence of `data/.initialized` marker. Subsequent boots treat it as optional; if set, it updates the admin password.
- `DataDir` must be writable; create it if missing.
- `BindAddr` and `RaftAddr` must be valid `host:port`, must not collide.
- If `Bootstrap=true` and `JoinAddrs` is non-empty, reject — these are mutually exclusive.
- `Envelope` ≥ 1 and ≤ 10000.
- `MaxRetries` ≥ 0.
- `Idles` ≥ 100ms (guard against tight loops).
- `Timeout` ≥ 1s.

## Config file shape

```yaml
# amebo.yaml
node_id: node-1
bind_addr: 0.0.0.0:3310
raft_addr: 0.0.0.0:3410
advertise_addr: node-1.internal:3310
raft_advertise: node-1.internal:3410
data_dir: /var/lib/amebo
bootstrap: true
join_addrs: []

secret: ${AMEBO_SECRET}    # interpolation supported
admin_user: admin
admin_pass: ${AMEBO_PASSWORD}

envelope: 256
idles: 5s
max_retries: 3
timeout: 10s

log_level: info
log_format: json
metrics_addr: :9310
```

**Secret interpolation:** `${VAR}` in string values expands from the environment at load time. Missing vars cause load to fail (no silent empty strings).

## Reload semantics

- **Hot-reloadable**: `LogLevel`, `Envelope`, `Idles`, `MaxRetries`, `Timeout`. Watched via `fsnotify` on the config file; a SIGHUP also triggers a reload.
- **Immutable after startup**: `NodeID`, addresses, `DataDir`, `Secret`, `Bootstrap`, `JoinAddrs`, TLS paths. Changes require restart.
- Attempting to hot-reload an immutable key logs a warning and ignores the change.

## Admin credential handling

On first boot (no `data/.initialized` marker):
1. Hash `AdminPass` with bcrypt (cost 12).
2. Write an admin credential entry via Raft propose (so all nodes see it).
3. Create `data/.initialized`.

On subsequent boots:
- If `AdminPass` is set in config/env, update the stored hash (matches Python's "reset on startup" behavior for ops convenience).
- If not set, leave the stored hash untouched.

## CLI flags

See spec 018 for full command surface. For `amebo serve`, every config key is mapped to a flag with the same name in kebab-case:

```
--node-id           --bind-addr           --advertise-addr
--data-dir          --raft-addr           --raft-advertise
--bootstrap         --join-addrs          --secret
--admin-user        --admin-pass          --envelope
--idles             --max-retries         --timeout
--log-level         --log-format          --metrics-addr
--tls-cert          --tls-key             --config
```

## Precedence in code

```go
// internal/config/load.go
func Load(cmdFlags *pflag.FlagSet) (*Config, error) {
    v := viper.New()
    v.SetEnvPrefix("AMEBO")
    v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
    v.AutomaticEnv()
    v.SetConfigFile(cmdFlags.Lookup("config").Value.String())
    _ = v.ReadInConfig()  // not required to exist
    v.BindPFlags(cmdFlags)
    // ... build Config, validate, return
}
```

## Acceptance criteria

- [ ] `amebo serve --help` lists every flag in the table above with a one-line description.
- [ ] Starting with no env vars, no config file, no flags prints a single actionable error ("AMEBO_SECRET is required").
- [ ] Starting with `AMEBO_SECRET` set but no `AMEBO_PASSWORD` on first boot prints an actionable error.
- [ ] Starting with a config file whose values are all overridden by env vars reflects the env values at runtime (verified via a debug endpoint or log line).
- [ ] SIGHUP changes the log level without restart; a follow-up log confirms the new level.
- [ ] Attempting to SIGHUP a change to `Secret` logs a warning and keeps the old value.

## Alternatives considered

- **TOML over YAML**: less ambiguous for nested config, but YAML is what our users expect.
- **No file format, env-only**: simpler but painful for anything with >10 keys.
- **koanf instead of viper**: cleaner API but smaller community. Revisit if viper becomes a pain point.
