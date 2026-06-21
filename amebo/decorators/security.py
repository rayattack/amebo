import logging
from http import HTTPStatus
from inspect import iscoroutinefunction

from heaven import Context, Request, Response
from jwt import decode, encode

from amebo.constants.literals import AMEBO_SECRET

logger = logging.getLogger('amebo.auth')


async def authenticate(req: Request, res: Response, ctx: Context):
    sk = req.app.peek(AMEBO_SECRET)
    def leave():
        res.headers = 'Location', '/'
        return res.out(HTTPStatus.TEMPORARY_REDIRECT, None)

    # TODO: remove secret from ui and use withCredentials as we use the cookie to get it from the tokens cache
    #TODO: Change checking for secret in handlers to checking for producer name as authorization and identification is done here
    authentication = req.cookies.get('authentication')
    if not authentication: return leave()

    try: metadata = decode(authentication, sk, algorithms='HS256')
    except Exception: return leave()

    # keep metadata for use later in pages if required
    ctx.keep('metadata', metadata)


def protected(func):
    async def delegate(req: Request, res: Response, ctx: Context):
        sk = req.app.peek(AMEBO_SECRET)
        def leave():
            res.headers = 'Location', '/'
            return res.out(HTTPStatus.TEMPORARY_REDIRECT, None)

        # TODO: remove secret from ui and use withCredentials as we use the cookie to get it from the tokens cache
        #TODO: Change checking for secret in handlers to checking for producer name as authorization and identification is done here
        authentication = req.cookies.get('Authentication')
        if not authentication: return leave()

        try: metadata = decode(authentication, sk, algorithms='HS256')
        except Exception: return leave()

        # keep metadata for use later in pages if required
        ctx.keep('metadata', metadata)

        # nothing else to see here move on to next delegate or handler
        if iscoroutinefunction(func): return await func(req, res, ctx)
        else: return func(req, res, ctx)
    return delegate
