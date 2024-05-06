from http import HTTPStatus
from inspect import iscoroutinefunction

from heaven import Context, Request, Response


def authenticated(func):
    async def delegate(req: Request, res: Response, ctx: Context):
        cookie = req.cookies.get('Authorization')
        if not cookie:
            print(req.headers)
            print(req.cookies)
            res.status = HTTPStatus.TEMPORARY_REDIRECT
            res.headers = 'Location', '/'
            return

        if iscoroutinefunction(func): return await func(req, res, ctx)
        else: return func(req, res, ctx)
    return delegate
