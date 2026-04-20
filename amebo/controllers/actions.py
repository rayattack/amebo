from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from asyncpg import UniqueViolationError
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION, X_AMEBO_SIGNATURE, X_AMEBO_REDACT, AMEBO_SECRET
from amebo.controllers.redactions import bulk_insert_redactions
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.decorators.providers import cacheschema
from amebo.models.actions import Action
from amebo.utils.helpers import get_pagination, get_timeline, datachecker, untokenize
from amebo.utils.structs import Steps


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'action', 'application', 'schemata', 'timeline']
    _id, _action, _application, _schemata, _timeline = [req.queries.get(p) for p in params]

    steps = Steps(req.app._.engine)
    executor = ctx.executor

    sqls = f'''
        SELECT
            rowid, action, application, schemata, timestamped
        FROM
            {executor.schema}actions
            {steps.EQUALS('rowid', _id)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('application', _application)}
            {steps.LIKE('schemata', _schemata)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'action': action,
        'application': application,
        'schemata': loads(schemata),
        'timestamped': timestamped
    } for id, action, application, schemata, timestamped in rows]


@jsonify
@expects(Action)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    request_signature = req.headers.get(X_AMEBO_SIGNATURE)
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action
    
    steps = Steps(req.app._.engine)
    executor = ctx.executor

    table = 'actions'
    fields = ('action', 'application', 'schemata', 'timestamped',)
    values = (action.action, action.application, dumps(action.schemata).decode(), action.timestamped.isoformat())

    try:
        sqls = f'''select application, secret from {executor.schema}applications where application = {steps.next()} AND active = 1'''
        _application = await executor.fetch(1).execute(sqls, action.application)
        if not _application:
            raise ValueError(f'Application {action.application} not found')
        application, secret = _application
        body = loads(req.body)
        if request_signature:
            if not datachecker(body, request_signature, secret): raise ValueError('Invalid signature')
        else:
            # allow admin JWT cookie as fallback (for UI-based action creation)
            admin_auth = req.cookies.get('Authentication')
            if admin_auth:
                try: untokenize(admin_auth, req.app.peek(AMEBO_SECRET))
                except Exception: raise ValueError('Invalid admin credentials')
            elif body.get('secret') != secret:
                raise ValueError('Invalid secret')
    except Exception as exc:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'{exc}'})

    try:
        sqls = f'''INSERT INTO {executor.schema}{table}({', '.join(fields)}) VALUES ({steps.reset.next(4)})'''
        await executor.fetch(0).execute(sqls, *values)
    except UniqueViolationError:
        return res.out(HTTPStatus.CONFLICT, {'error': f'Action {action.action} already exists'})
    except Exception as exc:
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    # handle x-amebo-redact header: space-separated field paths
    redact_header = req.headers.get(X_AMEBO_REDACT)
    if redact_header:
        field_paths = redact_header.split(' ')
        await bulk_insert_redactions(executor, action.action, field_paths)

    ctx.keep('schemata', action.schemata)
    res.status = HTTPStatus.CREATED
    res.body = action.model_dump()


@jsonify
@contextualize
async def remove(req: Request, res: Response, ctx: Context):
    sk = req.app.peek(AMEBO_SECRET)
    authentication = req.cookies.get('Authentication')
    if not authentication:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Admin authentication required'})
    try: metadata = untokenize(authentication, sk)
    except Exception:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid admin credentials'})
    if metadata.get('scheme') != 'password':
        return res.out(HTTPStatus.FORBIDDEN, {'error': 'Admin privileges required to delete actions'})

    action_name = req.params.get('id')
    executor = ctx.executor

    steps = Steps(req.app._.engine)
    sqls = f'SELECT action FROM {executor.schema}actions WHERE action = {steps.next()}'
    row = await executor.fetch(1).execute(sqls, action_name)
    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': f'Action {action_name} not found'})

    try:
        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'''DELETE FROM {executor.schema}gists
                WHERE event IN (SELECT event FROM {executor.schema}events WHERE action = {steps.next()})
                   OR subscription IN (SELECT subscription FROM {executor.schema}subscriptions WHERE action = {steps.next()})''',
            action_name, action_name,
        )

        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'DELETE FROM {executor.schema}events WHERE action = {steps.next()}',
            action_name,
        )

        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'DELETE FROM {executor.schema}subscriptions WHERE action = {steps.next()}',
            action_name,
        )

        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'DELETE FROM {executor.schema}redactions WHERE action = {steps.next()}',
            action_name,
        )

        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'DELETE FROM {executor.schema}actions WHERE action = {steps.next()}',
            action_name,
        )
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    res.status = HTTPStatus.ACCEPTED
    res.body = {'removed': action_name}

