from datetime import datetime, timezone
from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError
from uuid import uuid4

from asyncpg import ForeignKeyViolationError, UniqueViolationError
from heaven import Context, Request, Response
from orjson import loads

from amebo.constants.literals import DB, MAX_PAGINATION, X_AMEBO_SIGNATURE, AMEBO_SECRET
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.models.subscriptions import Subscriptions, SubscriptionMigration
from amebo.utils.helpers import get_pagination, get_timeline, datachecker, untokenize
from amebo.utils.structs import Steps


@jsonify
@contextualize
async def tabulate(req: Request, res, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    qstrings = ['id', 'application', 'matchrule', 'action', 'endpoint', 'description', 'active', 'timeline']
    [
        _id, _application, _matchrule,
        _action, _handler, _description, _active, _timeline] = [req.queries.get(q) for q in qstrings]

    steps = Steps(req.app._.engine)
    executor = ctx.executor
    sqls = f'''
        SELECT
            subscription, action, application, max_retries, handler, description, active, timestamped
        FROM {executor.schema}subscriptions
            {steps.EQUALS('subscription', _id)}
            {steps.LIKE('application', _application)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('handler', _handler)}
            {steps.LIKE('description', _description)}
            {steps.EQUALS('active', _active)}
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
        'max_retries': max_retries,
        'endpoint': handler,
        'description': description,
        'active': bool(active),
        'timestamped': timestamped
    } for subscription, action, application, max_retries, handler, description, active, timestamped in rows]


@jsonify
@expects(Subscriptions)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    subscriptions: Subscriptions = ctx.subscriptions
    request_signature = req.headers.get(X_AMEBO_SIGNATURE)

    steps = Steps(req.app._.engine)
    executor = ctx.executor
    try:
        sqls = f'SELECT address, secret FROM {executor.schema}applications WHERE application = {steps.next()} AND active = 1'
        rows = await executor.fetch(1).execute(sqls, subscriptions.application)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'Invalid data submmitted {exc}'})
    if not rows: return res.out(HTTPStatus.EXPECTATION_FAILED, {'error': 'Subscription request rejected'})

    try:
        address, secret = rows
        host = address.strip('/')
    except Exception: return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, 'Can not process the event with information provided')

    if not datachecker(loads(req.body), request_signature, secret):
        return res.out(HTTPStatus.UNAUTHORIZED, 'Invalid signature')

    address = f'{host}{subscriptions.handler}'
    identifier = uuid4().hex
    now = datetime.now(tz=timezone.utc).isoformat()

    steps = Steps(req.app._.engine)
    fields = ('subscription', 'application', 'action', 'max_retries', 'handler', 'active', 'timestamped',)
    values = (identifier, subscriptions.application, subscriptions.action, subscriptions.max_retries, address, 1, now)
    try:
        sqls = f'''INSERT INTO {executor.schema}subscriptions ({', '.join(fields)}) VALUES ({steps.reset.next(7)});'''
        await executor.fetch(0).execute(sqls, *values)
    except (UniqueViolationError, IntegrityError):
        # idempotent re-subscribe: the (application, action, handler) tuple already exists.
        # Reactivate it (covering a prior soft-unsubscribe) instead of rejecting with 409.
        steps = Steps(req.app._.engine)
        upd = (f'UPDATE {executor.schema}subscriptions SET active = 1, max_retries = {steps.next()} '
               f'WHERE application = {steps.next()} AND action = {steps.next()} AND handler = {steps.next()}')
        await executor.fetch(0).execute(upd, subscriptions.max_retries, subscriptions.application, subscriptions.action, address)
        steps = Steps(req.app._.engine)
        sel = (f'SELECT subscription FROM {executor.schema}subscriptions '
               f'WHERE application = {steps.next()} AND action = {steps.next()} AND handler = {steps.next()}')
        existing = await executor.fetch(1).execute(sel, subscriptions.application, subscriptions.action, address)
        res.status = HTTPStatus.OK
        res.body = subscriptions.model_dump(exclude={'subscription'})
        res.body['subscription'] = str(existing[0]) if existing else identifier
        res.body['reactivated'] = True
        return
    except ForeignKeyViolationError as exc:
        return res.out(HTTPStatus.FORBIDDEN, {'error': f'Action {subscriptions.action} does not exist'})
    except Exception as exc:
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    res.status = HTTPStatus.CREATED
    res.body = subscriptions.model_dump(exclude={'subscription'})
    res.body['subscription'] = identifier


@jsonify
@contextualize
async def remove(req: Request, res: Response, ctx: Context):
    """Soft-unsubscribe: deactivate the subscription so it stops fanning out and
    delivering, while keeping its delivery history. Reversible by re-subscribing.
    Already-queued gists are left to drain. Subscriber-signed or admin."""
    subscription_id = req.params.get('id')
    executor = ctx.executor
    sqlite = executor.engine == 'sqlite'
    uc = '' if sqlite else '::uuid'

    steps = Steps(req.app._.engine)
    sqls = f'''
        SELECT s.application, a.secret
        FROM {executor.schema}subscriptions s
        JOIN {executor.schema}applications a ON a.application = s.application
        WHERE s.subscription = {steps.next()}{uc}
    '''
    try: row = await executor.fetch(1).execute(sqls, subscription_id)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})
    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': 'Subscription not found'})
    application, secret = row

    request_signature = req.headers.get(X_AMEBO_SIGNATURE)
    try:
        if request_signature:
            body = loads(req.body) if req.body else {}
            if not datachecker(body, request_signature, secret): raise ValueError('Invalid signature')
        else:
            admin_auth = req.cookies.get('Authentication')
            if not admin_auth: raise ValueError('Authentication required')
            try: untokenize(admin_auth, req.app.peek(AMEBO_SECRET))
            except Exception: raise ValueError('Invalid admin credentials')
    except Exception as exc:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'{exc}'})

    steps = Steps(req.app._.engine)
    upd = f'UPDATE {executor.schema}subscriptions SET active = 0 WHERE subscription = {steps.next()}{uc}'
    try: await executor.fetch(0).execute(upd, subscription_id)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    return res.out(HTTPStatus.ACCEPTED, {'unsubscribed': subscription_id, 'active': False})


@jsonify
@expects(SubscriptionMigration)
@contextualize
async def migrate(req: Request, res: Response, ctx: Context):
    """Clone active subscriptions from one action onto another (typically v1 -> v2).
    `to_action` defaults to from_action's successor. Optionally deactivates the source
    subscriptions so consumers move over cleanly. Admin only."""
    migration: SubscriptionMigration = ctx.subscriptionmigration

    sk = req.app.peek(AMEBO_SECRET)
    authentication = req.cookies.get('Authentication')
    if not authentication:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Admin authentication required'})
    try: untokenize(authentication, sk)
    except Exception:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid admin credentials'})

    executor = ctx.executor
    from_action = migration.from_action
    to_action = migration.to_action

    if not to_action:
        steps = Steps(req.app._.engine)
        row = await executor.fetch(1).execute(
            f'SELECT successor FROM {executor.schema}actions WHERE action = {steps.next()}', from_action)
        if not row:
            return res.out(HTTPStatus.NOT_FOUND, {'error': f'Action {from_action} not found'})
        to_action = row[0]
        if not to_action:
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY,
                           {'error': f'{from_action} has no successor; pass to_action explicitly'})

    steps = Steps(req.app._.engine)
    target = await executor.fetch(1).execute(
        f'SELECT action FROM {executor.schema}actions WHERE action = {steps.next()}', to_action)
    if not target:
        return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': f'Target action {to_action} does not exist'})

    steps = Steps(req.app._.engine)
    src = await executor.fetch(2).execute(
        f'''SELECT application, max_retries, handler, description FROM {executor.schema}subscriptions
            WHERE action = {steps.next()} AND active <> 0''', from_action)

    now = datetime.now(tz=timezone.utc).isoformat()
    created, reactivated = 0, 0
    for application, max_retries, handler, description in (src or []):
        identifier = uuid4().hex
        steps = Steps(req.app._.engine)
        fields = ('subscription', 'application', 'action', 'max_retries', 'handler', 'description', 'active', 'timestamped',)
        values = (identifier, application, to_action, max_retries, handler, description, 1, now)
        try:
            sqls = f'''INSERT INTO {executor.schema}subscriptions ({', '.join(fields)}) VALUES ({steps.reset.next(8)});'''
            await executor.fetch(0).execute(sqls, *values)
            created += 1
        except (UniqueViolationError, IntegrityError):
            steps = Steps(req.app._.engine)
            upd = (f'UPDATE {executor.schema}subscriptions SET active = 1 '
                   f'WHERE application = {steps.next()} AND action = {steps.next()} AND handler = {steps.next()}')
            await executor.fetch(0).execute(upd, application, to_action, handler)
            reactivated += 1
        except Exception as exc:
            return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    if migration.deactivate_source:
        steps = Steps(req.app._.engine)
        await executor.fetch(0).execute(
            f'UPDATE {executor.schema}subscriptions SET active = 0 WHERE action = {steps.next()}', from_action)

    return res.out(HTTPStatus.OK, {
        'from_action': from_action,
        'to_action': to_action,
        'created': created,
        'reactivated': reactivated,
        'deactivated_source': bool(migration.deactivate_source),
    })
