from typing import Any


class Lookup(object):
    def __init__(self, data: dict):
        self._data = data
        self.name = '45'

    def __getattr__(self, key: str):
        if key == '_': return {'dollar': '$'}
        value = self._data.get(key)
        if isinstance(value, dict):
            return Lookup(value)
        return value

    def __setattr__(self, __name: str, __value: Any) -> None:
        if __name == '_data': super().__setattr__(__name, __value)
        else: self._data[__name] = __value


class Steps(object):
    def __init__(self):
        self._first = None
        self._values = []
        self._misses = []

    def EQUALS(self, key: str, datum: any):
        # necessary as sqlite uses 0 a falsy value for false
        if(datum == 0 or datum):
            if(self.dirty):
                sqls = f'AND {key} = ?'
            else:
                sqls = f'WHERE {key} = ?'
            self._values.append(datum)
            return sqls
        return ''

    def LIKE(self, key: str, datum: any):
        if(datum):
            if(self.dirty):
                sqls = f'AND {key} LIKE ?'
            else:
                sqls = f'WHERE {key} LIKE ?'
            self._values.append(f'%{datum}%')
            return sqls
        return ''

    @property
    def dirty(self) -> bool:
        return bool(self._values)

    @property
    def values(self) -> list:
        return self._values
