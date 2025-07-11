from functools import wraps
from http import HTTPStatus
from inspect import iscoroutinefunction
from sqlite3 import Connection

from asyncpg import Pool
from fastjsonschema import compile
from heaven import App, Context, Request, Response
from orjson import dumps, loads
from pydantic import BaseModel

from amebo.utils.structs import Lookup
from amebo.constants.literals import DB


class Executor(object):
    def __init__(self, app: App):
        self.app = app
        self.engine = self.app._.engine
        self.db = self.app._.db
        self._fetching = 0

    @property
    def schema(self):
        if self.engine == 'sqlite': return ''
        return '_amebo_.'

    def fetch(self, val: int):
        self._fetching = val
        return self

    async def _pg(self, query: str, *args):
        if self.db is None:
            # Handle case where database connection failed (e.g., in tests)
            print("Warning: PostgreSQL database connection is None, skipping query")
            if self._fetching == 1: return None
            if self._fetching > 1: return []
            else: return None

        async with self.db.acquire() as conn:
            async with conn.transaction():
                if self._fetching == 1: return await conn.fetchrow(query, *args)
                if self._fetching > 1: return await conn.fetch(query, *args)
                else: return await conn.execute(query, *args)

    async def _sqlite(self, query: str, *args: tuple):
        cursor = self.db.cursor()
        try:
            if self._fetching == 1: return cursor.execute(query, args).fetchone()
            if self._fetching > 1: return cursor.execute(query, args).fetchall()
            else: return cursor.execute(query, args); self.db.commit()
        except Exception as exc: raise exc
        finally: cursor.close()

    def esc(self, count: int):
        return '?' if self.engine == 'sqlite' else f'${count}'

    @property
    def execute(self, *args, **kwargs):
        async def acaller(*args, **kwargs):
            if self.engine == 'sqlite': return await self._sqlite(*args, **kwargs)
            return await self._pg(*args, **kwargs)
        return acaller


def cacheschema(func):
    @wraps(func)
    async def delegate(req: Request, res: Response, ctx: Context):
        if iscoroutinefunction(func): await func(req, res, ctx)
        else: func(req, res, ctx)
        if req.app._.schematas.get(ctx.schemata_name): pass
        else: req.app._.schematas[ctx.schemata_name] = compile(ctx.schemata)
    return delegate


def contextualize(func):
    @wraps(func)
    async def delegate(req: Request, res: Response, ctx: Context):
        ctx.keep('executor', Executor(req.app))
        if iscoroutinefunction(func): await func(req, res, ctx)
        else: func(req, res, ctx)
    return delegate


def expects(Model: BaseModel):
    def wrapper(func):
        async def delegate(req: Request, res: Response, ctx: Context):
            appjson, ctype = 'application/json', 'content-type'
            res.headers = ctype, appjson
            if(req.headers.get(ctype) != appjson):
                res.status = HTTPStatus.IM_A_TEAPOT
                res.body = {'error': 'your request does not know json kung-fu'}
                return

            try:
                body = loads(req.body)
                model = Model(**body)
                mname = model.__class__.__name__.lower()
                ctx.keep(mname, model)
            except Exception as exc:
                error = exc.errors()[0]
                res.status = HTTPStatus.BAD_REQUEST
                print('-' * 20, error)
                res.body = {'error': f"{error.get('loc')[0]} - {error.get('msg')}"}
                print('-' * 10, res.body)
                return

            if iscoroutinefunction(func): await func(req, res, ctx)
            else: func(req, res, ctx)
        return delegate
    return wrapper


def inspects(schema: dict):
    validation = compile(schema)  # validictory?
    def decorator(func):
        @wraps(func)
        async def delegate(req: Request, res: Response, ctx: Context):
            try: payload = validation(loads(req.body))
            except: return res.out(HTTPStatus.NOT_ACCEPTABLE, 'Invalid data detected')
            ctx.keep('data', Lookup({key: value for key, value in payload.items() if value}))
            return await func(req, res, ctx)
        return delegate
    return decorator
