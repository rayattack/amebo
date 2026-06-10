# 013 — Webhook Delivery Client

## Summary

The outbound HTTP client that posts events to subscriber webhook URLs. One instance per worker process. Handles connection reuse, timeouts, signing, idempotency headers, and response interpretation.

## Interface

```go
package webhook

type Client interface {
    Deliver(ctx context.Context, job DeliveryJob) Result
    Close() error
}

type DeliveryJob struct {
    Gist           *pb.Gist
    Subscription   *pb.Subscription
    Event          *pb.Event
    SubscriberApp  *pb.Application   // the app receiving the webhook (source of secret)
    Attempt        int               // 1-indexed attempt number
}

type Result struct {
    GistID       string
    Success      bool
    HTTPStatus   int
    Err          error
    DurationMs   int64
    At           time.Time
}
```

## Underlying transport

One `http.Client` with a tuned transport, reused across all deliveries:

```go
transport := &http.Transport{
    Proxy:                  http.ProxyFromEnvironment,
    DialContext:            (&net.Dialer{Timeout: 5*time.Second, KeepAlive: 30*time.Second}).DialContext,
    ForceAttemptHTTP2:      true,
    MaxIdleConns:           1024,
    MaxIdleConnsPerHost:    32,
    MaxConnsPerHost:        128,
    IdleConnTimeout:        90 * time.Second,
    TLSHandshakeTimeout:    5 * time.Second,
    ExpectContinueTimeout:  1 * time.Second,
    ResponseHeaderTimeout:  10 * time.Second,
}
client := &http.Client{Transport: transport, Timeout: 10*time.Second}
```

**Why stdlib over fasthttp / resty:** pooling, HTTP/2, context propagation, and middleware-style round trippers are all we need. fasthttp is fast but incompatible with context cancellation and lacks HTTP/2. resty is a convenience layer we don't need.

**HTTP/2** auto-negotiated under TLS. Multiplexes many requests over one connection — matters when fanning out to a single subscriber with many events.

## Request construction

```go
body := map[string]any{
    "action":   event.Action,
    "payload":  rawMessage(event.Payload),
    "metadata": rawMessage(event.Metadata),   // omit key if nil
}
buf, _ := json.Marshal(body)

req, _ := http.NewRequestWithContext(ctx, "POST", sub.Handler, bytes.NewReader(buf))
req.Header.Set("Content-Type", "application/json")
req.Header.Set("User-Agent", "amebo/1.0")
req.Header.Set("X-Amebo-Event-Id", gist.Id)
req.Header.Set("X-Amebo-Event", event.Id)
req.Header.Set("X-Amebo-Action", event.Action)
req.Header.Set("X-Amebo-Delivery-Attempt", strconv.Itoa(attempt))
req.Header.Set("X-Amebo-Timestamp", time.Now().UTC().Format(time.RFC3339))
req.Header.Set("X-Amebo-Signature", sign(buf, subscriberApp.Secret))
```

**Signature:** `HMAC_SHA256(body_bytes, subscriber_app_secret)` → hex. Matches spec 009's outbound convention (inverse of the inbound scheme — subscribers verify with their own secret).

## Success / failure classification

| Outcome | HTTP | Classification |
|---|---|---|
| 2xx | 200–299 | success |
| 3xx with redirect | 301/302/307/308 | follow once (max 1 redirect to prevent loops); classified by final response |
| 4xx client | 400–499 except 408, 429 | **permanent failure** — retry is not useful |
| 408 Request Timeout | 408 | transient — retry |
| 429 Too Many Requests | 429 | transient — retry, respect `Retry-After` if present |
| 5xx | 500–599 | transient — retry |
| Connection error | - | transient |
| Timeout (read or connect) | - | transient — **but not treated as success** (see below) |
| TLS error | - | transient — may be permanent in practice; we retry with backoff anyway |

