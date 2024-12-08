from os import environ
from sqlite3 import Connection
from heaven import Application, Response


async def cors(req, res: Response, ctx):
    res.headers = 'Access-Control-Allow-Credentials', 'true'


def upsudo(app: Application) -> str:
    db: Connection = app.peek('db')
    username = environ.get('AMEBO_ADMIN_USERNAME')
    password = environ.get('AMEBO_ADMIN_PASSWORD')
    # credentials table dropped every time so this is possible, what of producer credentials created after app start?
    try: db.execute(f'INSERT INTO credentials VALUES(?, ?);', (username, password))
    except: pass


def upsecret(app: Application):
    if not environ.get('AMEBO_SECRET_KEY'):
        print('Deterministic dev secret key is: ', app.CONFIG('AMEBO_SECRET_KEY'))

