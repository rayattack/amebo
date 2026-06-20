"""JSON-Schema compatibility checking between two versions of an action.

Confluent-style modes, kept deliberately small and isolated so the rest of amebo
stays simple:

  NONE      no checking; any new version is accepted (the escape hatch)
  BACKWARD  a new version can read data written for the previous one
            (consumers upgrade first). DEFAULT.
  FORWARD   the previous version can read data written for the new one
            (producers upgrade first).
  FULL      both BACKWARD and FORWARD hold.

The engine reasons about the common JSON-Schema object/array shape: `type`,
`properties`, `required`, `additionalProperties`, numeric/length bounds, `enum`,
`const`, and nested objects / array `items`. It is intentionally CONSERVATIVE:
anything it cannot prove safe (composition keywords, `$ref`, opaque restructures)
is reported as breaking under the strict modes. NONE bypasses it entirely. The
result is a (ok, reasons) pair so callers can surface exactly what would break.
"""
from orjson import OPT_SORT_KEYS, dumps


MODES = ('NONE', 'BACKWARD', 'FORWARD', 'FULL')

_MIN_KEYS = ('minimum', 'exclusiveMinimum', 'minLength', 'minItems', 'minProperties')
_MAX_KEYS = ('maximum', 'exclusiveMaximum', 'maxLength', 'maxItems', 'maxProperties')
_OPAQUE = ('allOf', 'anyOf', 'oneOf', 'not', '$ref')


def _key(value):
    return dumps(value, option=OPT_SORT_KEYS)


def _type_widens(old_type, new_type) -> bool:
    """True if `new_type` accepts at least everything `old_type` did."""
    o = {old_type} if isinstance(old_type, str) else set(old_type or [])
    n = {new_type} if isinstance(new_type, str) else set(new_type or [])
    if o <= n:
        return True
    # integer instances are valid numbers
    if 'integer' in o and 'number' in n and (o - {'integer'}) <= n:
        return True
    return False


def _backward(old, new, path: str, reasons: list):
    """Append a reason for every way an instance valid under `old` could be
    REJECTED by `new` (i.e. `new` cannot necessarily read `old`'s data)."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return reasons
    loc = path or '(root)'

    old_type, new_type = old.get('type'), new.get('type')
    if new_type is not None and old_type != new_type:
        if old_type is None:
            reasons.append(f'{loc}: adds a type constraint ({new_type!r}) the previous version lacked')
        elif not _type_widens(old_type, new_type):
            reasons.append(f'{loc}: type changed from {old_type!r} to {new_type!r}')

    old_required = set(old.get('required') or [])
    new_required = set(new.get('required') or [])
    for prop in sorted(new_required - old_required):
        reasons.append(f'{loc}.{prop}: newly required (older instances may omit it)')

    new_ap = new.get('additionalProperties', True)
    if old.get('additionalProperties', True) is not False and new_ap is False:
        reasons.append(f'{loc}: additionalProperties tightened to false')

    old_props = old.get('properties') or {}
    new_props = new.get('properties') or {}
    for prop, old_sub in old_props.items():
        if prop in new_props:
            _backward(old_sub, new_props[prop], f'{loc}.{prop}', reasons)
        elif new_ap is False:
            reasons.append(f'{loc}.{prop}: property removed while additionalProperties is false')

    _bounds(old, new, loc, reasons)
    _values(old, new, loc, reasons)

    if 'items' in old or 'items' in new:
        old_items, new_items = old.get('items'), new.get('items')
        if isinstance(old_items, dict) and isinstance(new_items, dict):
            _backward(old_items, new_items, f'{loc}[]', reasons)
        elif old_items != new_items:
            reasons.append(f'{loc}[]: array items schema changed in an unverifiable way')

    for keyword in _OPAQUE:
        if old.get(keyword) != new.get(keyword):
            reasons.append(f'{loc}: {keyword} changed; compatibility cannot be proven')

    return reasons


def _bounds(old, new, loc, reasons):
    for keyword in _MIN_KEYS:
        if keyword in new:
            try:
                if keyword not in old or new[keyword] > old[keyword]:
                    reasons.append(f'{loc}: {keyword} tightened')
            except TypeError:
                reasons.append(f'{loc}: {keyword} changed in an unverifiable way')
    for keyword in _MAX_KEYS:
        if keyword in new:
            try:
                if keyword not in old or new[keyword] < old[keyword]:
                    reasons.append(f'{loc}: {keyword} tightened')
            except TypeError:
                reasons.append(f'{loc}: {keyword} changed in an unverifiable way')
    if 'pattern' in new and new.get('pattern') != old.get('pattern'):
        reasons.append(f'{loc}: pattern added or changed')
    if 'multipleOf' in new and new.get('multipleOf') != old.get('multipleOf'):
        reasons.append(f'{loc}: multipleOf added or changed')


def _values(old, new, loc, reasons):
    if 'enum' in new:
        if 'enum' not in old:
            reasons.append(f'{loc}: enum restriction added')
        else:
            try:
                allowed = {_key(v) for v in new['enum']}
                if not {_key(v) for v in old['enum']} <= allowed:
                    reasons.append(f'{loc}: enum no longer permits previously valid values')
            except Exception:
                if old['enum'] != new['enum']:
                    reasons.append(f'{loc}: enum changed in an unverifiable way')
    if 'const' in new and new.get('const') != old.get('const'):
        reasons.append(f'{loc}: const added or changed')


def check(old: dict, new: dict, mode: str):
    """Return (ok, reasons). `reasons` is empty when ok is True."""
    mode = (mode or 'BACKWARD').upper()
    if mode == 'NONE':
        return True, []
    if mode == 'FORWARD':
        reasons = [f'(forward) {r}' for r in _backward(new, old, '', [])]
        return (not reasons), reasons
    if mode == 'FULL':
        reasons = [f'(backward) {r}' for r in _backward(old, new, '', [])]
        reasons += [f'(forward) {r}' for r in _backward(new, old, '', [])]
        return (not reasons), reasons
    # BACKWARD (and any unknown mode, conservatively)
    reasons = _backward(old, new, '', [])
    return (not reasons), reasons
