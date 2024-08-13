from datetime import datetime, timezone
from http import HTTPStatus
from sqlite3 import Connection, Cursor

from heaven import Context, Request, Response

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.models.subscriptions import Subscriptions
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
@contextualize
async def tabulate(req: Request, res, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    qstrings = ['id', 'application', 'matchrule', 'action', 'endpoint', 'description', 'timeline']
    [
        _id, _application, _matchrule,
        _action, _handler, _description, _timeline] = [req.queries.get(q) for q in qstrings]

    steps = Steps(req.app._.engine)
    executor = ctx.executor
    sqls = f'''
        SELECT
            subscription, action, application, handler, description, timestamped
        FROM {executor.schema}subscriptions
            {steps.EQUALS('subscription', _id)}
            {steps.LIKE('application', _application)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('handler', _handler)}
            {steps.LIKE('description', _description)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = None
        return

    res.status = HTTPStatus.OK
    res.body = [{
        'subscription': subscription,
        'action': action,
        'application': application,
        'endpoint': handler,
        'description': description,
        'timestamped': timestamped
    } for subscription, action, application, handler, description, timestamped in rows]


@jsonify
@expects(Subscriptions)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    subscriptions: Subscriptions = ctx.subscriptions
    
    steps = Steps(req.app._.engine)
    executor = ctx.executor

    try:
        sqls = f'SELECT address FROM {executor.schema}applications WHERE application = {steps.next()} AND secret = {steps.next()}'
        rows = await executor.fetch(1).execute(sqls, *(subscriptions.application, subscriptions.secret))
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'Invalid data submmitted {exc}'})

    if not rows: return res.out(HTTPStatus.NOT_ACCEPTABLE, {'error': 'Subscription request rejected'})
    try:
        row = rows[0]
        host = row.strip('/')
    except: return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, 'Can not process the event with information provided')
    address = f'{host}{subscriptions.handler}'

    fields = ('application', 'action', 'max_retries', 'handler', 'timestamped',)
    values = (
        subscriptions.application,  # subscribing application
        subscriptions.action,
        subscriptions.max_retries,
        address,
        datetime.now(tz=timezone.utc).isoformat()
    )

    try:
        sqls = f'''INSERT INTO {executor.schema}subscriptions ({', '.join(fields)}) VALUES ({steps.reset.next(5)}) RETURNING rowid;'''
        subscriptionid = await executor.execute(sqls, *values)
    except Exception as exc: return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    res.status = HTTPStatus.CREATED
    subscriptions.subscription = subscriptionid[0]
    
    res.body = subscriptions.model_dump()
