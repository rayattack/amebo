import hashlib, hmac, secrets

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
