from os import environ
from sqlite3 import Connection
from heaven import Application, Response


async def cors(req, res: Response, ctx):
    res.headers = 'Access-Control-Allow-Credentials', 'true'


def upsudo(app: Application) -> str:
    db: Connection = app.peek('db')
    username = environ.get('ADMINISTRATOR_USERNAME')
    password = environ.get('ADMINISTRATOR_PASSWORD')

    # credentials table dropped every time so this is possible, what of producer credentials created after app start?
    try: db.execute(f'INSERT INTO credentials VALUES(?, ?);', (username, password))
    except: pass
