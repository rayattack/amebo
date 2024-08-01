from datetime import datetime, timedelta
from uuid import UUID, uuid5, getnode

from jwt import decode, encode
from heaven import Request

from amebo.constants.literals import DEFAULT_PAGINATION


HS256 = 'HS256'


def get_pagination(req: Request):
    try: page = int(req.params.get('page'))
    except: page = 1
    else: page = 1 if page < 0 else page

    try: pagination = int(req.params.get('pagination'))
    except: pagination = DEFAULT_PAGINATION
    else: pagination = DEFAULT_PAGINATION if pagination < 0 else pagination
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
