from http import HTTPStatus
from inspect import iscoroutinefunction
from sqlite3 import Connection, Cursor, IntegrityError

# installed libs
from bcrypt import checkpw
from heaven import Context, Request, Response

# src code
from amebo.constants.literals import DB, AMEBO_SECRET, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import contextualize, expects
from amebo.utils.helpers import get_pagination, get_timeline, tokenize

from amebo.models.applications import Credential, Location, Application, Token
from amebo.utils.structs import Steps


@jsonify
@expects(Credential)
@contextualize
async def authenticate(req: Request, res: Response, ctx: Context):
    def unauthorized():
        res.status = HTTPStatus.UNAUTHORIZED
        res.body = {'error': 'could not authenticate microservice'}

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
        return unauthorized()

    if not row: return unauthorized()
    username, password = row
    if not checkpw(credential.password.encode(), password.encode()): return unauthorized()
    # no feedback is provided if secret key mismatches i.e. continue indicates just that

    token = tokenize({
        'scheme': credential.scheme,
        'username': username,
    }, req.app.CONFIG('AMEBO_SECRET'))
    res.headers = 'Set-Cookie', f'Authentication={token}; Path=/; HttpOnly; Max-Age={60*10}; SameSite=Strict; Secure'
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

    sqls = f'''SELECT application, address, timestamped
        FROM {executor.schema}applications
            {steps.LIKE('application', _application)}
            {steps.LIKE('address', _address)}
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
        'application': application,
        'address': address,
        'secret': '****************',
        'timestamped': timestamped
    } for application, address, timestamped in rows]


@jsonify
@expects(Application)
@contextualize
async def insert(req: Request, res: Response, ctx: Context):
    application: Application = ctx.application
    steps = Steps(req.app._.engine)
    try:
        executor = ctx.executor
        values = (str(application.application), str(application.address), application.secret, application.timestamped.isoformat())
        sqls = f'''INSERT INTO {executor.schema}applications(application, address, secret, timestamped) VALUES ({steps.next(4)})'''
        print(sqls)
        await executor.execute(sqls, *values)
    except IntegrityError as exc:
        res.status = HTTPStatus.CONFLICT
        res.body = {'error': f'{exc}'}
        return
    except Exception as exc:
        res.status = HTTPStatus.NOT_ACCEPTABLE
        res.body = {'error': f'{exc}'}
        return

    res.status = HTTPStatus.CREATED
    res.body = {
        'name': application.application,
        'address': str(application.address),
        'secret': application.secret,
        'timestamped': application.timestamped
    }


@jsonify
@expects(Location)
@contextualize
def update(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    application = req.params.get('id')
    location: Location = ctx.location

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
