from http import HTTPStatus
from sqlite3 import Connection

from fastjsonschema import JsonSchemaException, compile
from heaven import Context, Request, Response
from orjson import dumps, loads

from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.models.events import Events
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
def tabulate(req: Request, res: Response, _: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)

    params = ['id', 'action', 'deduper', 'payload', 'timeline']
    _id, _action,  _deduper, _payload, _timeline = [req.params.get(p) for p in params]

    steps = Steps()
    sqls = f'''SELECT
            event, action, payload, deduper, timestamped, COUNT(*) AS results
        FROM events
            {steps.EQUALS(_id, 'event')}
            {steps.LIKE(_action, 'action')}
            {steps.EQUALS(_deduper, 'deduper')}
            {steps.LIKE(_payload, 'payload')}
            {get_timeline(_timeline, steps)}
        GROUP BY
            event, action, payload, deduper, timestamped
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()

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
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    event: Events = ctx.events

    table = 'events'
    fields = ('action', 'payload', 'deduper', 'timestamped',)

    try:
        cursor = db.cursor()
        row = cursor.execute('''
            SELECT
                schemata, producer, p.passphrase
            FROM
                actions
            WHERE
                action = ?
            JOIN producers p ON p.name = actions.producer
        ''', (event.action,)).fetchone()

        if not row:
            res.status = HTTPStatus.UNPROCESSABLE_ENTITY
            res.body = {'error': 'Action can not be used to process any events'}
            return

        schemata = loads(row[0])
        _schemas = req.app.peek('schematas')
        if not _schemas.get(event.action): _schemas[event.action] = compile(loads(schemata))
        validation = _schemas.get(event.action)
        validation(event.payload)
        values = (event.action,
            dumps(event.payload), event.deduper, event.timestamped)

        eventid = cursor.execute(f'''
            INSERT INTO
                {table} ({', '.join(fields)})
            VALUES(?, ?, ?, ?) RETURNING rowid;
        ''', values).fetchone()

        cursor.execute(f'''
            INSERT INTO
                gists(event, subscriber, completed, timestamped)
            SELECT
                {eventid[0]}, subscriber, 0, '{event.timestamped.isoformat()}'
            FROM subscribers WHERE action = ?
        ''', (event.action,));

        db.commit()
    except JsonSchemaException:
        return res.out(HTTPStatus.NOT_ACCEPTABLE, {'error': f'Event payload does not conform to {event.action} schema'})
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})
    finally:
        cursor.close()

    res.status = HTTPStatus.CREATED
    res.body = {
        'event': eventid[0],
        'action': event.action,
        'payload': event.payload,
        'deduper': event.deduper,
        'timestamped': event.timestamped
    }
