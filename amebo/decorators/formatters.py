from functools import wraps
from inspect import iscoroutinefunction

from fastjsonschema import compile
from heaven import Context, Request, Response
from orjson import dumps

from amebo.utils.structs import Lookup


def jsonify(func):
    @wraps(func)
    async def delegate(req, res, ctx: Context):
        if(iscoroutinefunction(func)): await func(req, res, ctx)
        else: func(req, res, ctx)
        res.headers = 'Content-Type', 'application/json'
        res.body = dumps(res.body)
    return delegate


def parameters(params: dict):
    def wrapper(func):
        @wraps(func)
        async def proxy(req: Request, res: Response, ctx: Context):
            lookup = {}
            for key, value in params.items():
                if key in req.params: lookup[key] = value(req.params.get(key))
                ctx.keep('params', Lookup(lookup))
            return await func(req, res, ctx)
        return proxy
    return wrapper


# ie. {name: {kind: str, default: ''}}
def queries(schema: dict):
    validator = compile(schema)
    def wrapper(func):
        @wraps(func)
        async def delegate(req: Request, res: Response, ctx: Context):
            qp = {}
            for param in params:
                # dict.values might give you results out of order if key order changed
                kind, default = param.get('kind'), param.get('default')
                try: value = kind(req.queries.get(param))
                except: value = default
                else: qp[param] = value
            ctx.keep('queryparams', qp)
            return await func(req, res, ctx)
        return delegate
    return wrapper
