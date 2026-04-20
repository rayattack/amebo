import asyncio
import logging
from asyncio import gather, sleep
from datetime import datetime, timedelta
from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Router
from httpx import AsyncClient, ReadTimeout, Timeout
from orjson import loads

# src code
from amebo.constants.literals import DB, X_AMEBO_SIGNATURE
from amebo.decorators.providers import Executor
from amebo.utils.helpers import datasigner

logger = logging.getLogger('amebo.aproko')


async def aproko(router: Router):
    executor = Executor(router)
    x = executor.schema
    accepters = []
    rejecters = []

    # Check if database is available
    if executor.db is None and executor.engine and executor.engine.startswith('postgres'):
        logger.warning('Database connection not available, aproko daemon will not run')
        return False

    async def notify(endpoint: str, data: dict, metadata: dict, secret: str, gist_id: str, attempt_number: int, action: str):
        payload= {'action': action, 'metadata': metadata, 'payload': data}
        headers = {
            'Content-Type': 'application/json',
            X_AMEBO_SIGNATURE: datasigner(payload, secret),
            'x-amebo-event-id': gist_id,  # For idempotency
            'x-amebo-delivery-attempt': str(attempt_number),  # Our delivery tracking
        }

        client = None
        try:
            timeout = Timeout(10.0, connect=5.0)
            client = AsyncClient(timeout=timeout)
            result = await client.post(endpoint, json=payload, headers=headers)

            if 200 <= result.status_code < 300: accepters.append(gist_id)
            else: rejecters.append(gist_id)
        except ReadTimeout:
            accepters.append(gist_id)
        except Exception as exc:
            logger.error('Delivery failed for %s: %s', endpoint, exc)
            rejecters.append(gist_id)
        finally:
            if client: await client.aclose()

    async def reconcile():
        try:
            if rejecters:
                rejections = str(tuple(rejecters)).replace(',)', ')')
                sqls = f'''UPDATE {x}gists SET retries = retries + 1 WHERE gist IN {rejections};'''
                await executor.fetch(0).execute(sqls)
        except Exception as exc: logger.error('Could not update rejections: %s', exc)

        try:
            if accepters:
                acceptances = str(tuple(accepters)).replace(',)', ')')
                sqls = f'''UPDATE {x}gists SET completed = 1, retries = retries + 1 WHERE gist IN {acceptances};'''
                await executor.fetch(0).execute(sqls)
        except Exception as exc: logger.error('Could not update acceptances: %s', exc)

    async def traverse():
        try:
            now = datetime.now()
            if executor.engine.startswith('post'):
                # Enterprise Optimization: SKIP LOCKED
                # This turns the DB into a concurrent queue by locking rows & hiding them from other workers
                lease_expiry = now + timedelta(seconds=60)
                sqls = f'''
                    WITH picked AS (
                        SELECT g.gist
                        FROM {x}gists AS g
                        JOIN {x}subscriptions s ON s.subscription = g.subscription
                        WHERE g.completed <> 1
                        AND g.retries < s.max_retries
                        AND (g.sleep_until IS NULL OR g.sleep_until < $1::timestamp)
                        ORDER BY g.event LIMIT {router.CONFIG('envelope_size')}
                        FOR UPDATE SKIP LOCKED
                    ),
                    leased AS (
                        UPDATE {x}gists g
                        SET sleep_until = $2::timestamp
                        FROM picked
                        WHERE g.gist = picked.gist
                        RETURNING g.gist
                    )
                    SELECT
                        s.handler AS endpoint, e.payload, e.metadata, a.secret, g.gist as gid,
                        g.retries, e.action
                    FROM {x}gists AS g
                    JOIN leased l ON g.gist = l.gist
                    JOIN {x}events e ON g.event = e.event
                    JOIN {x}subscriptions s ON s.subscription = g.subscription
                    JOIN {x}actions x ON e.action = x.action
                    JOIN {x}applications a ON s.application = a.application;
                '''
                gists = await executor.fetch(2).execute(sqls, now, lease_expiry)
            else:
                now_iso = now.isoformat()
                sqls = f'''
                    SELECT
                        s.handler AS endpoint, e.payload, e.metadata, a.secret, g.gist as gid,
                        g.retries, e.action
                    FROM {x}gists AS g JOIN {x}events e ON
                        g.event = e.event
                    JOIN {x}subscriptions s ON
                        s.subscription = g.subscription
                    JOIN {x}actions x ON
                        e.action = x.action
                    JOIN {x}applications a ON
                        s.application = a.application
                    WHERE g.completed <> 1
                    AND g.retries < s.max_retries
                    AND (g.sleep_until IS NULL OR g.sleep_until < '{now_iso}'::timestamp)
                    ORDER BY g.event LIMIT {router.CONFIG('envelope_size')};
                '''
                gists = await executor.fetch(2).execute(sqls)

            if gists is None: gists = []
            await gather(*[notify(endpoint, loads(payload), loads(metadata), secret, str(gid), retries, action) for endpoint, payload, metadata, secret, gid, retries, action in gists])
            await reconcile()
            return len(gists)
        except Exception as exc:
            logger.error('Traverse cycle failed: %s', exc)
            return 0
    count = await traverse()

    # PostgreSQL: wait for NOTIFY wake signal (instant delivery), with fallback sweep.
    # SQLite: poll every few seconds as before (no LISTEN/NOTIFY support).
    if count == 0:
        wake_event = getattr(router._, 'wake_event', None)
        if wake_event:
            wake_event.clear()
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=router.CONFIG('idles'))
            except asyncio.TimeoutError:
                pass
        else:
            await sleep(router.CONFIG('idles'))

    return True


def cli():
    pass
