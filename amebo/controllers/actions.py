from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.decorators.providers import cacheschema
from amebo.models.actions import Action
from amebo.utils.helpers import get_pagination, get_timeline
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
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action
    
    steps = Steps(req.app._.engine)
    executor = ctx.executor

    table = 'actions'
    fields = ('action', 'application', 'schemata', 'timestamped',)
    values = (action.action, action.application, dumps(action.schemata).decode(), action.timestamped.isoformat())

    try:
        sqls = f'''select application, secret from {executor.schema}applications where application = {steps.next()}'''
        _application = await executor.fetch(1).execute(sqls, action.application)
        if not _application:
            raise ValueError(f'Application {action.application} not found')
        application, secret = _application
        if(secret != action.secret):
            return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'Incorrect {application} secret detected'})
    except Exception as exc: return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'{exc}'})
    
    try:
        sqls = f'''INSERT INTO {executor.schema}{table}({', '.join(fields)}) VALUES ({steps.reset.next(4)})'''
        print(sqls)
        await executor.fetch(0).execute(sqls, *values)
    except Exception as exc: return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    ctx.keep('schemata', action.schemata)
    res.status = HTTPStatus.CREATED
    res.body = action.model_dump()

