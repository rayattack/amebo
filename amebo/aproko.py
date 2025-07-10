from asyncio import gather, sleep
from datetime import datetime
from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Router
from httpx import AsyncClient
from orjson import loads

# src code
from amebo.constants.literals import DB
from amebo.decorators.providers import Executor


async def aproko(router: Router):
    executor = Executor(router)
    x = executor.schema
    accepters = []
    rejecters = []
    async def notify(endpoint: str, data: dict, secret: str, gist_id: int):
        headers = {
            'Content-Type': 'application/json',
            'X-PASS-Phrase': secret
        }

        try:
            client = AsyncClient()
            result = await client.post(endpoint, json=data, headers=headers)
            if result.status_code not in [HTTPStatus.ACCEPTED, HTTPStatus.OK]: rejecters.append(int(gist_id))
            else: accepters.append(int(gist_id))
        except Exception as exc:
            print('Exception occured@@@@@@@@@@@@@@@@@@@@@@@@@: ', exc, ' ', endpoint)
            rejecters.append(gist_id)
        finally:
            await client.aclose()

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
                    s.handler AS endpoint, e.payload, a.secret, g.rowid as gid
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

            if len(gists) < router.CONFIG('rest_when'): await sleep(router.CONFIG('idles'))
            await gather(*[notify(endpoint, loads(payload), secret, gid) for endpoint, payload, secret, gid in gists])
        except Exception as exc: print('Exception occured: ', exc)
    await traverse()
    return True


def cli():
    pass
