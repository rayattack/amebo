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
from amebo.models.actions import Action, ActionTransition
from amebo.utils.compatibility import check as check_compatibility
from amebo.utils.helpers import get_pagination, get_timeline, datachecker, untokenize
from amebo.utils.structs import Steps
from amebo.utils.versioning import parse_action, schema_fingerprint, next_version_hint


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['id', 'action', 'application', 'schemata', 'family', 'status', 'timeline']
    _id, _action, _application, _schemata, _family, _status, _timeline = [req.queries.get(p) for p in params]

    steps = Steps(req.app._.engine)
    executor = ctx.executor

    sqls = f'''
        SELECT
            rowid, action, application, schemata, family, status, successor, compatibility, timestamped
        FROM
            {executor.schema}actions
            {steps.EQUALS('rowid', _id)}
            {steps.LIKE('action', _action)}
            {steps.LIKE('application', _application)}
            {steps.LIKE('schemata', _schemata)}
            {steps.LIKE('family', _family)}
            {steps.EQUALS('status', _status)}
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
        'family': family,
        'version': parse_action(action)['version'],
        'status': status,
        'successor': successor,
        'compatibility': compatibility,
        'timestamped': timestamped
    } for id, action, application, schemata, family, status, successor, compatibility, timestamped in rows]


@jsonify
@expects(Action)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    request_signature = req.headers.get(X_AMEBO_SIGNATURE)
    db: Connection = req.app.peek(DB)
    action: Action = ctx.action

    steps = Steps(req.app._.engine)
    executor = ctx.executor

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

    parsed = parse_action(action.action)
    family = parsed['family']
    fingerprint = schema_fingerprint(action.schemata)

    # 1) same name already registered? Schemas are IMMUTABLE: identical -> idempotent 200,
    #    changed -> reject and tell them to cut a new version (never silently replace).
    steps = Steps(req.app._.engine)
    sqls = f'SELECT schema_hash, schemata FROM {executor.schema}actions WHERE action = {steps.next()}'
    existing = await executor.fetch(1).execute(sqls, action.action)
    if existing:
        stored_hash, stored_schemata = existing
        if not stored_hash:
            stored_hash = schema_fingerprint(stored_schemata)
        if stored_hash == fingerprint:
            res.status = HTTPStatus.OK
            res.body = {**action.model_dump(), 'family': family, 'version': parsed['version'],
                        'status': 'active', 'unchanged': True}
            return
        if parsed['version']:
            message = (f'Action {action.action} already exists with a different schema. Schemas are '
                       f'immutable; register a new version (e.g. {next_version_hint(parsed)}).')
        else:
            message = (f'Action {action.action} already exists with a different schema. Schemas are '
                       f'immutable; register a new version by adding a version token '
                       f'(e.g. {next_version_hint(parsed)}), or deprecate this one with a successor.')
        return res.out(HTTPStatus.CONFLICT, {'error': message})

    # 2) new action in an existing family? Enforce strictly-increasing version + compatibility
    #    against the previous version, using the predecessor's promised compatibility policy.
    steps = Steps(req.app._.engine)
    sqls = f'SELECT action, schemata, compatibility FROM {executor.schema}actions WHERE family = {steps.next()}'
    try: siblings = await executor.fetch(2).execute(sqls, family)
    except Exception: siblings = []

    if siblings:
        latest_action, latest_schemata, latest_compatibility = max(
            siblings, key=lambda row: parse_action(row[0])['sortkey'])
        latest = parse_action(latest_action)

        if parsed['scheme'] and latest['scheme'] and parsed['scheme'] != latest['scheme']:
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error':
                f"Family {family} uses the {latest['scheme']} version scheme; "
                f"{action.action} uses {parsed['scheme']}. Keep one scheme per family."})

        if parsed['sortkey'] <= latest['sortkey']:
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error':
                f"Version must come after the latest in family {family} "
                f"({latest['version'] or 'the unversioned base'}). Try {next_version_hint(latest)}."})

        ok, reasons = check_compatibility(loads(latest_schemata), action.schemata, latest_compatibility)
        if not ok:
            return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {
                'error': f'Schema is not {latest_compatibility}-compatible with {latest_action}',
                'compatibility': latest_compatibility,
                'predecessor': latest_action,
                'reasons': reasons,
            })

    # 3) persist the new version
    steps = Steps(req.app._.engine)
    fields = ('action', 'application', 'schemata', 'family', 'status', 'compatibility', 'schema_hash', 'timestamped',)
    values = (action.action, action.application, dumps(action.schemata).decode(), family, 'active',
              action.compatibility, fingerprint, action.timestamped.isoformat())
    try:
        sqls = f'''INSERT INTO {executor.schema}actions({', '.join(fields)}) VALUES ({steps.reset.next(8)})'''
        await executor.fetch(0).execute(sqls, *values)
    except UniqueViolationError:
        # raced with a concurrent identical registration: treat as idempotent success
        return res.out(HTTPStatus.OK, {**action.model_dump(), 'family': family,
                                       'version': parsed['version'], 'status': 'active', 'unchanged': True})
    except Exception as exc:
        return res.out(HTTPStatus.UPGRADE_REQUIRED, {'error': f'{exc}'})

    # handle x-amebo-redact header: space-separated field paths
    redact_header = req.headers.get(X_AMEBO_REDACT)
    if redact_header:
        field_paths = redact_header.split(' ')
        await bulk_insert_redactions(executor, action.action, field_paths)

    ctx.keep('schemata', action.schemata)
    res.status = HTTPStatus.CREATED
    res.body = {**action.model_dump(), 'family': family, 'version': parsed['version'], 'status': 'active'}


@jsonify
@expects(ActionTransition)
@contextualize
async def transition(req: Request, res: Response, ctx: Context):
    """Move an action through its lifecycle: active -> deprecated -> retired, and/or set
    its successor. Non-destructive (use DELETE to purge). Owner-signed or admin."""
    transition: ActionTransition = ctx.actiontransition
    if transition.status is None and transition.successor is None:
        return res.out(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': 'Provide at least one of status or successor'})

    name = req.params.get('id')
    executor = ctx.executor
    steps = Steps(req.app._.engine)

    sqls = f'''
        SELECT a.application, a.status, a.successor, app.secret
        FROM {executor.schema}actions a
        JOIN {executor.schema}applications app ON app.application = a.application
        WHERE a.action = {steps.next()}
    '''
    row = await executor.fetch(1).execute(sqls, name)
    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': f'Action {name} not found'})
    application, current_status, current_successor, secret = row

    request_signature = req.headers.get(X_AMEBO_SIGNATURE)
    try:
        if request_signature:
            if not datachecker(loads(req.body), request_signature, secret): raise ValueError('Invalid signature')
        else:
            admin_auth = req.cookies.get('Authentication')
            if not admin_auth: raise ValueError('Authentication required')
            try: untokenize(admin_auth, req.app.peek(AMEBO_SECRET))
            except Exception: raise ValueError('Invalid admin credentials')
    except Exception as exc:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': f'{exc}'})

    sqlite = executor.engine == 'sqlite'
    set_parts, args = [], []
    if transition.status is not None:
        set_parts.append(f"status = {'?' if sqlite else f'${len(args) + 1}'}")
        args.append(transition.status)
    if transition.successor is not None:
        set_parts.append(f"successor = {'?' if sqlite else f'${len(args) + 1}'}")
        args.append(transition.successor)
    where_ph = '?' if sqlite else f'${len(args) + 1}'
    args.append(name)

    sqls = f'UPDATE {executor.schema}actions SET {", ".join(set_parts)} WHERE action = {where_ph}'
    try: await executor.fetch(0).execute(sqls, *args)
    except Exception as exc:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'{exc}'})

    res.status = HTTPStatus.OK
    res.body = {
        'action': name,
        'status': transition.status if transition.status is not None else current_status,
        'successor': transition.successor if transition.successor is not None else current_successor,
    }


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
