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
from amebo.controllers.gists import writeback_attempt
from amebo.decorators.providers import Executor
from amebo.utils.helpers import datasigner, truncate_error

logger = logging.getLogger('amebo.aproko')


async def aproko(router: Router):
    executor = Executor(router)
    x = executor.schema
    # Each entry records the outcome of one attempt so reconcile can write the
    # delivery result (status code / error / attempted_at) back onto the gist row.
    results = []

    # Check if database is available
    if executor.db is None and executor.engine and executor.engine.startswith('postgres'):
        logger.warning('Database connection not available, aproko daemon will not run')
        return False

    async def notify(endpoint: str, data: dict, metadata: dict, secret: str, rowid, header_id: str, attempt_number: int, action: str):
        payload= {'action': action, 'metadata': metadata, 'payload': data}
        headers = {
            'Content-Type': 'application/json',
            X_AMEBO_SIGNATURE: datasigner(payload, secret),
            'x-amebo-event-id': str(header_id),  # For idempotency
            'x-amebo-delivery-attempt': str(attempt_number),  # Our delivery tracking
        }

        attempted_at = datetime.now().isoformat()
        outcome = {'rowid': rowid, 'ok': False, 'code': None, 'error': None, 'at': attempted_at}
        client = None
        try:
            timeout = Timeout(10.0, connect=5.0)
            client = AsyncClient(timeout=timeout)
            result = await client.post(endpoint, json=payload, headers=headers)
            outcome['code'] = result.status_code
            if 200 <= result.status_code < 300:
                outcome['ok'] = True
            else:
                outcome['error'] = truncate_error(result.text)
        except (ReadTimeout, Exception) as exc:
            # A timeout is NOT a success — the handler may never have run. Record it
            # as a failed attempt so the gist remains visible and retryable.
            logger.error('Delivery failed for %s: %s', endpoint, exc)
            outcome['error'] = truncate_error(f'{type(exc).__name__}: {exc}')
        finally:
            if client: await client.aclose()
            results.append(outcome)

    async def reconcile():
        # Write each attempt's result back onto its gist row, keyed on rowid (the
        # one identifier present on both PostgreSQL and SQLite). Shares the exact
        # write path as UI replay so daemon and replay record results identically.
        for r in results:
            try: await writeback_attempt(executor, r['rowid'], r['ok'], r['code'], r['error'], r['at'])
            except Exception as exc: logger.error('Could not reconcile gist %s: %s', r['rowid'], exc)
        results.clear()

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
                        s.handler AS endpoint, e.payload, e.metadata, a.secret, g.rowid as gid,
                        g.gist as header_id, g.retries, e.action
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
                # SQLite has no `gist` uuid column — address rows by rowid and use the
                # event uuid as the idempotency header. Lease via sleep_until so a slow
                # handler isn't re-picked on every poll.
                sqls = f'''
                    SELECT
                        s.handler AS endpoint, e.payload, e.metadata, a.secret, g.rowid as gid,
                        g.event as header_id, g.retries, e.action
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
                    AND (g.sleep_until IS NULL OR g.sleep_until < '{now_iso}')
                    ORDER BY g.timestamped LIMIT {router.CONFIG('envelope_size')};
                '''
                gists = await executor.fetch(2).execute(sqls)
                # lease the picked sqlite rows so they aren't re-fetched mid-flight
                lease = (now + timedelta(seconds=60)).isoformat()
                for row in (gists or []):
                    try: await executor.fetch(0).execute(f"UPDATE {x}gists SET sleep_until = ? WHERE rowid = ?;", lease, row[4])
                    except Exception as exc: logger.error('Could not lease sqlite gist: %s', exc)

            if gists is None: gists = []
            await gather(*[notify(endpoint, loads(payload), loads(metadata), secret, gid, header_id, retries, action) for endpoint, payload, metadata, secret, gid, header_id, retries, action in gists])
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
