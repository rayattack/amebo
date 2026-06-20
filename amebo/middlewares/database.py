import asyncio
import logging
from inspect import iscoroutinefunction
from os import environ
from sqlite3 import Connection

from heaven import Application
from asyncpg import connect as pg_connect, create_pool

from amebo.constants.literals import AMEBO_SECRET, DB
from amebo.constants.scripts import initdbscript
from amebo.decorators.providers import Executor
from amebo.utils.structs import Lookup
from amebo.database.pg import pgscript
from amebo.utils.helpers import deterministic_uuid
from amebo.utils.versioning import parse_action, schema_fingerprint

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
            # delivery-result tracking on gists (P0: make failures visible)
            'ALTER TABLE gists ADD COLUMN last_status_code integer',
            'ALTER TABLE gists ADD COLUMN last_error text',
            'ALTER TABLE gists ADD COLUMN last_attempted_at text',
            # first-class dead-letter marker (P2): set when a gist exhausts its retries
            'ALTER TABLE gists ADD COLUMN dead_at text',
            # action version registry (families, lifecycle, immutable-schema fingerprint)
            'ALTER TABLE actions ADD COLUMN family text',
            "ALTER TABLE actions ADD COLUMN status text NOT NULL DEFAULT 'active'",
            'ALTER TABLE actions ADD COLUMN successor text',
            "ALTER TABLE actions ADD COLUMN compatibility text NOT NULL DEFAULT 'BACKWARD'",
            'ALTER TABLE actions ADD COLUMN schema_hash text',
            # soft-unsubscribe: deactivated subscriptions stop fan-out and delivery
            'ALTER TABLE subscriptions ADD COLUMN active integer NOT NULL DEFAULT 1',
        ]:
            try: db.execute(alter)
            except Exception: pass  # column already exists


async def backfill_versioning(app: Application):
    """Populate `family` and `schema_hash` for actions registered before the version
    registry existed. Idempotent: only touches rows still missing those values, so it
    is safe to run on every boot. New rows are populated at registration time."""
    executor = Executor(app)
    if executor.db is None:
        return
    x = executor.schema
    try:
        rows = await executor.fetch(2).execute(
            f'SELECT action, schemata FROM {x}actions WHERE family IS NULL OR schema_hash IS NULL')
    except Exception as exc:
        logger.error('Versioning backfill skipped: %s', exc)
        return

    for action, schemata in (rows or []):
        family = parse_action(action)['family']
        try: fingerprint = schema_fingerprint(schemata)
        except Exception: fingerprint = None
        sqls = (f'UPDATE {x}actions SET family = {executor.esc(1)}, schema_hash = {executor.esc(2)} '
                f'WHERE action = {executor.esc(3)}')
        try: await executor.fetch(0).execute(sqls, family, fingerprint, action)
        except Exception as exc: logger.error('Could not backfill action %s: %s', action, exc)


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
