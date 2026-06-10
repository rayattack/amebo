from datetime import datetime, timedelta
from http import HTTPStatus
from math import ceil
from sqlite3 import Connection

from heaven import Context, Request, Response
from httpx import AsyncClient, ReadTimeout, Timeout
from orjson import loads

from amebo.decorators.formatters import jsonify
from amebo.decorators.security import protected
from amebo.decorators.providers import contextualize, expects
from amebo.constants.literals import DB, MAX_PAGINATION, X_AMEBO_SIGNATURE
from amebo.utils.helpers import (
    get_pagination, datasigner, status_expr, truncate_error, redact_payload,
    backoff_seconds, DELIVERY_STATUSES,
)
from amebo.utils.structs import Steps
from amebo.models.gists import Ack
from amebo.controllers.redactions import fetch_redacted_paths


# status -> the raw (param-less) SQL predicate that selects it. Mirrors helpers.status_expr
# so the API filter and the dashboard cards mean the exact same thing as the daemon.
STATUS_PREDICATES = {
    'delivered': 'g.completed <> 0',
    'failed': 'g.completed = 0 AND (g.dead_at IS NOT NULL OR g.retries >= s.max_retries)',
    'retrying': 'g.completed = 0 AND g.dead_at IS NULL AND g.retries > 0 AND g.retries < s.max_retries',
    'pending': 'g.completed = 0 AND g.dead_at IS NULL AND g.retries = 0',
}

# windows for the dashboard / metrics, expressed as a lookback delta
WINDOWS = {
    'today': timedelta(hours=24),
    '7d': timedelta(days=7),
    '30d': timedelta(days=30),
}


class _Where(object):
    """Tiny cross-backend WHERE builder: `?` for sqlite, `$n` for postgres."""
    def __init__(self, engine: str):
        self.engine = engine
        self.parts = []
        self.values = []

    def add(self, template: str, value):
        """template uses {p} for the bound placeholder, e.g. 'g.rowid = {p}'."""
        self.values.append(value)
        p = '?' if self.engine == 'sqlite' else f'${len(self.values)}'
        self.parts.append(template.format(p=p))

    def raw(self, predicate: str):
        """A param-less predicate (e.g. a status condition)."""
        self.parts.append(f'({predicate})')

    def clause(self):
        return f"WHERE {' AND '.join(self.parts)}" if self.parts else ''


def _timeline_cutoff(value: str):
    """Translate a timeline/window keyword into an ISO cutoff string, or None."""
    delta = WINDOWS.get((value or '').lower())
    if value and value.lower() in ('month', 'week'):  # back-compat with old UI keywords
        delta = timedelta(days=31) if value.lower() == 'month' else timedelta(days=7)
    if not delta: return None
    return (datetime.now() - delta).isoformat()


def _build_filters(req: Request, engine: str, default_status: str = None):
    """Shared filter builder for the gists list, bulk replay and requeue."""
    where = _Where(engine)
    _gist = req.queries.get('gist') or req.queries.get('id')
    _action = req.queries.get('action')
    _publisher = req.queries.get('origin') or req.queries.get('publisher')
    _subscriber = req.queries.get('destination') or req.queries.get('subscriber')
    _event = req.queries.get('event')
    _subscription = req.queries.get('subscription')
    _status = (req.queries.get('status') or default_status or '').lower()
    _completed = req.queries.get('completed')
    _timeline = req.queries.get('timeline') or req.queries.get('window')

    # PG types these columns (rowid int, event/subscription uuid); URL params arrive as
    # text, so cast on PG. SQLite stores them as text/implicit-rowid — no cast.
    # rowid is int on both backends — coerce so asyncpg binds an int (it won't coerce
    # str). event/subscription are uuid on PG (asyncpg accepts str for uuid), text on
    # sqlite; cast on PG so the comparison types line up.
    sqlite = engine == 'sqlite'
    uc = '' if sqlite else '::uuid'
    if _gist is not None and _gist != '':
        try: where.add('g.rowid = {p}', int(_gist))
        except (TypeError, ValueError): pass
    if _action: where.add('e.action LIKE {p}', f'%{_action}%')
    if _publisher: where.add('x.application LIKE {p}', f'%{_publisher}%')
    if _subscriber: where.add('s.application LIKE {p}', f'%{_subscriber}%')
    if _event: where.add(f'g.event = {{p}}{uc}', _event)
    if _subscription: where.add(f'g.subscription = {{p}}{uc}', _subscription)

    if _status in STATUS_PREDICATES:
        where.raw(STATUS_PREDICATES[_status])
    elif _completed is not None and _completed != '':
        flag = {'true': '<> 0', '1': '<> 0', 'false': '= 0', '0': '= 0'}.get(_completed.lower())
        if flag: where.raw(f'g.completed {flag}')

    cutoff = _timeline_cutoff(_timeline)
    if cutoff: where.add('g.timestamped > {p}', cutoff)
    return where


