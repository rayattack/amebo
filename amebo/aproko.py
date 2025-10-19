from asyncio import gather, sleep
from datetime import datetime
from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Router
from httpx import AsyncClient, ReadTimeout, Timeout
from orjson import loads

# src code
from amebo.constants.literals import DB
from amebo.decorators.providers import Executor


async def aproko(router: Router):
    executor = Executor(router)
    x = executor.schema
    accepters = []
    rejecters = []

    # Check if database is available
    if executor.db is None and executor.engine and executor.engine.startswith('postgres'):
        print("Warning: Database connection not available, aproko daemon will not run")
        return False
    async def notify(endpoint: str, data: dict, metadata: dict, secret: str, gist_id: int, attempt_number: int, action: str):
        headers = {
            'Content-Type': 'application/json',
            'X-PASS-Phrase': secret,
            'X-Amebo-Event-ID': str(gist_id),  # For idempotency
            'X-Amebo-Delivery-Attempt': str(attempt_number)  # Our delivery tracking
        }

        client = None
        try:
            timeout = Timeout(10.0, connect=5.0)
            client = AsyncClient(timeout=timeout)
            
            # Keep original structure - don't modify metadata
            result = await client.post(endpoint, json={
                'action': action,
                'metadata': metadata,  # Untouched from publisher
                'payload': data
            }, headers=headers)

            if 200 <= result.status_code < 300: accepters.append(int(gist_id))
            else: rejecters.append(int(gist_id))
        except ReadTimeout:
            await mark_as_timeout(gist_id, endpoint)
            
        except Exception as exc:
            print(f'Exception occurred: {exc} for {endpoint}')
            rejecters.append(gist_id)
        finally:
            if client: await client.aclose()

        try:
            rejections = str(tuple(rejecters)).replace(',)', ')')
            sqls = f'''
                UPDATE {x}gists SET retries = retries + 1 WHERE rowid IN {rejections};
            '''
            if rejecters: await executor.fetch(0).execute(sqls)
        except Exception as exc: print('Could not negate in notify: ', exc)

        try:
            acceptances = str(tuple(accepters)).replace(',)', ')')
            sqls = f'''
                UPDATE {x}gists SET completed = 1, retries = retries + 1 WHERE rowid IN {acceptances};
            '''
            if accepters: await executor.fetch(0).execute(sqls)
        except Exception as exc: print('Could not update in notify: ', exc)

    async def traverse():
        try:
            gists = await executor.fetch(2).execute(f'''
                SELECT
                    s.handler AS endpoint, e.payload, e.metadata, a.secret, g.rowid as gid,
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
                AND (g.sleep_until IS NULL OR g.sleep_until < '{datetime.now().isoformat()}'::timestamp)
                ORDER BY g.event LIMIT {router.CONFIG('envelope_size')};
            ''')

            if gists is None: gists = []
            if len(gists) < router.CONFIG('rest_when'): await sleep(router.CONFIG('idles'))
            await gather(*[notify(endpoint, loads(payload), loads(metadata), secret, gid, retries, action) for endpoint, payload, metadata, secret, gid, retries, action in gists])
        except Exception as exc: print('Exception occured: ', exc)
    await traverse()
    return True


def cli():
    pass
