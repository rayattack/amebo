from os import environ
from sqlite3 import Connection

from heaven import Router


def upsudo(router: Router) -> str:
    db: Connection = router.peek('db')
    username = environ.get('AMEBO_ADMIN_USERNAME')
    password = environ.get('AMEBO_ADMIN_PASSWORD')
    try:
        # credentials table dropped every time so this is possible
        db.execute(f'''
            INSERT INTO credentials VALUES(?, ?);
        ''', (username, password))
    except: pass

