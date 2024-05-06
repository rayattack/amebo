from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError

# installed libs
from heaven import Context, Request, Response

# src code
from amebo.constants.literals import DB, SECRET_KEY, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.utils.helpers import get_pagination, get_timeline, tokenize

from amebo.models.microservices import Credential, Location, Microservice
from amebo.utils.structs import Steps


@jsonify
@expects(Credential)
def authenticate(req: Request, res: Response, ctx: Context):
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
def tabulate(req: Request, res: Response, ctx: Context):
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
    finally:
        if cursor: cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'id': id,
        'microservice': microservice,
        'location': location,
        'passkey': '****************',
        'timestamped': timestamped
    } for id, microservice, location, timestamped in rows]


@jsonify
@expects(Microservice)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    microservice: Microservice = ctx.microservice
    try:
        cursor = db.cursor()
        values = (microservice.microservice, str(microservice.address), microservice.passkey, microservice.timestamped)
        cursor.execute('''
            INSERT into microservices(microservice, location, passkey, timestamped) VALUES (?, ?, ?, ?)
        ''', values)
        db.commit()
    except IntegrityError as exc:
        res.status = HTTPStatus.CONFLICT
        res.body = {'error': f'{exc}'}
        return
    except Exception as exc:
        res.status = HTTPStatus.NOT_ACCEPTABLE
        res.body = {'error': f'{exc}'}
        return
    finally:
        cursor.close()
    
    res.status = HTTPStatus.CREATED
    res.body = {
        'name': microservice.microservice,
        'location': str(microservice.address),
        'passkey': microservice.password,
        'timestamped': microservice.timestamped
    }


@jsonify
@expects(Location)
def update(req: Request, res: Response, ctx: Context):
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
