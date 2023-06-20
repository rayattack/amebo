from functools import wraps
from http import HTTPStatus
from inspect import iscoroutinefunction

from orjson import dumps, loads
from pydantic import BaseModel
from routerling import Context, HttpRequest, ResponseWriter



def expects(Model: BaseModel):
    def wrapper(func):
        async def delegate(req: HttpRequest, res: ResponseWriter, ctx: Context):
            appjson, ctype = 'application/json', 'content-type'
            res.headers = ctype, appjson
            if(req.headers.get(ctype) != appjson):
                res.status = HTTPStatus.UNPROCESSABLE_ENTITY
                res.body = dumps({'error': 'your request does not know json kung-fu'})
                return
            
            try:
                body = loads(req.body)
                model = Model(**body)
                mname = model.__class__.__name__.lower()
                ctx.keep(mname, model)
            except Exception as exc:
                print(exc)
                res.status = HTTPStatus.BAD_REQUEST
                res.body = dumps({'error': f'{exc}'})
                return

            if iscoroutinefunction(func): await func(req, res, ctx)
            else: func(req, res, ctx)
        return delegate
    return wrapper


def jsonify(func):
    @wraps(func)
    async def delegate(req, res, ctx):
        if(iscoroutinefunction(func)): await func(req, res, ctx)
        else: func(req, res, ctx)
        res.body = dumps(res.body)
    return delegate