GISTS_FROM = '''
    FROM {x}gists AS g
    JOIN {x}events e ON g.event = e.event
    JOIN {x}subscriptions s ON g.subscription = s.subscription
    JOIN {x}actions x ON e.action = x.action
'''


@jsonify
@expects(Ack)
@contextualize
async def acknowledge(req: Request, res: Response, ctx: Context):
    identifier = req.params.get('id')
    steps = Steps(req.app._.engine)
    executor = ctx.executor
    sqls = f'''
        UPDATE {executor.schema}gists SET acknowledged = {steps.next()} WHERE rowid = {steps.next()}
    '''
    try: await executor.fetch(0).execute(sqls, ctx.ack.acknowledged, identifier)
    except Exception: return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Gist not acknowledged'})
    return res.out(HTTPStatus.ACCEPTED, {'acknowledged': identifier, 'timestamped': datetime.now().isoformat()})


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    page, pagination = get_pagination(req)
    per_page = pagination if pagination < MAX_PAGINATION else MAX_PAGINATION
    executor = ctx.executor
    x = executor.schema
    where = _build_filters(req, executor.engine)
    clause = where.clause()
    frm = GISTS_FROM.format(x=x)

    sqls = f'''
        SELECT
            g.rowid AS id, g.event AS event, e.action AS action,
            x.application AS publisher, s.application AS subscriber,
            s.handler AS endpoint, s.max_retries AS max_retries,
            g.completed AS completed, g.retries AS retries,
            g.last_status_code AS last_status_code, g.last_error AS last_error,
            g.last_attempted_at AS last_attempted_at, g.sleep_until AS sleep_until,
            g.dead_at AS dead_at, g.timestamped AS timestamped, e.payload AS payload,
            {status_expr('g', 's')} AS status
        {frm}
        {clause}
        ORDER BY g.timestamped DESC, g.rowid DESC
        LIMIT {per_page} OFFSET {(page - 1) * per_page};
    '''
    try:
        rows = await executor.fetch(2).execute(sqls, *where.values)
        total_row = await executor.fetch(1).execute(f'SELECT COUNT(*) {frm} {clause};', *where.values)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    rows = rows or []
    total = total_row[0] if total_row else 0

    # batch-fetch redaction paths so payload previews respect privacy
    redactions_by_action = {}
    for action_name in set(r[2] for r in rows):
        redactions_by_action[action_name] = await fetch_redacted_paths(executor, action_name)

    def preview(action, payload):
        try: data = redact_payload(redactions_by_action.get(action, []), loads(payload))
        except Exception: data = None
        return data

    data = [{
        'id': str(id),
        'gist': str(id),  # back-compat: UI keyed on `gist`
        'event': str(event),
        'action': action,
        'publisher': publisher,
        'subscriber': subscriber,
        'endpoint': endpoint,
        'max_retries': max_retries,
        'completed': bool(completed),
        'retries': retries,
        'last_status_code': last_status_code,
        'last_error': last_error,
        'last_attempted_at': last_attempted_at,
        'sleep_until': sleep_until,
        'dead_at': dead_at,
        'timestamped': timestamped,
        'status': status,
        'payload': preview(action, payload),
    } for (id, event, action, publisher, subscriber, endpoint, max_retries, completed,
           retries, last_status_code, last_error, last_attempted_at, sleep_until,
           dead_at, timestamped, payload, status) in rows]

    res.status = HTTPStatus.OK
    res.body = {
        'data': data,
        'total': total,
        'page': page,
        'pagination': per_page,
        'pages': ceil(total / per_page) if per_page else 1,
    }


