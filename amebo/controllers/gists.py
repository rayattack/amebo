from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError

from heaven import Context, Request, Response
from httpx import AsyncClient
from orjson import loads

from amebo.decorators.formatters import jsonify
from amebo.decorators.security import protected
from amebo.decorators.providers import contextualize
from amebo.constants.literals import DB, MAX_PAGINATION
from amebo.utils.helpers import get_pagination, get_timeline
from amebo.utils.structs import Steps


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['origin', 'destination', 'gist', 'event', 'completed', 'timeline']
    _origin, _destination, _gist, _event, _completed, _timeline = [req.queries.get(p) for p in params]
    _completed = _completed or 'all'

    completed = {'all': '', 'true': 1, 'false': 0}.get(_completed.lower())

    steps = Steps(req.app._.engine)
    executor = ctx.executor
    sqls = f'''
        SELECT
            g.rowid as gist,
            e.action as action,
            case when
                g.completed <> 0
            then
                'True'
            else
                'False'
            end as
                completed,
            x.application as publisher,
            s.application as subscriber,
            g.timestamped
        FROM {executor.schema}gists AS g JOIN {executor.schema}events e ON
            g.event = e.event
        JOIN {executor.schema}subscriptions s ON
            g.subscription = s.subscription
        JOIN {executor.schema}actions x ON
            s.action = x.action
        {steps.EQUALS('g.rowid', _gist)}
        {steps.LIKE('e.producer', _origin)}
        {steps.EQUALS('g.completed', completed)}
        {steps.LIKE('a.event', _event)}
        {steps.LIKE('p.name', _destination)}
        {get_timeline(_timeline, steps, column='g.timestamped')}
        ORDER BY g.rowid
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        print('exc is: ', exc)
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return

    res.status = HTTPStatus.OK
    res.body = [{
        'gist': gist,
        'action': action,
        'completed': completed,
        'publisher': publisher,
        'subscriber': subscriber,
        'timestamped': timestamped
    } for gist, action, completed, publisher, subscriber, timestamped in rows]


@jsonify
@contextualize
async def replay(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    id = req.params.get('id')
    
    steps = Steps(req.app._.engine)
    executor = ctx.executor

    try:
        gist = await executor.fetch(1).execute(f'''
            SELECT
                s.handler AS endpoint, e.payload, a.secret, g.rowid as gid
            FROM gists AS g JOIN subscriptions s ON
                g.subscription = s.subscription
            JOIN events e ON
                g.event = e.event
            JOIN applications a ON
                s.application = a.application
            WHERE g.rowid = {steps.next()};
        ''', (id,))
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return

    if not gist: return res.out(HTTPStatus.NOT_FOUND, {'error': 'Gist not found'})

    try:
        sender = AsyncClient()

        endpoint, payload, secret, gid = gist
        headers = {'content-type': 'application/json', 'x-pass-phrase': secret}

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
