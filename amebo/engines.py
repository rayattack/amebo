from asyncpg import create_pool as pgpool
from aiosqlite import connect as liteconnect


class PostgresEngine(object):
    def __init__(self, *args):
        self.__pool = pgpool(*args)
    
    @property
    def pool(self):
        return self.__pool

    async def create_microservice(self, microservice: str, endpoint: str, passphrase: str):
        async with self.pool.acquire() as conn:
            await conn.execute("", [])

    def delete_microservice(self, microservice: str):
        self.__redis.delete(microservice)

    def get_microservice(self, microservice: str):
        return self.__redis.get(microservice)

    def save_action(self, action: str, data: dict):
        self.__redis.set(action, data)

    def get_action(self, action: str):
        return self.__redis.get(action)


class LiteEngine(object):
    def __init__(self, *args):
        self.__conn = liteconnect(*args)

    def create_microservice(self, microservice: str, endpoint: str, passphrase: str):
        self.__redis.set(microservice, f'{endpoint} {passphrase}')

    def delete_microservice(self, microservice: str):
        self.__redis.delete(microservice)

    def get_microservice(self, microservice: str):
        return self.__redis.get(microservice)

    def save_action(self, action: str, data: dict):
        self.__redis.set(action, data)

    def get_action(self, action: str):
        return self.__redis.get(action)
