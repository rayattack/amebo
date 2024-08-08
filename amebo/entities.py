from sqlite3 import Connection, Cursor
from typing import List, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class Entity(object):
    def __init__(self, model: BaseModel[T], db: Connection):
        self.db = db
        self.table = model.__class__.__name__.lower()
        self.cursor = db.cursor()

    def select_from(self, *fields: List[str]) -> T:
        return self.cursor.execute(f'SELECT {",".join(fields)} from {self.table}').fetchall()

    def select_by_id(self, key, value, *fields, offset=0, limit=25):
        return self.cursor.execute(f"""
            SELECT {','.join(fields)} FROM {self.table}
                WHERE {key} = ?
            OFFSET {offset} LIMIT {limit}
        """, value).fetchall()
