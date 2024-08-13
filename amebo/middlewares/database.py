from inspect import iscoroutinefunction
from os import environ
from sqlite3 import Connection

from heaven import Application
from asyncpg import create_pool

from amebo.constants.literals import DB
from amebo.constants.scripts import initdbscript
from amebo.utils.structs import Lookup
from amebo.database.pg import pgscript


ENGINES = {
    'sqlite': lambda *args: Connection(*args),
    'postgres': lambda *args: create_pool(*args)
}


async def connect(app: Application):
    engine = app.CONFIG('engine').lower()
    app.keep('engine', engine)
    if engine == 'postgres': db = await create_pool(environ.get('AMEBO_DSN'))
    else: db = Connection('amebo.db')
    app.keep(DB, db)


async def disconnect(app: Application):
    try: db: Connection = app.peek(DB)
    except Exception as exc: print('Exception in closing db on shutdown: ', exc)
    else:
        if(iscoroutinefunction(db.close)): await db.close()
        else: db.close()


async def initialize(app: Application):
    """todo: enable switching db backend between redis, pg, sqlite"""
    if app._.engine == 'postgres': await app.peek(DB).execute(pgscript)
    else:
        try:
            db: Connection = app.peek(DB)
            db.executescript(initdbscript)
        except Exception as exc:
            print('Exception in initdb hook: ', exc)


def cache(app: Application):
    app._.tokens = {}
    app._.schematas = {}
