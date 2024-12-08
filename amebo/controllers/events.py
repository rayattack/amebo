from http import HTTPStatus
from sqlite3 import Connection

from fastjsonschema import JsonSchemaException, compile
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.models.events import Events
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


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
            event, action, payload, deduper, timestamped, COUNT(*) AS results
        FROM {executor.schema}events
            {steps.EQUALS('event', _id)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('payload', _payload)}
            {steps.EQUALS('deduper', _deduper)}
            {get_timeline(_timeline, steps)}
        GROUP BY
            event, action, deduper, payload, timestamped
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, [])

    res.status = HTTPStatus.OK
    res.body = [{
        'event': event,
        'action': action,
        'payload': loads(payload),
        'deduper': deduper,
        'timestamped': timestamped
    } for event, action, payload, deduper, timestamped, results in rows]


@jsonify
@expects(Events)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    event: Events = ctx.events

    steps = Steps(req.app._.engine)
    try:
        executor = ctx.executor
        sqls = f'''
            SELECT
                schemata, actions.application, app.secret
            FROM
                {executor.schema}actions
            JOIN {executor.schema}applications app ON app.application = actions.application
            WHERE
                action = {steps.next()}
        '''
        row = await executor.fetch(1).execute(sqls, event.action)
        if not row: return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': 'Action can not be used to process any events'})

        schemata = loads(row[0])  # load the schemata from the db
        schemas = req.app.peek('schematas')  # get the compiled schematas
        if not schemas.get(event.action): schemas[event.action] = compile(schemata)
        validation = schemas.get(event.action)
        validation(event.payload)

        table = f'{executor.schema}events'
        fields = ['action', 'payload', 'deduper', 'timestamped',]
        values = [event.action, dumps(event.payload).decode(), event.deduper, event.timestamped.isoformat()]

        sqls = f'''INSERT INTO {table} ({', '.join(fields)}) VALUES ({steps.reset.next(4)}) RETURNING rowid;'''
        eventid = await executor.fetch(1).execute(sqls, *values)
    
        sqls = f'''
            INSERT INTO
                {executor.schema}gists(event, subscription, completed, retries, timestamped)
            SELECT
                {eventid[0]}, subscription, 0, 0, '{event.timestamped.isoformat()}'
            FROM {executor.schema}subscriptions WHERE action = {steps.reset.next()}
        '''
        await executor.fetch(0).execute(sqls, event.action)
    except JsonSchemaException:
        return res.out(HTTPStatus.NOT_ACCEPTABLE, {'error': f'Event payload does not conform to {event.action} schema'})
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    res.status = HTTPStatus.CREATED
    res.body = {
        'event': eventid[0],
        'payload': event.payload,
        'action': event.action,
        'deduper': event.deduper,
        'timestamped': event.timestamped
    }