def _gist_uuid_col(executor):
    # SQLite gists has no `gist` uuid column — only PG does. Fall back to NULL so the
    # delivery uses the event uuid for the idempotency header.
    return 'g.gist' if not executor.engine.startswith('sqlite') else 'NULL'


async def _fetch_gist(executor, rowid):
    x = executor.schema
    p = '?' if executor.engine == 'sqlite' else '$1'
    sqls = f'''
        SELECT g.rowid, s.handler, e.payload, e.metadata, a.secret, g.retries, e.action, {_gist_uuid_col(executor)}, g.event, s.max_retries
        {GISTS_FROM.format(x=x)}
        JOIN {x}applications a ON s.application = a.application
        WHERE g.rowid = {p};
    '''
    try: rowid = int(rowid)
    except (TypeError, ValueError): pass
    return await executor.fetch(1).execute(sqls, rowid)


async def writeback_attempt(executor, rowid, ok: bool, code, error, at: str,
                            retries: int = 0, max_retries: int = None):
    """Record one delivery attempt's outcome onto a gist row (keyed on rowid).
    Shared by the aproko daemon and UI replay so both write results identically.

    On failure (P2): schedules the next attempt with EXPONENTIAL BACKOFF via
    sleep_until, and DEAD-LETTERS the gist (sets dead_at) once it exhausts max_retries
    so the terminal state is queryable without re-deriving it from max_retries."""
    x = executor.schema
    sqlite = executor.engine == 'sqlite'
    cast = '' if sqlite else '::text::timestamptz'
    def ph(n): return '?' if sqlite else f'${n}'

    if ok:
        # delivered: clear the failure markers
        sqls = (f'UPDATE {x}gists SET completed = 1, retries = retries + 1, '
                f'last_status_code = {ph(1)}, last_error = NULL, last_attempted_at = {ph(2)}{cast}, '
                f'dead_at = NULL WHERE rowid = {ph(3)};')
        args = (code, at, rowid)
    else:
        next_retries = (retries or 0) + 1
        dead = max_retries is not None and next_retries >= max_retries
        now = datetime.now()
        # dead gists are terminal — no point scheduling them; live ones back off
        next_sleep = now.isoformat() if dead else (now + timedelta(seconds=backoff_seconds(next_retries))).isoformat()
        dead_at = now.isoformat() if dead else None
        sqls = (f'UPDATE {x}gists SET retries = retries + 1, last_status_code = {ph(1)}, '
                f'last_error = {ph(2)}, last_attempted_at = {ph(3)}{cast}, '
                f'sleep_until = {ph(4)}{cast}, dead_at = {ph(5)}{cast} WHERE rowid = {ph(6)};')
        args = (code, error, at, next_sleep, dead_at, rowid)
    await executor.fetch(0).execute(sqls, *args)


async def _proxy_deliver(executor, gist):
    """Re-POST one gist inline and write the outcome back onto the row.
    Returns (ok, status_code, error). Preserves HMAC signing + amebo headers."""
    rowid, handler, payload, metadata, secret, retries, action, header_gist, event, max_retries = gist
    body = {'action': action, 'metadata': loads(metadata) if metadata else {}, 'payload': loads(payload)}
    headers = {
        'Content-Type': 'application/json',
        X_AMEBO_SIGNATURE: datasigner(body, secret),
        'x-amebo-event-id': str(header_gist or event),
        'x-amebo-delivery-attempt': str((retries or 0) + 1),
    }
    at = datetime.now().isoformat()
    ok, code, error = False, None, None
    client = None
    try:
        client = AsyncClient(timeout=Timeout(10.0, connect=5.0))
        result = await client.post(handler, json=body, headers=headers)
        code = result.status_code
        if 200 <= result.status_code < 300: ok = True
        else: error = truncate_error(result.text)
    except (ReadTimeout, Exception) as exc:
        error = truncate_error(f'{type(exc).__name__}: {exc}')
    finally:
        if client: await client.aclose()
    await writeback_attempt(executor, rowid, ok, code, error, at, retries=retries, max_retries=max_retries)
    return ok, code, error


