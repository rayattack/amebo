import logging
from http import HTTPStatus
from inspect import iscoroutinefunction
from sqlite3 import Connection, Cursor, IntegrityError

# installed libs
from asyncpg import UniqueViolationError
from bcrypt import checkpw
from heaven import Context, Request, Response

# src code
from amebo.constants.literals import DB, AMEBO_SECRET, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.utils.helpers import get_pagination, get_timeline, tokenize, untokenize, generate_apikey, verify_apikey
from amebo.utils.netguard import validate_webhook_url
from amebo.utils.throttle import rate_limited, reset_attempts, client_key

from amebo.models.applications import Credential, Location, Application, Token, Provision, SecretUpdate
from amebo.utils.structs import Steps

logger = logging.getLogger('amebo.applications')


@jsonify
@expects(Credential)
@contextualize
async def authenticate(req: Request, res: Response, ctx: Context):
    def unauthorized():
        res.status = HTTPStatus.UNAUTHORIZED
        res.body = {'error': 'could not authenticate microservice'}

    # Throttle brute-force / credential-stuffing on the credential endpoint.
    throttle_key = client_key(req, scope='tokens')
    if rate_limited(throttle_key):
        res.status = HTTPStatus.TOO_MANY_REQUESTS
        res.body = {'error': 'Too many authentication attempts; try again later'}
        return

    db: Connection = req.app.peek(DB)
    credential: Credential = ctx.credential
    executor = ctx.executor

    table = 'credentials'
    username_field = 'username'
    password_field = 'password'
    if credential.scheme == 'token':
        table = 'applications'
        username_field = 'application'
        password_field = 'secret'

    try:
        SQL = f'''
            SELECT {username_field}, {password_field} FROM {executor.schema}{table}
                WHERE {username_field} = {executor.esc(1)}
        '''
        row = await executor.fetch(1).execute(SQL, (credential.username))
    except Exception as exc:
        logger.error('Authentication lookup failed: %s', exc)
        return unauthorized()

    if not row: return unauthorized()
    username, password = row
    if not checkpw(credential.password.encode(), password.encode()): return unauthorized()
    # no feedback is provided if secret key mismatches i.e. continue indicates just that

    # successful auth — clear this client's failed-attempt history
    reset_attempts(throttle_key)

    token = tokenize({
        'scheme': credential.scheme,
        'username': username,
    }, req.app.peek(AMEBO_SECRET))
    res.headers = 'Set-Cookie', f'Authentication={token}; Path=/; HttpOnly; Max-Age={60*15}; SameSite=Strict; Secure'
    res.status = HTTPStatus.ACCEPTED
    res.body = {'token': token}


