import logging
from datetime import datetime
from http import HTTPStatus
from sqlite3 import Connection

from asyncpg import UniqueViolationError
from heaven import Context, Request, Response
from orjson import loads

from amebo.constants.literals import DB, MAX_PAGINATION, X_AMEBO_SIGNATURE, X_AMEBO_TIMESTAMP
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.models.redactions import Redaction
from amebo.utils.helpers import get_pagination, get_timeline, verify_request_signature
from amebo.utils.structs import Steps
from amebo.utils.versioning import parse_action


logger = logging.getLogger('amebo.redactions')


async def fetch_redacted_paths(executor, action):
    """Fetch all redacted field paths for a given action."""
    steps = Steps(executor.engine)
    sqls = f'''SELECT field_path FROM {executor.schema}redactions WHERE action = {steps.next()}'''
    rows = await executor.fetch(2).execute(sqls, action)
    if not rows: return []
    return [row[0] for row in rows]


async def bulk_insert_redactions(executor, action, field_paths):
    """Insert multiple redaction field paths for an action."""
    steps = Steps(executor.engine)
    for path in field_paths:
        path = path.strip()
        if not path: continue
        try:
            sqls = f'''INSERT INTO {executor.schema}redactions(action, field_path, timestamped) VALUES ({steps.reset.next(3)})'''
            await executor.fetch(0).execute(sqls, action, path, datetime.now().isoformat())
        except UniqueViolationError:
            pass


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    _action = req.queries.get('action')
    _field_path = req.queries.get('field_path')
    _timeline = req.queries.get('timeline')

    steps = Steps(req.app._.engine)
    executor = ctx.executor

    sqls = f'''
        SELECT
            rowid, action, field_path, timestamped
        FROM
            {executor.schema}redactions
            {steps.EQUALS('action', _action)}
            {steps.LIKE('field_path', _field_path)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        logger.error('Could not list redactions: %s', exc)
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'Could not list redactions'}
        return

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'action': action,
        'field_path': field_path,
        'timestamped': timestamped,
        'family': parse_action(action)['family'],
        'version': parse_action(action)['version']
    } for id, action, field_path, timestamped in rows]


@jsonify
@expects(Redaction)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    request_signature = req.headers.get(X_AMEBO_SIGNATURE)
    db: Connection = req.app.peek(DB)
    redaction: Redaction = ctx.redaction

    steps = Steps(req.app._.engine)
    executor = ctx.executor

    try:
        sqls = f'''SELECT app.application, app.secret FROM {executor.schema}applications app
            JOIN {executor.schema}actions a ON a.application = app.application
            WHERE a.action = {steps.next()}'''
        row = await executor.fetch(1).execute(sqls, redaction.action)
        if not row:
            raise ValueError(f'Action {redaction.action} not found')
        application, secret = row
        body = loads(req.body)
        if request_signature:
            ok, _ = verify_request_signature(body, request_signature, secret,
                                             timestamp=req.headers.get(X_AMEBO_TIMESTAMP))
            if not ok: raise ValueError('Invalid signature')
        else:
            if body.get('secret') != secret: raise ValueError('Invalid secret')
    except ValueError as exc:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': str(exc)})
    except Exception as exc:
        logger.error('Redaction insert authorization failed: %s', exc)
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Could not authorize request'})

    fields = ('action', 'field_path', 'timestamped',)
    values = (redaction.action, redaction.field_path, redaction.timestamped.isoformat())

    try:
        sqls = f'''INSERT INTO {executor.schema}redactions({', '.join(fields)}) VALUES ({steps.reset.next(3)})'''
        await executor.fetch(0).execute(sqls, *values)
    except UniqueViolationError:
        return res.out(HTTPStatus.CONFLICT, {'error': f'{redaction.field_path} is already redacted for {redaction.action}'})
    except Exception as exc:
        logger.error('Could not create redaction: %s', exc)
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': 'Could not create redaction'})

    res.status = HTTPStatus.CREATED
    res.body = redaction.model_dump()


@jsonify
@contextualize
async def remove(req: Request, res: Response, ctx: Context):
    identifier = req.params.get('id')
    steps = Steps(req.app._.engine)
    executor = ctx.executor

    try:
        sqls = f'''DELETE FROM {executor.schema}redactions WHERE rowid = {steps.next()}'''
        await executor.fetch(0).execute(sqls, identifier)
    except Exception as exc:
        logger.error('Could not remove redaction: %s', exc)
        return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Could not remove redaction'})

    res.status = HTTPStatus.ACCEPTED
    res.body = {'removed': identifier}
