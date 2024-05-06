from functools import wraps
from http import HTTPStatus
from inspect import iscoroutinefunction

from fastjsonschema import compile
from heaven import Context, Request, Response
from orjson import dumps, loads
from pydantic import BaseModel

from amebo.utils.structs import Lookup


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
