"""In-memory fixed-window rate limiter for credential endpoints.

The token endpoint (``POST /v1/tokens`` / ``/v8/tokens``) verifies admin and
application credentials. Without throttling it is an open door for brute-force
and credential-stuffing. This module provides a small, dependency-free sliding
window keyed by client identity.

Scope/limits: counts are per-process and held in memory, so a multi-worker or
multi-instance deployment limits per worker rather than globally. That is a
deliberate first step — it raises the cost of brute force substantially without
adding a Redis dependency. For a hard global limit, back ``_buckets`` with Redis
(the project already depends on it). Tune via env:

    AMEBO_AUTH_RATELIMIT_MAX     attempts allowed per window (default 5)
    AMEBO_AUTH_RATELIMIT_WINDOW  window length in seconds   (default 60)
"""
import time
from os import environ


def _int_env(name: str, default: int) -> int:
    try:
        return int(environ.get(name) or default)
    except (TypeError, ValueError):
        return default


MAX_ATTEMPTS = _int_env('AMEBO_AUTH_RATELIMIT_MAX', 5)
WINDOW_SECONDS = _int_env('AMEBO_AUTH_RATELIMIT_WINDOW', 60)

# key -> list of monotonic timestamps of recent attempts
_buckets: "dict[str, list]" = {}


def client_key(req, scope: str = 'auth') -> str:
    """Best-effort client identifier for rate-limit bucketing.

    Prefers proxy-forwarded client IPs (Amebo is typically fronted by nginx),
    falling back to a shared bucket when no client hint is available. The
    forwarded headers are spoofable, so this is brute-force friction, not an
    authorization control.
    """
    headers = getattr(req, 'headers', None)
    ip = None
    if headers is not None:
        forwarded = headers.get('x-forwarded-for')
        if forwarded:
            ip = forwarded.split(',')[0].strip()
        if not ip:
            ip = headers.get('x-real-ip')
    if not ip:
        ip = getattr(req, 'ip', None) or 'global'
    return f'{scope}:{ip}'


def rate_limited(key: str, max_attempts: int = MAX_ATTEMPTS, window: int = WINDOW_SECONDS) -> bool:
    """Record an attempt for ``key`` and return True if it should be rejected.

    Once the window is saturated, further attempts are rejected without
    extending the window (so a flood can't keep pushing the unlock further out).
    """
    now = time.monotonic()
    bucket = [t for t in _buckets.get(key, ()) if now - t < window]
    if len(bucket) >= max_attempts:
        _buckets[key] = bucket
        return True
    bucket.append(now)
    _buckets[key] = bucket
    return False


def reset_attempts(key: str) -> None:
    """Clear a key's attempt history — called on a successful auth so legitimate
    users are never locked out by their own earlier typos."""
    _buckets.pop(key, None)
