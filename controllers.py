from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError

# installed libs
from httpx import AsyncClient
from jsonschema import draft7_format_checker, validate, ValidationError
from routerling import Context, HttpRequest, ResponseWriter
from orjson import dumps, loads

# src code
from constants import DB, MAX_PAGINATION, SECRET_KEY
from libx import Steps
from models import (
    Event,
    Credential,
    Action,
    Location,
    Microservice,
    Subscriber,
)
from middleware import expects, jsonify
from utils import get_pagination, get_timeline, tokenize



@expects(Credential)
@jsonify
def authenticate_microservice(req: HttpRequest, res: ResponseWriter, ctx):
    def unauthorized():
        res.status = HTTPStatus.UNAUTHORIZED
        res.body = {'error': 'could not authenticate microservice'}

    db: Connection = req.app.peek(DB)
    credential: Credential = ctx.credential

    table = 'credentials'
    username_field = 'username'
    password_field = 'password'
    if credential.scheme == 'token':
        table = 'microservices'
        username_field = 'microservice'
        password_field = 'passkey'

    try:
        cursor: Cursor = db.cursor()
        row = cursor.execute(f'''
            SELECT {username_field}, {password_field} FROM {table}
                WHERE {username_field} = ?
        ''', (credential.username,))
    except Exception as exc:
        return unauthorized()
    else: data = row.fetchone()
    finally: cursor.close()

    if not data: return unauthorized()

    username, password = data
    if password != credential.password: return unauthorized()
    # no feedback if provided if secret key mismatches i.e. continue indicates just that

    token = tokenize({
        'scheme': credential.scheme,
        'username': username,
    }, req.app.CONFIG(SECRET_KEY))
    res.headers = 'Set-Cookie', f'Authorization={token}; Path=/; HttpOnly; Max-Age={60*10}; SameSite=Strict; Secure'
    res.status = HTTPStatus.ACCEPTED
    res.body = None


@jsonify
def list_gists(req, res, ctx):
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
def list_actions(req, res, ctx):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'action', 'microservice', 'schemata', 'timeline']
    _id, _action, _microservice, _schemata, _timeline = [req.params.get(p) for p in params]

    steps = Steps()
    sqls = f'''
        SELECT
            rowid, action, microservice, schemata, timestamped
        FROM
            actions
            {steps.EQUALS(_id, 'rowid')}
            {steps.LIKE(_action, 'action')}
            {steps.LIKE(_microservice, 'microservice')}
            {steps.LIKE(_schemata, 'schemata')}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.NO_CONTENT
        res.body = None
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'action': action,
        'microservice': microservice,
        'schemata': loads(schemata),
        'timestamped': timestamped
    } for id, action, microservice, schemata, timestamped in rows]


@jsonify
def list_events(req: HttpRequest, res: ResponseWriter, ctx):
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
def list_microservices(req: HttpRequest, res: ResponseWriter, ctx):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['microservice', 'location', 'timeline']
    _microservice, _location, _timeline = [req.params.get(p) for p in params]
    steps = Steps()

    m = 'microservice'

    sqls = f'''SELECT rowid AS id, microservice, location, timestamped
        FROM microservices
            {steps.LIKE(_microservice, m)}
            {steps.LIKE(_location, 'location')}
            {get_timeline(_timeline, steps)}
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
    finally: cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'microservice': microservice,
        'location': location,
        'passkey': '...',
        'timestamped': timestamped
    } for id, microservice, location, timestamped in rows]


