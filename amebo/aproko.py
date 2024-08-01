from asyncio import gather, sleep
from http import HTTPStatus
from sqlite3 import Connection, Cursor

# installed libs
from heaven import Router
from httpx import AsyncClient
from orjson import loads

# src code
from amebo.constants.literals import DB


async def aproko(router: Router):
    db: Connection = router.peek(DB)
    accepters = []
    rejecters = []
    async def notify(endpoint: str, data: dict, passphrase: str, gist_id: int):
        headers = {
            'Content-Type': 'application/json',
            'X-PASS-Phrase': passphrase
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
        cursor = None
        try:
            cursor: Cursor = db.cursor()
            gists = cursor.execute(f'''
                SELECT
                    p.location || s.handler AS endpoint, e.payload, p.passphrase, g.rowid as gid
                FROM gists AS g JOIN events e ON
                    g.event = e.event
                JOIN subscribers s ON
                    s.subscription = g.subscription
                JOIN actions a ON
                    e.action = a.action
                JOIN producers p ON
                    s.producer = p.name
                WHERE g.completed <> 1
                ORDER BY g.event LIMIT {router.CONFIG('envelope_size')};
            ''').fetchall()

            if len(gists) < router.CONFIG('rest_when'): await sleep(router.CONFIG('idles'))
            await gather(*[notify(endpoint, loads(payload), passphrase, gid) for endpoint, payload, passphrase, gid in gists])

            db.commit()
        except Exception as exc:
            print('Exception occured: ', exc)
        finally:
            if cursor: cursor.close()

    await traverse()
