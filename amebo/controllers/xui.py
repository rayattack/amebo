from heaven import Context, Request, Response

from amebo import __version__
from amebo.decorators.security import protected


@protected
async def pages(req: Request, res: Response, ctx: Context):
    page = req.params.get('page')
    if page not in ['dashboard', 'actions', 'events', 'subscriptions', 'applications', 'gists', 'redactions']:
        page = '404'
    ctx.keep('amebo_version', __version__)  # TODO: deprecate in favor of req.app._.version
    return await res.render(f'{page}.html', req=req)


async def login(req: Request, res: Response, ctx: Context):
    return await res.render('login.html', req=req)


async def windows(req: Request, res: Response, ctx: Context):
    page = req.params.get('page')
    if page not in ['dashboard', 'actions', 'events', 'subscriptions', 'applications', 'gists', 'redactions']:
        page = '404'
    return await res.render(f'windows/{page}.html', req=req)