@jsonify
def list_subscribers(req: HttpRequest, res, ctx):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'microservice', 'matchrule', 'event', 'endpoint', 'description', 'timeline']
    [
        _id, _microservice, _matchrule,
        _event, _endpoint, _description, _timeline] = [req.params.get(p) for p in params]
    
    m = 'microservice'
    steps = Steps()
    sqls = f'''
        SELECT
            subscriber, event, microservice, endpoint, description, timestamped
        FROM subscribers
            {steps.EQUALS(_id, 'subscriber')}
            {steps.LIKE(_microservice, m)}
            {steps.LIKE(_event, 'event')}
            {steps.LIKE(_endpoint, 'endpoint')}
            {steps.LIKE(_description, 'description')}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = None
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'subscriber': subscriber,
        'event': event,
        'microservice': microservice,
        'endpoint': endpoint,
        'description': description,
        'timestamped': timestamped
    } for subscriber, event, microservice, endpoint, description, timestamped in rows]


@expects(Event)
@jsonify
def register_event(req: HttpRequest, res: ResponseWriter, ctx: Context):
    db: Connection = req.app.peek(DB)
    event: Event = ctx.event

    table = 'events'
    fields = ('action', 'payload', 'deduper', 'timestamped',)

    try:
        cursor = db.cursor()
        row = cursor.execute('''
            SELECT schemata FROM actions WHERE action = ?
        ''', (event.action,)).fetchone()

        if not row:
            res.status = HTTPStatus.BAD_REQUEST
            res.body = {'error': 'event can not be processed using this action'}
            return

        schemata = loads(row[0])
        validate(
            instance=event.payload,
            schema=schemata, format_checker=draft7_format_checker)
        values = (event.action,
            dumps(event.payload), event.deduper, event.timestamped)

        eventid = cursor.execute(f'''
            INSERT INTO
                {table} ({', '.join(fields)})
            VALUES(?, ?, ?, ?) RETURNING rowid;
        ''', values).fetchone();

        cursor.execute(f'''
            INSERT INTO
                gists(event, subscriber, completed, timestamped)
            SELECT
                {eventid[0]}, subscriber, 0, '{event.timestamped.isoformat()}'
            FROM subscribers WHERE action = ?
        ''', (event.action,));

        db.commit()
    except ValidationError:
        res.status = HTTPStatus.NOT_ACCEPTABLE
        res.body = {'error': 'payload does not conform to action schema'}
        return
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        res.body = {'error': f'{exc}'}
        return
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


@expects(Action)
@jsonify
def register_action(req: HttpRequest, res: ResponseWriter, ctx: Context):
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action

    table = 'actions'
    fields = ('action', 'microservice', 'schemata', 'timestamped',)
    values = (action.action, action.microservice, dumps(action.schemata), action.timestamped)

    try:
        cursor: Cursor = db.cursor()
        microservice = cursor.execute(f'''
            select * from microservices where rowid = ?
        ''', (action.microservice,)).fetchone()
        if not microservice:
            raise ValueError(f'microservice with id {action.microservice} not found')

        cursor.execute(f'''
            INSERT INTO {table}({', '.join(fields)}) VALUES(?, ?, ?, ?)
        ''', values)
        db.commit()
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.CREATED
    res.body = action.dict()


@expects(Microservice)
@jsonify
def register_microservice(req: HttpRequest, res: ResponseWriter, ctx: Context):
    db: Connection = req.app.peek(DB)
    microservice: Microservice = ctx.microservice
    try:
        cursor = db.cursor()
        values = (microservice.microservice, microservice.location, microservice.passkey, microservice.timestamped)
        cursor.execute('''
            INSERT into microservices(microservice, location, passkey, timestamped) VALUES (?, ?, ?, ?)
        ''', values)
        db.commit()
    except IntegrityError as exc:
        res.status = HTTPStatus.CONFLICT
        res.body = {'error': f'{exc}'}
        return
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()
    
    res.status = HTTPStatus.CREATED
    res.body = {
        'name': microservice.microservice,
        'location': microservice.location,
        'passkey': microservice.password,
        'timestamped': microservice.timestamped
    }


@expects(Location)
@jsonify
def update_microservice(req: HttpRequest, res: ResponseWriter, ctx: Context):
    db: Connection = req.app.peek(DB)
    microservice = req.params.get('id')
    location: Location = ctx.location

    try:
        cursor = db.cursor()
        cursor.execute(f'''
            UPDATE microservices SET location = ?
                WHERE microservice = ? AND passkey = ?
        ''', (location.location, microservice, location.passkey))
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'could not update microservice'}
        return
    finally:
        cursor.close()

    # no feedback if provided if secret key mismatches i.e. continue indicates just that
    res.status = HTTPStatus.ACCEPTED
    res.body = None


@expects(Subscriber)
@jsonify
def register_subscriber(req: HttpRequest, res: ResponseWriter, ctx: Context):
    db: Connection = req.app.peek(DB)
    subscriber: Action = ctx.subscriber

    table = 'subscribers'
    fields = ('event', 'microservice', 'endpoint', 'description', 'timestamped',)
    values = (subscriber.action, subscriber.microservice, subscriber.endpoint, subscriber.description, subscriber.timestamped)

    try:
        cursor: Cursor = db.cursor()
        subscriberid = cursor.execute(f'''
            INSERT INTO {table}({', '.join(fields)}) VALUES(?, ?, ?, ?, ?) RETURNING rowid;
        ''', values).fetchone()
        db.commit()
    except Exception as exc:
        res.status = HTTPStatus.UPGRADE_REQUIRED
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()

    res.status = HTTPStatus.CREATED
    subscriber.subscriber = subscriberid[0]
    res.body = subscriber.dict()


@jsonify
async def resend_gist(req: HttpRequest, res: ResponseWriter, ctx: Context):
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
