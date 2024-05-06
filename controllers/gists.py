from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError

from heaven import Context, Request, Response
from httpx import AsyncClient
from orjson import loads

from decorators.formatters import jsonify
from decorators.security import authenticated
from constants.literals import DB, MAX_PAGINATION
from utils.helpers import get_pagination, get_timeline
from utils.structs import Steps


@jsonify
@authenticated
def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['origin', 'destination', 'gist', 'event', 'completed', 'timeline']
    _origin, _destination, _gist, _event, _completed, _timeline = [req.params.get(p) for p in params]
    _completed = _completed or 'all'

    completed = {'all': '', 'true': 1, 'false': 0}.get(_completed.lower())

    steps = Steps()
    sqls = f'''
        SELECT
            g.rowid as gist, e.microservice as origin, a.event,
            case when
                g.completed <> 0
            then
                'True'
            else
                'False'
            end as
                completed,
            g.timestamped, a.payload, m.microservice as destination
        FROM gists AS g JOIN actions a ON
            g.action = a.action
        JOIN subscribers s ON
            s.subscriber = g.subscriber
        JOIN events e ON
            a.event = e.event
        JOIN microservices m ON
            s.microservice = m.microservice
        {steps.EQUALS(_gist, 'g.rowid')}
        {steps.LIKE(_origin, 'e.microservice')}
        {steps.EQUALS(completed, 'g.completed')}
        {steps.LIKE(_event, 'a.event')}
        {steps.LIKE(_destination, 'm.microservice')}
        {get_timeline(_timeline, steps, column='g.timestamped')}
        ORDER BY g.rowid 
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
        'gist': gist,
        'origin': origin,
        'event': event,
        'completed': completed,
        'timestamped': timestamped,
        'payload': loads(payload),
        'destination': destination
    } for gist, origin, event, completed, timestamped, payload, destination in rows]


@jsonify
async def replay(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    id = req.params.get('id')

    try:
        cursor = db.cursor()
        gist = cursor.execute(f'''
            SELECT
                m.location || s.endpoint AS endpoint, a.payload, m.passkey, g.rowid as gid
            FROM gists AS g JOIN actions a ON
                g.action = a.action
            JOIN subscribers s ON
                s.subscriber = g.subscriber
            JOIN events e ON
                a.event = e.event
            JOIN microservices m ON
                s.microservice = m.microservice
            WHERE g.rowid = ?;
        ''', (id,)).fetchone()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()
    
    if not gist:
        res.status = HTTPStatus.NOT_FOUND
        res.body = {}
        return

    try:
        sender = AsyncClient()

        endpoint, payload, passkey, gid = gist
        headers = {'Content-Type': 'application/json', 'X-Secret-Key': passkey}

        response = await sender.post(endpoint, json=loads(payload), headers=headers)
        if response.status_code not in [HTTPStatus.ACCEPTED, HTTPStatus.OK]:
            raise ConnectionRefusedError('Endpoint maybe offline, failed to handle gist')
    except ConnectionRefusedError as exc:
        res.status = HTTPStatus.SERVICE_UNAVAILABLE
        try: proxied = response.json()
        except: proxied = None
        res.body = {'gist': gid, 'proxied': proxied, 'error': f'{exc}'}
        return
    except Exception as exc:
        res.status = HTTPStatus.BAD_GATEWAY
        res.body = {'error': f'{exc}'}
        return
    finally:
        await sender.aclose()

    res.satus = HTTPStatus.ACCEPTED
    try: proxied = response.json()
    except: proxied = None
    res.body = {'gist': gid, 'proxied': proxied}
    return
