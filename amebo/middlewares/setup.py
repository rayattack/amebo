from os import environ
from sqlite3 import Connection

from heaven import Router


def upsudo(router: Router) -> str:
    db: Connection = router.peek('db')
    username = environ.get('ADMINISTRATOR_USERNAME')
    password = environ.get('ADMINISTRATOR_PASSWORD')
    try:
        # credentials table dropped every time so this is possible
        db.execute(f'''
            INSERT INTO credentials VALUES(?, ?);
        ''', (username, password))
    except: pass
