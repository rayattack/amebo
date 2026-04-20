import asyncio
import logging
from inspect import iscoroutinefunction
from os import environ
from sqlite3 import Connection

from heaven import Application
from asyncpg import connect as pg_connect, create_pool

from amebo.constants.literals import AMEBO_SECRET, DB
from amebo.constants.scripts import initdbscript
from amebo.utils.structs import Lookup
from amebo.database.pg import pgscript
from amebo.utils.helpers import deterministic_uuid

logger = logging.getLogger('amebo.database')

ENGINES = {
    'sqlite': lambda *args: Connection(*args),
    'postgres': lambda *args: create_pool(*args)
}


async def connect(app: Application):
    dsn = environ.get('AMEBO_DSN')
    engine = 'postgres' if dsn else 'sqlite'
    app.keep('engine', engine)
    db = None
    try:
        if engine.startswith('postgres'): db = await create_pool(dsn)
        else: db = Connection('amebo.db')
    except Exception as exc:
        logger.error('Connection middleware failed: %s', exc)
        # Set a default connection for testing environments
        if engine.startswith('postgres'):
            db = None  # Will be handled by Executor
        else: db = Connection(':memory:')  # In-memory SQLite for tests
    app.keep(DB, db)


async def disconnect(app: Application):
    try: db: Connection = app.peek(DB)
    except Exception as exc: logger.error('Exception closing db on shutdown: %s', exc)
    else:
        if(iscoroutinefunction(db.close)): await db.close()
        else: db.close()


async def initialize(app: Application):
    """todo: enable switching db backend between redis, pg, sqlite"""
    logger.info('Initializing database')
    if app._.engine.startswith('postgres'):
        try: await app.peek(DB).execute(pgscript)
        except Exception as exc: logger.error('Exception in initdb hook: %s', exc)
    else:
        db: Connection = app.peek(DB)
        db.executescript(initdbscript)
        # migrate existing sqlite databases: add new columns
        for alter in [
            'ALTER TABLE applications ADD COLUMN apikey text',
            'ALTER TABLE applications ADD COLUMN active integer NOT NULL DEFAULT 1',
        ]:
            try: db.execute(alter)
            except Exception: pass  # column already exists


async def setup_listener(app: Application):
    """Create a dedicated PG connection for LISTEN/NOTIFY (outside the pool).
    SQLite does not support LISTEN/NOTIFY so this is a no-op for SQLite."""
    if not app._.engine.startswith('postgres'):
        return

    dsn = environ.get('AMEBO_DSN')
    if not dsn:
        return

    try:
        wake_event = asyncio.Event()
        listener_conn = await pg_connect(dsn)

        def on_notify(conn, pid, channel, payload):
            wake_event.set()

        await listener_conn.add_listener('aproko_wake', on_notify)
        app.keep('listener_conn', listener_conn)
        app.keep('wake_event', wake_event)
        logger.info('LISTEN aproko_wake registered on dedicated connection')
    except Exception as exc:
        logger.error('Failed to set up LISTEN connection: %s', exc)


async def teardown_listener(app: Application):
    """Close the dedicated LISTEN connection on shutdown."""
    try:
        listener_conn = app.peek('listener_conn')
        if listener_conn:
            await listener_conn.close()
    except Exception:
        pass


def cache(app: Application):
    app._.tokens = {}
    app._.schematas = {}
