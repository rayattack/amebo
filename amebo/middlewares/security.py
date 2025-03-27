from os import environ
from sqlite3 import Connection

from bcrypt import gensalt, hashpw 
from heaven import Application, Response


async def cors(req, res: Response, ctx):
    res.headers = 'Access-Control-Allow-Credentials', 'true'


async def upsudo(app: Application) -> str:
    db: Connection = app.peek('db')
    username = environ.get('AMEBO_USERNAME')
    pwd = environ.get('AMEBO_PASSWORD')
    password = hashpw(pwd.encode(), gensalt())
    print("Administrator Password: ", pwd)

    # credentials table dropped every time so this is possible, what of producer credentials created after app start?
    # this has the potential to overwrite admin credentials if updated by admin after start? So document
    # to admins the need to set password from environmental variable and that that will always override and reset
    # everything else set afterwards
    try:
        if(app._.engine.startswith('postgres')):
            await db.execute(f'''
                INSERT INTO _amebo_.credentials(username, password) VALUES($1, $2)
                    ON CONFLICT(username) DO UPDATE SET password = EXCLUDED.password;
            ''', username, password.decode())
        else: db.execute('INSERT INTO credentials VALUES(?, ?);', (username, password.decode()))
    except Exception as exc: 
        print("SUDO Credentials not created....")
        print('*' * 100, f': {exc}')


def upsecret(app: Application):
    if not environ.get('AMEBO_SECRET'):
        print('Deterministic dev secret key is: ', app.CONFIG('AMEBO_SECRET'))
