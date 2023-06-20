from os import environ
from sqlite3 import connect, Connection


# installed libs
from dotenv import load_dotenv
from washika import Washika as Router

# src code
from scripts import initdbscript


def administratorup(router: Router) -> str:
    db: Connection = router.peek('db')
    username = environ.get('ADMINISTRATOR_USERNAME')
    password = environ.get('ADMINISTRATOR_PASSWORD')
    try:
        # credentials table dropped every time so this is possible
        db.execute(f'''
            INSERT INTO credentials VALUES(?, ?);
        ''', (username, password))
    except:
        pass


async def downsqlite(router: Router):
    try:
        db: Connection = router.peek('db')
    except Exception as exc:
        print('Exception in closing db on shutdown: ', exc)
    else:
        db: db.close()


async def envup(router: Router):
    load_dotenv()


async def initdb(router: Router):
    """TODO: enable switching db backend between redis, pg, sqlite"""
    try:
        db: Connection = router.peek('db')
        db.executescript(initdbscript)
    except Exception as exc:
        print('Exception in initdb hook: ', exc)


async def upsqlite(router: Router):
    router.keep('db', connect(router.CONFIG('db')))
