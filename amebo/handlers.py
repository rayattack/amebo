from asyncio import (
    get_running_loop,
    sleep,
)
from http import HTTPStatus
from sqlite3 import Connection

# installed libs
from httpx import AsyncClient


async def amebo(db: Connection):
    """This is where washika handles its business"""
    try:
        cursor = db.cursor()
        rows = cursor.execute('SELECT position, action, payload, timestamped FROM events ORDER BY timestamped')
        row = rows.fetchone()
        if row:
            _, action, payload, _ = row
            for result in rows:
                subscribers = cursor.execute(f'SELECT application, endpoint, passphrase FROM subscribers WHERE action = {result.action}')
                for subscriber in subscribers:
                    application, endpoint, passphrase = subscriber
                    async with AsyncClient() as ahttp:
                        res = await ahttp.post(endpoint, data=payload, headers={'Authorization': f'bearer {passphrase}'})
                    if res.status_code != HTTPStatus.ACCEPTED:
                        cursor.execute(f'INSERT INTO subscribers')
    except Exception as exc:
        print(exc)
        cursor.close()


async def amebo_infinite_recursion_loop():
    loop = get_running_loop()
    # await amebo()
    # print('+')
    await sleep(2)
    loop.create_task(amebo_infinite_recursion_loop())