@jsonify
@protected
@contextualize
async def replay(req: Request, res: Response, ctx: Context):
    """Stateful single replay: proxies inline AND writes the result onto the gist."""
    rowid = req.params.get('id')
    executor = ctx.executor
    try:
        gist = await _fetch_gist(executor, rowid)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    if not gist: return res.out(HTTPStatus.NOT_FOUND, {'error': 'Gist not found'})

    ok, code, error = await _proxy_deliver(executor, gist)
    status = HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY
    return res.out(status, {'gist': str(rowid), 'delivered': ok, 'status_code': code, 'error': error})


@jsonify
@protected
@contextualize
async def time_travel(req: Request, res: Response, ctx: Context):
    """Bulk replay DRY-RUN (GET /v1/regists): count gists matching the filter.
    Defaults to status=failed so 'replay all failed' is the natural call."""
    executor = ctx.executor
    where = _build_filters(req, executor.engine, default_status='failed')
    sqls = f'SELECT COUNT(*) {GISTS_FROM.format(x=executor.schema)} {where.clause()};'
    try: row = await executor.fetch(1).execute(sqls, *where.values)
    except Exception as exc: return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})
    return res.out(HTTPStatus.OK, {'count': row[0] if row else 0, 'dry_run': True})


@jsonify
@protected
@contextualize
async def bulk_replay(req: Request, res: Response, ctx: Context):
    """Bulk replay (POST /v1/regists): re-deliver all gists matching the filter,
    in CHRONOLOGICAL order (oldest -> newest) so snapshot handlers converge.
    Idempotent: replaying a delivered gist simply re-delivers it."""
    executor = ctx.executor
    x = executor.schema
    where = _build_filters(req, executor.engine, default_status='failed')
    sqls = f'''
        SELECT g.rowid, s.handler, e.payload, e.metadata, a.secret, g.retries, e.action, {_gist_uuid_col(executor)}, g.event, s.max_retries
        {GISTS_FROM.format(x=x)}
        JOIN {x}applications a ON s.application = a.application
        {where.clause()}
        ORDER BY e.timestamped ASC, g.rowid ASC;
    '''
    try: gists = await executor.fetch(2).execute(sqls, *where.values)
    except Exception as exc: return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    gists = gists or []
    succeeded, still_failing = 0, 0
    for gist in gists:  # sequential, preserves chronological ordering
        ok, _, _ = await _proxy_deliver(executor, gist)
        if ok: succeeded += 1
        else: still_failing += 1

    return res.out(HTTPStatus.OK, {
        'total': len(gists), 'succeeded': succeeded, 'still_failing': still_failing,
    })


@jsonify
@protected
@contextualize
async def requeue(req: Request, res: Response, ctx: Context):
    """Hand gists back to the daemon: reset sleep_until=now and clear the exhausted
    condition (retries=0, completed=0) so the normal retry path redelivers them."""
    executor = ctx.executor
    x = executor.schema
    where = _build_filters(req, executor.engine, default_status='failed')
    now = datetime.now().isoformat()
    cast = '::text::timestamptz' if executor.engine.startswith('post') else ''
    # gather matching rowids first (UPDATE...JOIN isn't portable across both backends)
    sqls = f'SELECT g.rowid {GISTS_FROM.format(x=x)} {where.clause()};'
    try: rows = await executor.fetch(2).execute(sqls, *where.values)
    except Exception as exc: return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    rows = rows or []
    for row in rows:
        p1 = '?' if executor.engine == 'sqlite' else '$1'
        p2 = '?' if executor.engine == 'sqlite' else '$2'
        upd = f'''UPDATE {x}gists SET sleep_until = {p1}{cast}, retries = 0, completed = 0,
            last_error = NULL, last_status_code = NULL, dead_at = NULL WHERE rowid = {p2};'''
        try: await executor.fetch(0).execute(upd, now, row[0])
        except Exception as exc: return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    # wake the daemon (PG only; no-op on sqlite)
    if executor.engine.startswith('post'):
        try: await executor.fetch(0).execute("SELECT pg_notify('aproko_wake', '')")
        except Exception: pass
    return res.out(HTTPStatus.OK, {'requeued': len(rows)})


