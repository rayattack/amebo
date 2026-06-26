import logging
from datetime import datetime, timedelta
from http import HTTPStatus
from sqlite3 import Connection, IntegrityError
from uuid import uuid4

from asyncpg import UniqueViolationError
from fastjsonschema import JsonSchemaException
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION, X_AMEBO_SIGNATURE, X_AMEBO_TIMESTAMP
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects, _compile_schema
from amebo.models.events import Events
from amebo.utils.helpers import get_pagination, get_timeline, verify_request_signature, redact_payload
from amebo.controllers.redactions import fetch_redacted_paths
from amebo.utils.structs import Steps
from amebo.utils.versioning import parse_action


logger = logging.getLogger('amebo.events')


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)

    params = ['id', 'action', 'deduper', 'payload', 'timeline']
    _id, _action,  _deduper, _payload, _timeline = [req.queries.get(p) for p in params]

    steps = Steps(req.app._.engine)
    executor = ctx.executor

    sqls = f'''SELECT
            e.event, e.action, e.payload, e.deduper, e.timestamped, COUNT(*) AS results
        FROM {executor.schema}events e
            {steps.EQUALS('e.event', _id)}
            {steps.LIKE('e.action', _action)}
            {steps.LIKE('e.payload', _payload)}
            {steps.EQUALS('e.deduper', _deduper)}
            {get_timeline(_timeline, steps, column='e.timestamped')}
        GROUP BY
            e.event, e.action, e.deduper, e.payload, e.timestamped
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, [])

    # batch-fetch private field paths for all actions in this page
    actions_seen = set(row[1] for row in rows)
    redactions_by_action = {}
    for action_name in actions_seen:
        redactions_by_action[action_name] = await fetch_redacted_paths(executor, action_name)

    res.status = HTTPStatus.OK
    res.body = [{
        'event': event,
        'action': action,
        'payload': redact_payload(redactions_by_action.get(action, []), loads(payload)),
        'deduper': deduper,
        'timestamped': timestamped,
        'family': parse_action(action)['family'],
        'version': parse_action(action)['version']
    } for event, action, payload, deduper, timestamped, results in rows]


@jsonify
@expects(Events)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    identifier = uuid4().hex
    db: Connection = req.app.peek(DB)
    event: Events = ctx.events

    steps = Steps(req.app._.engine)
    try:
        executor = ctx.executor
        sqls = f'''
            SELECT
                schemata, actions.application, app.secret, actions.status, actions.successor
            FROM
                {executor.schema}actions
            JOIN {executor.schema}applications app ON app.application = actions.application
            WHERE
                action = {steps.next()} AND app.active = 1
        '''
        row = await executor.fetch(1).execute(sqls, event.action)
        if not row:
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': 'Action can not be used to process any events'})

        schemata, application, app_secret, status, successor = row
        ok, _ = verify_request_signature(
            loads(req.body), req.headers.get(X_AMEBO_SIGNATURE), app_secret,
            timestamp=req.headers.get(X_AMEBO_TIMESTAMP))
        if not ok:
            return res.out(HTTPStatus.UNAUTHORIZED, 'Invalid signature')

        # retired actions accept no new events (history + in-flight gists are untouched);
        # deprecated ones still flow but the response nudges producers toward the successor.
        if status == 'retired':
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {
                'error': f'Action {event.action} is retired and no longer accepts events',
                'successor': successor,
            })

        # compile the json schema with LRU cache (bounded to 1024 entries)
        # AND validate event payload to ensure we are only sending valid contractual payload
        # to subscribed endpoints
        if isinstance(schemata, str): schema_json = schemata
        else: schema_json = dumps(schemata).decode()
        validation = _compile_schema(schema_json)
        validation(event.payload)

        table = f'{executor.schema}events'
        fields = ['event', 'action', 'payload', 'metadata', 'deduper', 'timestamped',]
        values = [
            identifier,
            event.action,
            dumps(event.payload).decode(),
            dumps(event.metadata).decode(),
            event.deduper,
            event.timestamped.isoformat()
        ]

        sqls = f'''INSERT INTO {table} ({', '.join(fields)}) VALUES ({steps.reset.next(6)}) RETURNING rowid;'''
        rowid = await executor.fetch(1).execute(sqls, *values)
        sleep_until = datetime.now()
        if event.sleep_until:
            sleep_until = datetime.now() + timedelta(seconds = event.sleep_until)

        # find all subscribers for this event and create a gist for each one
        sqls = f'''
            INSERT INTO
                {executor.schema}gists(event, subscription, completed, retries, sleep_until, timestamped)
            SELECT
                '{identifier}', subscription, 0, 0, '{sleep_until.isoformat()}', '{event.timestamped.isoformat()}'
            FROM {executor.schema}subscriptions WHERE action = {steps.reset.next()} AND active <> 0
        '''
        await executor.fetch(0).execute(sqls, event.action)

        # Wake aproko daemon instantly via PG LISTEN/NOTIFY (no-op for SQLite)
        if executor.engine.startswith('post'):
            await executor.fetch(0).execute("SELECT pg_notify('aproko_wake', '')")
    except JsonSchemaException as exc:
        return res.out(HTTPStatus.NOT_ACCEPTABLE, {'error': f'Event payload does not conform to {event.action} schema'})
    except ModuleNotFoundError as exc:
        logger.error('Schema engine unavailable: %s', exc)
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': 'Schema engine unavailable'})
    except (UniqueViolationError, IntegrityError):
        # Idempotent publish. The UNIQUE(deduper, payload) guard means this exact event was
        # already accepted: its row and gists already exist, and the INSERT above failed before
        # any new gist was created — so nothing is re-delivered. Re-publishing a deduped event is
        # expected (e.g. a producer retrying), so return the existing event with 200 OK rather
        # than 409/500. Publishers treat any non-2xx as a failed emit, so a duplicate must read
        # as success.
        sqls = f'''
            SELECT event, rowid FROM {executor.schema}events
            WHERE deduper = {steps.reset.next()} AND payload = {steps.next()}
        '''
        existing = await executor.fetch(1).execute(sqls, event.deduper, dumps(event.payload).decode())
        redacted_paths = await fetch_redacted_paths(executor, event.action)
        return res.out(HTTPStatus.OK, {
            'event': existing[0] if existing else identifier,
            'row_id': existing[1] if existing else None,
            'payload': redact_payload(redacted_paths, event.payload),
            'metadata': event.metadata,
            'action': event.action,
            'deduper': event.deduper,
            'timestamped': event.timestamped,
            'duplicate': True,
        })

    redacted_paths = await fetch_redacted_paths(executor, event.action)
    res.status = HTTPStatus.CREATED
    res.body = {
        'event': identifier,
        'row_id': rowid[0],
        'payload': redact_payload(redacted_paths, event.payload),
        'metadata': event.metadata,
        'action': event.action,
        'sleep_until': sleep_until,
        'deduper': event.deduper,
        'timestamped': event.timestamped
    }
    if status == 'deprecated':
        res.body['deprecated'] = True
        res.body['successor'] = successor
        res.headers = 'Warning', f'299 - "action {event.action} is deprecated; use {successor or "its successor"}"'
