from http import HTTPStatus
from inspect import iscoroutinefunction

from heaven import Context, Request, Response
from jwt import decode, encode

from amebo.constants.literals import AMEBO_SECRET_KEY


async def authenticate(req: Request, res: Response, ctx: Context):
    sk = req.app.CONFIG(AMEBO_SECRET_KEY)
    def leave():
        res.headers = 'Location', '/'
        return res.out(HTTPStatus.TEMPORARY_REDIRECT, None)

    # TODO: remove passphrase from ui and use withCredentials as we use the cookie to get it from the tokens cache
    #TODO: Change checking for passphrase in handlers to checking for producer name as authorization and identification is done here
    authentication = req.cookies.get('authentication')
    if not authentication: return leave()

    try: metadata = decode(authentication, sk, algorithms='HS256')
    except: return leave()

    # keep metadata for use later in pages if required
    ctx.keep('metadata', metadata)


def authorization(func):
    async def delegate(req: Request, res: Response, ctx: Context):
        sk = req.app.CONFIG(AMEBO_SECRET_KEY)
        authorization = req.headers.get('authorization')
        authentication = req.cookies.get('Authentication')

        if not authorization or authentication: return res.out(HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS, {'error': 'No credentials provided'})
        if iscoroutinefunction(func): return await func(req, res, ctx)

        try:
            if authorization: _, token = authorization.split(' ', 1)
            else: token = authentication
        except: return res.out(HTTPStatus.BAD_REQUEST, {'error': 'Could not process your credentials'})

        try: metadata = decode(token, sk, algorithms='HS256')
        except: return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Invalid credentials detected'})

        # user producer name to use for token lookup from global app state
        producer = metadata.get('producer')
        token = req.app._.tokens._data.get(producer)
        if not token: return res.out(HTTPStatus.UNAUTHORIZED, {'error': 'Application credentials cache cleared at app startup'})

        ctx.keep('token', token)
        return func(req, res, ctx)
    return delegate


def protected(func):
    async def delegate(req: Request, res: Response, ctx: Context):
        sk = req.app.CONFIG(AMEBO_SECRET_KEY)
        def leave():
            res.headers = 'Location', '/'
            return res.out(HTTPStatus.TEMPORARY_REDIRECT, None)

        # TODO: remove passphrase from ui and use withCredentials as we use the cookie to get it from the tokens cache
        #TODO: Change checking for passphrase in handlers to checking for producer name as authorization and identification is done here
        authentication = req.cookies.get('authentication')
        if not authentication: return leave()

        try: metadata = decode(authentication, sk, algorithms='HS256')
        except: return leave()

        # keep metadata for use later in pages if required
        ctx.keep('metadata', metadata)

        # nothing else to see here move on to next delegate or handler
        if iscoroutinefunction(func): return await func(req, res, ctx)
        else: return func(req, res, ctx)
    return delegate
