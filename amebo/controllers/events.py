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
    _id, _action,  _deduper, _payload, _timeline = [req.queries.get(p) for p in params]

    steps = Steps()
    sqls = f'''SELECT
            event, action, payload, deduper, timestamped, COUNT(*) AS results
        FROM events
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
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = []
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

    try:
        cursor = db.cursor()
        row = cursor.execute('''
            SELECT
                schemata, actions.application, app.passphrase
            FROM
                actions
            JOIN applications app ON app.application = actions.application
            WHERE
                action = ?
        ''', (event.action,)).fetchone()

        if not row:
            res.status = HTTPStatus.UNPROCESSABLE_ENTITY
            res.body = {'error': 'Action can not be used to process any events'}
            return

        schemata = loads(row[0])  # load the schemata from the db
        schemas = req.app.peek('schematas')  # get the compiled schematas
        if not schemas.get(event.action): schemas[event.action] = compile(loads(schemata))
        validation = schemas.get(event.action)
        validation(event.payload)

        table = 'events'
        fields = ['action', 'payload', 'deduper', 'timestamped',]
        values = [event.action, dumps(event.payload).decode(), event.deduper, event.timestamped]

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
        import pdb; pdb.set_trace()
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
        'payload': event.payload,
        'action': event.action,
        'deduper': event.deduper,
        'timestamped': event.timestamped
    }
