from asyncpg import create_pool as pgpool
from aiosqlite import connect as liteconnect


class PostgresEngine(object):
    def __init__(self, *args):
        self.__pool = pgpool(*args)

    def create_microservice(self, microservice: str, endpoint: str, passkey: str):
        self.__redis.set(microservice, f'{endpoint} {passkey}')

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

    def create_microservice(self, microservice: str, endpoint: str, passkey: str):
        self.__redis.set(microservice, f'{endpoint} {passkey}')

    def delete_microservice(self, microservice: str):
        self.__redis.delete(microservice)

    def get_microservice(self, microservice: str):
        return self.__redis.get(microservice)

    def save_action(self, action: str, data: dict):
        self.__redis.set(action, data)

    def get_action(self, action: str):
        return self.__redis.get(action)