@jsonify
@contextualize
async def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['application', 'address', 'timeline']
    _application, _address, _timeline = [req.queries.get(p) for p in params]
    steps = Steps(req.app._.engine)

    executor = ctx.executor

    sqls = f'''SELECT application, address, active, timestamped
        FROM {executor.schema}applications
            {steps.LIKE('application', _application)}
            {steps.LIKE('address', _address)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try: rows = await executor.fetch(2).execute(sqls, *steps.values)
    except Exception as exc:
        logger.error('Listing applications failed: %s', exc)
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'Could not list applications'}
        return

    res.status = HTTPStatus.OK
    res.body = [{
        'application': application,
        'address': address,
        'active': bool(active),
        'timestamped': timestamped
    } for application, address, active, timestamped in rows]


@jsonify
@expects(Provision)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    sk = req.app.peek(AMEBO_SECRET)
    authentication = req.cookies.get('Authentication')
    if not authentication:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Admin authentication required'})
    try: untokenize(authentication, sk)
    except Exception:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid admin credentials'})

    provision: Provision = ctx.provision

    # SSRF guard: an application's address is a delivery target. Reject addresses
    # that resolve to internal/non-routable hosts up front (see utils.netguard).
    ok, reason = validate_webhook_url(provision.address)
    if not ok:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'Invalid application address: {reason}'})

    plaintext_key, hashed_key = generate_apikey()
    steps = Steps(req.app._.engine)
    try:
        executor = ctx.executor
        values = (str(provision.application), str(provision.address), '', hashed_key, 1, provision.timestamped.isoformat())
        sqls = f'''INSERT INTO {executor.schema}applications(application, address, secret, apikey, active, timestamped) VALUES ({steps.next(6)})'''
        await executor.execute(sqls, *values)
    except (UniqueViolationError, IntegrityError):
        res.status = HTTPStatus.CONFLICT
        res.body = {'error': f'Application {provision.application} already exists'}
        return
    except Exception as exc:
        logger.error('Provisioning application failed: %s', exc)
        res.status = HTTPStatus.NOT_ACCEPTABLE
        res.body = {'error': 'Could not provision application'}
        return

    res.status = HTTPStatus.CREATED
    res.body = {
        'name': str(provision.application),
        'address': str(provision.address),
        'apikey': plaintext_key,
        'timestamped': provision.timestamped
    }


@jsonify
@expects(Location)
@contextualize
def update(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    application = req.params.get('id')
    location: Location = ctx.location

    # SSRF guard: changing an application's address re-points its delivery target.
    ok, reason = validate_webhook_url(location.location)
    if not ok:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': f'Invalid application address: {reason}'})

    executor = ctx.executor()
    try:
        cursor = db.cursor()
        cursor.execute(f'''
            UPDATE applications SET address = {executor.next()}
                WHERE application = {executor.next()} AND secret = {executor.next()}
        ''', (location.location, application, location.secret))
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'could not update application'}
        return
    finally:
        cursor.close()

    # no feedback if provided if secret key mismatches i.e. continue indicates just that
    res.status = HTTPStatus.ACCEPTED
    res.body = None


@jsonify
@expects(Token)
def tokens(req: Request, res: Response, ctx: Context):
    # TODO: set cookie and return body at same time for browser and api
    token: Token = ctx.token
    db: Connection = req.app.peek(DB)

    try:
        cursor = db.cursor()
        cursor.execute(f'''
            SELECT application, secret FROM applications WHERE application = ?
        ''', (token.application)).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'could not update application'}
        return
    finally:
        if cursor: cursor.close()

    res.status = HTTPStatus.ACCEPTED
    res.headers = 'set-cookie', '#cookie body here'
    res.body = {'token': token}


@jsonify
@expects(SecretUpdate)
@contextualize
async def set_secret(req: Request, res: Response, ctx: Context):
    authorization = req.headers.get('authorization')
    if not authorization:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Authorization header required'})

    try:
        scheme, key = authorization.split(' ', 1)
        if scheme.lower() != 'bearer': raise ValueError()
    except Exception:
        return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Expected Authorization: Bearer <apikey>'})

    application_name = req.params.get('id')
    executor = ctx.executor
    steps = Steps(req.app._.engine)

    try:
        sqls = f'SELECT application, apikey, active FROM {executor.schema}applications WHERE application = {steps.next()}'
        row = await executor.fetch(1).execute(sqls, application_name)
    except Exception:
        return res.out(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': 'Database error'})

    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': 'Application not found'})

    app_name, apikey_hash, active = row
    if not active:
        return res.out(HTTPStatus.FORBIDDEN, {'error': 'Application is disabled'})
    if not apikey_hash:
        return res.out(HTTPStatus.FORBIDDEN, {'error': 'No API key configured for this application'})
    if not verify_apikey(key, apikey_hash):
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid API key'})

    secret_update: SecretUpdate = ctx.secretupdate
    sqls = f'UPDATE {executor.schema}applications SET secret = {steps.reset.next()} WHERE application = {steps.next()}'
    await executor.execute(sqls, secret_update.secret, application_name)

    res.status = HTTPStatus.ACCEPTED
    res.body = {'message': 'Secret updated successfully'}


@jsonify
@contextualize
async def regenerate_apikey(req: Request, res: Response, ctx: Context):
    sk = req.app.peek(AMEBO_SECRET)
    authentication = req.cookies.get('Authentication')
    if not authentication:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Admin authentication required'})
    try: untokenize(authentication, sk)
    except Exception:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid admin credentials'})

    application_name = req.params.get('id')
    executor = ctx.executor
    steps = Steps(req.app._.engine)

    # verify application exists
    sqls = f'SELECT application FROM {executor.schema}applications WHERE application = {steps.next()}'
    row = await executor.fetch(1).execute(sqls, application_name)
    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': 'Application not found'})

    plaintext_key, hashed_key = generate_apikey()
    sqls = f'UPDATE {executor.schema}applications SET apikey = {steps.reset.next()} WHERE application = {steps.next()}'
    await executor.execute(sqls, hashed_key, application_name)

    res.status = HTTPStatus.OK
    res.body = {'apikey': plaintext_key, 'application': application_name}


@jsonify
@contextualize
async def toggle_active(req: Request, res: Response, ctx: Context):
    sk = req.app.peek(AMEBO_SECRET)
    authentication = req.cookies.get('Authentication')
    if not authentication:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Admin authentication required'})
    try: untokenize(authentication, sk)
    except Exception:
        return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid admin credentials'})

    application_name = req.params.get('id')
    executor = ctx.executor
    steps = Steps(req.app._.engine)

    # fetch current active state and toggle
    sqls = f'SELECT active FROM {executor.schema}applications WHERE application = {steps.next()}'
    row = await executor.fetch(1).execute(sqls, application_name)
    if not row:
        return res.out(HTTPStatus.NOT_FOUND, {'error': 'Application not found'})

    new_active = 0 if row[0] else 1
    sqls = f'UPDATE {executor.schema}applications SET active = {steps.reset.next()} WHERE application = {steps.next()}'
    await executor.execute(sqls, new_active, application_name)

    res.status = HTTPStatus.OK
    res.body = {'application': application_name, 'active': bool(new_active)}