@jsonify
@protected
@contextualize
async def backfill(req: Request, res: Response, ctx: Context):
    """Re-register a subscription against HISTORICAL events (late/fixed-subscriber
    backfill). (Re)creates gists for every past event of the subscription's action
    since an optional cutoff, then lets the daemon deliver them.
    Body: {"subscription": "<id>", "timeline"|"since": "<iso|today|week|month>", "dry_run": bool}."""
    executor = ctx.executor
    x = executor.schema
    try: body = loads(req.body) if req.body else {}
    except Exception: body = {}

    subscription = body.get('subscription')
    if not subscription:
        return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': 'subscription is required'})
    dry_run = bool(body.get('dry_run'))

    since = body.get('since') or body.get('timeline')
    cutoff = _timeline_cutoff(since) if since and not str(since)[:4].isdigit() else since

    # resolve the subscription's action
    p = '?' if executor.engine == 'sqlite' else '$1::uuid'
    try:
        srow = await executor.fetch(1).execute(
            f'SELECT action FROM {x}subscriptions WHERE subscription = {p};', subscription)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})
    if not srow: return res.out(HTTPStatus.NOT_FOUND, {'error': 'Subscription not found'})
    action = srow[0]

    where = _Where(executor.engine)
    where.add('e.action = {p}', action)
    if cutoff: where.add('e.timestamped > {p}', cutoff)
    count_sql = f'SELECT COUNT(*) FROM {x}events e {where.clause()};'
    try: crow = await executor.fetch(1).execute(count_sql, *where.values)
    except Exception as exc: return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})
    matched = crow[0] if crow else 0

    if dry_run:
        return res.out(HTTPStatus.OK, {'count': matched, 'action': action, 'dry_run': True})

    now = datetime.now().isoformat()
    # (re)create gists for each matching event; reset any existing ones to deliverable.
    # Placeholders are bound in APPEARANCE order so SQLite's positional `?` and PG's
    # numbered `$n` agree: SELECT (subscription, now) ... WHERE (action[, cutoff]).
    sqlite = executor.engine == 'sqlite'
    def ph(n): return '?' if sqlite else f'${n}'
    uc = '' if sqlite else '::uuid'           # gists.subscription is uuid on PG
    tc = '' if sqlite else '::text::timestamptz'  # gists.sleep_until is timestamptz on PG (bind str via text)
    where_sql = f'WHERE e.action = {ph(3)}'
    args = [subscription, now, action]
    if cutoff:
        where_sql += f' AND e.timestamped > {ph(4)}'
        args.append(cutoff)
    excluded = 'excluded.sleep_until' if sqlite else 'EXCLUDED.sleep_until'
    insert_sql = f'''
        INSERT INTO {x}gists (event, subscription, completed, retries, sleep_until, timestamped)
        SELECT e.event, {ph(1)}{uc}, 0, 0, {ph(2)}{tc}, e.timestamped
        FROM {x}events e {where_sql}
        ON CONFLICT (event, subscription) DO UPDATE
            SET completed = 0, retries = 0, sleep_until = {excluded},
                last_error = NULL, last_status_code = NULL, dead_at = NULL;
    '''
    try:
        await executor.fetch(0).execute(insert_sql, *args)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    if executor.engine.startswith('post'):
        try: await executor.fetch(0).execute("SELECT pg_notify('aproko_wake', '')")
        except Exception: pass
    return res.out(HTTPStatus.OK, {'backfilled': matched, 'action': action, 'subscription': subscription})
