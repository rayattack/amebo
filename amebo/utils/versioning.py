"""Action versioning helpers.

Versions live IN the action name. The family is the name with its version token
removed, so `customers.v1.created` and `customers.v2.created` share the family
`customers.created`. An action with no version token is a family of one (it behaves
exactly like a pre-versioning amebo action) and is treated as the implicit earliest
version of its family.

Two schemes are recognised, detected purely from the name:
  - sequence: a `v<int>` segment            e.g. v1, v2, v10
  - date:     a `YYYY-MM-DD` segment,        e.g. 2026-06-19
              optionally followed by a bare  e.g. billing.2026-06-19.1.invoiced
              integer segment as a same-day  -> version "2026-06-19.1"
              sub-index

`sortkey` is a comparable tuple so "the next version must come after the latest"
is a single `>` comparison. The unversioned base sorts below every real version.
These functions are pure (no I/O, no framework) and unit-tested in isolation.
"""
import hashlib
import re
from datetime import date

from orjson import OPT_SORT_KEYS, dumps, loads


SEQ_RE = re.compile(r'^v(\d+)$')
DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
INT_RE = re.compile(r'^\d+$')


def parse_action(name: str) -> dict:
    """Decompose an action name into {family, version, scheme, sortkey}.

    A name with no recognised version token returns scheme None and the lowest
    possible sortkey, so it acts as the base/earliest version of its own family."""
    segments = name.split('.')

    for i, seg in enumerate(segments):
        seq = SEQ_RE.match(seg)
        if seq:
            family = '.'.join(segments[:i] + segments[i + 1:]) or name
            return {'family': family, 'version': seg, 'scheme': 'sequence',
                    'sortkey': (1, int(seq.group(1)), 0)}

        dat = DATE_RE.match(seg)
        if dat:
            try:
                ordinal = date(int(dat.group(1)), int(dat.group(2)), int(dat.group(3))).toordinal()
            except ValueError:
                continue  # 2026-13-40 is not a date, so not a version token

            # a bare integer immediately after the date is its same-day sub-index
            consume, sub = {i}, 0
            if i + 1 < len(segments) and INT_RE.match(segments[i + 1]):
                consume.add(i + 1)
                sub = int(segments[i + 1])

            family = '.'.join(s for j, s in enumerate(segments) if j not in consume) or name
            version = f'{seg}.{sub}' if len(consume) == 2 else seg
            return {'family': family, 'version': version, 'scheme': 'date',
                    'sortkey': (1, ordinal, sub)}

    return {'family': name, 'version': None, 'scheme': None, 'sortkey': (0, 0, 0)}


def schema_fingerprint(schema) -> str:
    """Stable SHA-256 of a schema, independent of key order or whitespace, so an
    identical re-registration is recognisable byte-for-byte."""
    if isinstance(schema, (bytes, bytearray, str)):
        schema = loads(schema)
    return hashlib.sha256(dumps(schema, option=OPT_SORT_KEYS)).hexdigest()


def next_version_hint(parsed: dict) -> str:
    """A human suggestion for the next version label, used only in error copy."""
    if parsed['scheme'] == 'sequence':
        current = int(SEQ_RE.match(parsed['version']).group(1))
        return f'v{current + 1}'
    if parsed['scheme'] == 'date':
        return 'a later date, e.g. a YYYY-MM-DD segment after the current one'
    return 'a version token, e.g. add a `.v2.` segment to the name'
