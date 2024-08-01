from http import HTTPStatus
from sqlite3 import Connection, Cursor, IntegrityError

# installed libs
from heaven import Context, Request, Response

# src code
from amebo.constants.literals import DB, AMEBO_SECRET_KEY, MAX_PAGINATION
from amebo.decorators.formatters import jsonify
from amebo.decorators.providers import expects
from amebo.utils.helpers import get_pagination, get_timeline, tokenize

from amebo.models.producers import Credential, Location, Producer, Token
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
        password_field = 'passphrase'

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
    }, req.app.CONFIG(req.app._.AMEBO_SECRET_KEY))
    res.headers = 'Set-Cookie', f'Authentication={token}; Path=/; HttpOnly; Max-Age={60*10}; SameSite=Strict; Secure'
    res.status = HTTPStatus.ACCEPTED
    res.body = {'token': token}


@jsonify
def tabulate(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    page, pagination = get_pagination(req)
    params = ['name', 'location', 'timeline']
    _name, _location, _timeline = [req.queries.get(p) for p in params]
    steps = Steps()

    n = 'name'

    sqls = f'''SELECT name, location, timestamped
        FROM producers
            {steps.LIKE('name', _name)}
            {steps.LIKE('location', _location)}
            {get_timeline(_timeline, steps)}
        LIMIT {pagination if pagination < MAX_PAGINATION else MAX_PAGINATION}
        OFFSET {(page - 1) * pagination};
    '''
    try:
        cursor = db.cursor()
        rows = cursor.execute(sqls, steps.values).fetchall()
    except KeyError as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': f'{exc}'}
        return
    finally:
        if cursor: cursor.close()

    res.status = HTTPStatus.OK
    res.body = [{
        'name': name,
        'location': location,
        'passphrase': '****************',
        'timestamped': timestamped
    } for name, location, timestamped in rows]


@jsonify
@expects(Producer)
def insert(req: Request, res: Response, ctx: Context):
    db: Connection = req.app.peek(DB)
    producer: Producer = ctx.producer
    try:
        cursor = db.cursor()
        values = (producer.name, str(producer.address), producer.passphrase, producer.timestamped)
        cursor.execute('''
            INSERT into producers(name, location, passphrase, timestamped) VALUES (?, ?, ?, ?)
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
        'name': producer.name,
        'location': str(producer.address),
        'passphrase': producer.passphrase,
        'timestamped': producer.timestamped
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
                WHERE microservice = ? AND passphrase = ?
        ''', (location.location, microservice, location.passphrase))
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'could not update microservice'}
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
            SELECT microservice, passphrase FROM microservices WHERE microservice = ?
        ''', (token.microservice)).fetchall()
    except Exception as exc:
        res.status = HTTPStatus.BAD_REQUEST
        res.body = {'error': 'could not update microservice'}
        return
    finally:
        if cursor: cursor.close()

    res.status = HTTPStatus.ACCEPTED
    res.headers = 'set-cookie', '#cookie body here'
    res.body = {'token': token}
