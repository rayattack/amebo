from asyncio import gather, sleep
from http import HTTPStatus
from sqlite3 import Connection, Cursor
from typing import List

# installed libs
from httpx import AsyncClient
from orjson import loads

# src code
from washika import Washika as Router


async def amebo(router: Router):
    db: Connection = router.peek('db')
    accepters = []
    rejecters = []
    async def notify(endpoint: str, data: dict, passkey: str, gist_id: int):
        headers = {
            'Content-Type': 'application/json',
            'X-Secret-Key': passkey
        }

        try:
            client = AsyncClient()
            result = await client.post(endpoint, json=data, headers=headers)
            if result.status_code not in [HTTPStatus.ACCEPTED, HTTPStatus.OK]:
                rejecters.append(int(gist_id))
            else:
                accepters.append(int(gist_id))
        except Exception as exc:
            rejecters.append(gist_id)
        finally:
            await client.aclose()
        
        try:
            cursor: Cursor = db.cursor()
            cursor.execute(f'''
                UPDATE
                    gists
                SET
                    completed = 1
                WHERE rowid IN {format(tuple(accepters)).replace( ',)', ')' )};
            ''')
            db.commit()
        except Exception as exc:
            print('Could not update in notify: ', exc)
        finally:
            cursor.close()

    async def traverse():
        try:
            cursor: Cursor = db.cursor()
            gists = cursor.execute(f'''
                SELECT
                    m.location || s.endpoint AS endpoint, e.payload, m.passkey, g.rowid as gid
                FROM gists AS g JOIN events e ON
                    g.event = e.event
                JOIN subscribers s ON
                    s.subscriber = g.subscriber
                JOIN actions a ON
                    e.action = a.action
                JOIN microservices m ON
                    s.microservice = m.microservice
                WHERE g.completed <> 1
                ORDER BY g.event LIMIT {router.CONFIG('envelope_size')};
            ''').fetchall()

            if len(gists) < router.CONFIG('rest_when'): await sleep(router.CONFIG('idles'))
            await gather(*[notify(endpoint, loads(payload), passkey, gid) for endpoint, payload, passkey, gid in gists])

            db.commit()
        except Exception as exc:
            print('Exception occured: ', exc)
        finally:
            cursor.close()

    await traverse()
