import hashlib, hmac, secrets, time

from os import environ

from bcrypt import checkpw, gensalt, hashpw
from orjson import dumps
from datetime import datetime, timedelta
from uuid import UUID, uuid5, getnode

from jwt import decode, encode
from heaven import Request

from amebo.constants.literals import DEFAULT_PAGINATION


HS256 = 'HS256'


def get_pagination(req: Request):
    try: page = int(req.queries.get('page'))
    except (TypeError, ValueError): page = 1
    else: page = 1 if page < 1 else page

    try: pagination = int(req.queries.get('pagination'))
    except (TypeError, ValueError): pagination = DEFAULT_PAGINATION
    else: pagination = DEFAULT_PAGINATION if pagination < 1 else pagination
    return page, pagination


def get_params(params: list, req: Request):
    return [req.params.get(p) for p in params]


def get_timeline(timeline, step_or_filter, column: str = None):
    if timeline:
        dateline = datetime.now()
        value = timeline.lower()
        if value == 'month':
            dateline = dateline - timedelta(days=31)
        elif value == 'week':
            dateline = dateline - timedelta(days=7)
        elif value == 'today':
            dateline = dateline - timedelta(hours=24)

        adjunction = 'AND' if step_or_filter.dirty else 'WHERE'
        return f"{adjunction} {column or 'timestamped'} > DATETIME('{dateline.isoformat()}')"
    return ''


MAX_ERROR_LENGTH = 2000

# Canonical delivery-status vocabulary. "failed" == exhausted / dead-lettered.
DELIVERY_STATUSES = ('pending', 'retrying', 'delivered', 'failed')

# Exponential backoff between delivery retries (P2): base * factor^(attempt-1), capped.
BACKOFF_BASE_SECONDS = 10
BACKOFF_FACTOR = 2
BACKOFF_CAP_SECONDS = 3600


def backoff_seconds(attempt: int, base: int = BACKOFF_BASE_SECONDS,
                    factor: int = BACKOFF_FACTOR, cap: int = BACKOFF_CAP_SECONDS):
    """Seconds to wait before the next attempt. `attempt` is the number of attempts
    made so far (>=1): attempt 1 -> base, 2 -> base*factor, ... capped at `cap`."""
    if attempt < 1: attempt = 1
    return min(cap, base * (factor ** (attempt - 1)))


def status_expr(g: str = 'g', s: str = 's'):
    """The single source of truth for a gist's delivery status, as a SQL CASE
    expression. Reused by the gists API, the dashboard metrics, and any filter so
    'failed/exhausted' means the exact same thing everywhere.

    Requires the query to join gists (alias `g`) to subscriptions (alias `s`) so
    `max_retries` is in scope.
        delivered -> handler accepted (completed)
        failed    -> dead-lettered (dead_at set) or out of retries, never accepted
        retrying  -> attempted at least once, retries remain
        pending   -> not yet attempted
    """
    return f'''CASE
        WHEN {g}.completed <> 0 THEN 'delivered'
        WHEN {g}.dead_at IS NOT NULL OR {g}.retries >= {s}.max_retries THEN 'failed'
        WHEN {g}.retries > 0 THEN 'retrying'
        ELSE 'pending'
    END'''


def truncate_error(value, limit: int = MAX_ERROR_LENGTH):
    """Clamp an error/response-body snippet so last_error never bloats a row."""
    if value is None: return None
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[:limit]


def tokenize(data, sk):
    return encode(data, sk, algorithm=HS256)


def untokenize(token, sk):
    return decode(token, sk, algorithms=[HS256])


def deterministic_uuid():
    null = UUID("00000000-0000-0000-0000-000000000000")
    return uuid5(null, name = str(getnode())).hex


def datasigner(payload: dict, secret_key: str):
    """Sign payload HMAC with secret key"""
    sb = secret_key.encode('utf-8')
    return hmac.new(sb, dumps(payload), hashlib.sha256).hexdigest()


def datachecker(payload, signature, secret_key):
    """Check if payload is signed with secret key"""
    return hmac.compare_digest(signature, datasigner(payload, secret_key))


# Default window (seconds) a timestamped request stays valid. Overridable via env.
DEFAULT_REPLAY_TOLERANCE = 300


def replay_tolerance():
    try: return int(environ.get('AMEBO_REPLAY_TOLERANCE') or DEFAULT_REPLAY_TOLERANCE)
    except (TypeError, ValueError): return DEFAULT_REPLAY_TOLERANCE


def timestamped_signer(payload: dict, secret_key: str, timestamp):
    """HMAC over '<timestamp>.' + canonical body bytes. Binding the timestamp
    into the signed content is what makes the signature non-replayable: an
    attacker can't reuse a captured signature with a fresh timestamp header."""
    sb = secret_key.encode('utf-8')
    signed = f'{timestamp}.'.encode('utf-8') + dumps(payload)
    return hmac.new(sb, signed, hashlib.sha256).hexdigest()


def verify_request_signature(payload, signature, secret_key, timestamp=None, tolerance=None):
    """Backward-compatible inbound HMAC verification with optional replay protection.

    Returns ``(ok, reason)``.

    - If ``timestamp`` (the ``x-amebo-timestamp`` header) is present, the signature
      must cover ``'<timestamp>.<body>'`` AND the timestamp must be within
      ``tolerance`` seconds of now — so a captured request can't be replayed once
      the window passes.
    - If ``timestamp`` is absent/empty, falls back to the legacy body-only scheme so
      existing clients keep working. Replay protection is therefore opt-in: clients
      gain it by starting to send a signed timestamp.
    """
    if not signature:
        return False, 'missing signature'

    if timestamp is not None and str(timestamp) != '':
        try: ts = int(timestamp)
        except (TypeError, ValueError): return False, 'invalid timestamp'
        tol = tolerance if tolerance is not None else replay_tolerance()
        if abs(int(time.time()) - ts) > tol:
            return False, 'stale or future timestamp'
        expected = timestamped_signer(payload, secret_key, ts)
        return hmac.compare_digest(signature, expected), None

    # legacy body-only signature (no replay protection)
    return hmac.compare_digest(signature, datasigner(payload, secret_key)), None


def generate_apikey():
    """Generate a plaintext API key and its bcrypt hash.
    Returns (plaintext_key, hashed_key)."""
    plaintext = f'amebo_{secrets.token_hex(32)}'
    hashed = hashpw(plaintext.encode(), gensalt()).decode()
    return plaintext, hashed


def verify_apikey(plaintext, hashed):
    """Verify a plaintext API key against its bcrypt hash."""
    return checkpw(plaintext.encode(), hashed.encode())


REDACTED = '**redacted**'

def redact_payload(field_paths: list, payload):
    """Redact fields using dot-notation paths from the redactions table.
    Supports nested paths (address.zip) and array paths (items[].serial)."""
    if not isinstance(payload, dict) or not field_paths:
        return payload

    from copy import deepcopy
    result = deepcopy(payload)

    for path in field_paths:
        _redact_path(result, path.split('.'))

    return result


def _redact_path(obj, segments):
    """Walk into obj following segments and redact the leaf."""
    if not segments:
        return

    head = segments[0]
    rest = segments[1:]

    if head.endswith('[]'):
        key = head[:-2]
        if key in obj and isinstance(obj[key], list):
            if not rest:
                obj[key] = REDACTED
            else:
                for item in obj[key]:
                    if isinstance(item, dict):
                        _redact_path(item, rest)
    elif not rest:
        if head in obj:
            obj[head] = REDACTED
    else:
        if head in obj and isinstance(obj[head], dict):
            _redact_path(obj[head], rest)
