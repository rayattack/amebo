class Lookup(object):
    def __init__(self, data: dict):
        self._data = data
    
    def __getattr__(self, key: str):
        value = self._data.get(key)
        if isinstance(value, dict):
            return Lookup(value)
        return value


class Steps(object):
    def __init__(self):
        self._first = None
        self._values = []
        self._misses = []

    def EQUALS(self, datum: any, key: str):
        # necessary as sqlite uses 0 a falsy value for false
        if(datum == 0 or datum):
            if(self.dirty):
                sqls = f'AND {key} = ?'
            else:
                sqls = f'WHERE {key} = ?'
            self._values.append(datum)
            return sqls
        return ''

    def LIKE(self, datum: any, key: str):
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
