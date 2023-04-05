from sqlite3 import connect, Connection

# installed libs
from washika import Washika as Router

# src code
from scripts import initdbscript


async def downsqlite(router: Router):
    try:
        db: Connection = router.peek('db')
    except Exception as exc:
        print('Exception in closing db on shutdown: ', exc)
    else:
        db: db.close()


async def initdb(router: Router):
    try:
        db: Connection = router.peek('db')
        db.executescript(initdbscript)
    except Exception as exc:
        print('Exception in initdb hook: ', exc)


async def upsqlite(router: Router):
    router.keep('db', connect(router.CONFIG('db')))