**Departure from Python behavior:** the Python client treats `ReadTimeout` as success on the assumption that subscribers are idempotent and the request probably completed. This is wrong — it masks real outages. We treat timeouts as failure but rely on the subscriber's idempotency (via `X-Amebo-Event-Id`) to make retries safe.

**Permanent failures (4xx non-retryable)** still consume a retry slot in v1 — simpler. v1.1 may mark them permanently failed and stop retrying.

## Retry-After handling

For 429 and 503 responses with `Retry-After` header:
- The returned `Result.Err` carries the delay as a typed error:
  ```go
  type RetryAfterError struct { Delay time.Duration }
  ```
- The reconciler (spec 012) checks for this and uses `max(backoff, retry_after)` as the `SleepUntil`.

## Timeouts

- **Overall deadline**: 10s per request (configurable `AMEBO_TIMEOUT`).
- **Connect**: 5s.
- **TLS handshake**: 5s.
- **Response headers**: 10s.
- **Body read**: 10s.

Ctx deadline from reconciler takes precedence — if the reconciler's cycle is cancelled, the request aborts.

## Response body

- Read up to 64 KB for logging. Truncate beyond that.
- Success path: discard body, close.
- Failure path: store first 512 bytes in `Gist.LastError` for operator visibility.

## Body size limit (outbound)

We don't limit outbound payload size beyond what was stored — payloads are already bounded at ingest (spec 004). A subscriber that can't accept large payloads responds with 413; we treat as permanent failure.

## Connection hygiene

- No custom cookie jar.
- No automatic authentication (subscribers verify via HMAC, no Basic/Bearer).
- Close idle connections on worker shutdown.

## Per-subscription tuning (future)

v1 uses one transport for all subscriptions. v1.1 may add per-subscription:
- Custom timeout.
- Custom concurrency cap.
- Circuit breaker (if a subscriber's error rate exceeds a threshold, open the circuit for N seconds).

## Testing hooks

The `Client` interface allows a `FakeClient` in tests:

```go
type FakeClient struct {
    fn func(DeliveryJob) Result
}
func (f *FakeClient) Deliver(ctx context.Context, job DeliveryJob) Result { return f.fn(job) }
```

Scenarios covered:
- All-success: verify reconciler marks gists completed.
- All-fail: verify retries increment, backoff applies, eventually exhausted.
- Mixed: verify per-gist outcomes in the batched commit.
- Timeout: verify `ctx.Deadline` respected.

## Observability

Metrics:
- `amebo_webhook_requests_total{status, subscription_app, action}`
- `amebo_webhook_request_duration_seconds{subscription_app, action}`
- `amebo_webhook_retries_applied_total{reason="5xx|429|timeout|connection"}`
- `amebo_webhook_permanent_failures_total{status}`

Log lines on failure include: subscription ID, handler URL (path only, host pseudonymized if configured), attempt number, status code (or error class), duration.

**Secret leakage avoidance:** never log request headers (contains signatures), never log response body, never log full URLs (may contain query-string secrets).

## Acceptance criteria

- [ ] Delivering to a mock server that returns 200 marks the gist completed.
- [ ] Delivering to a mock server that returns 500 increments retries and sets a future `sleep_until`.
- [ ] A subscriber returning 429 with `Retry-After: 30` causes the next attempt to wait ≥ 30s.
- [ ] Read timeout is classified as failure, not success (regression fix from Python).
- [ ] `X-Amebo-Signature` can be validated by a subscriber using the app's secret.
- [ ] `X-Amebo-Event-Id` is stable across retries of the same gist — allows subscriber-side idempotency.
- [ ] Concurrent deliveries cap is honored (inspect goroutine count under load).

## Alternatives considered

- **Use `github.com/imroc/req`**: convenient API but another dependency for small benefit.
- **Per-subscription custom TLS configs**: overkill for v1; operators who need mTLS to subscribers can put Amebo behind a mesh.
- **Follow multiple redirects**: dangerous (loops, open redirect abuse). Cap at one.
- **Keep Python's "timeout = success" behavior**: hides outages. Rejected with an explicit callout.
