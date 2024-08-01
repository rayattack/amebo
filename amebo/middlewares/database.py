from os import environ
from sqlite3 import Connection

from heaven import Application
from redis import Redis
from asyncpg import connect as pgconnect

from amebo.constants.literals import DB
from amebo.constants.scripts import initdbscript
from amebo.utils.structs import Lookup


ENGINES = {
    'sqlite': lambda *args: Connection(*args),
    'redis': lambda *args: Redis(*args),
    'postgres': lambda *args: pgconnect(*args)
}


async def connect(app: Application):
    engine = app.CONFIG(DB).lower()
    app.keep('engine', engine)
    connection = ENGINES.get(engine)
    db = connection(environ.get('AMEBO_DSN') or 'amebo.db')
    app.keep(DB, db)


async def disconnect(app: Application):
    try: db: Connection = app.peek(DB)
    except Exception as exc: print('Exception in closing db on shutdown: ', exc)
    else: db: db.close()


async def initialize(app: Application):
    """todo: enable switching db backend between redis, pg, sqlite"""
    try:
        db: Connection = app.peek(DB)
        db.executescript(initdbscript)
    except Exception as exc:
        print('Exception in initdb hook: ', exc)


def cache(app: Application):
    app._.tokens = {}
