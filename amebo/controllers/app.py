from heaven import Context, Request, Response


async def pages(req: Request, res: Response, ctx: Context):
    page = req.params.get('page')
    if page not in ['actions', 'events', 'subscribers', 'producers', 'gists']:
        page = '404'
    return await res.render(f'{page}.html', req=req)


async def login(req: Request, res: Response, ctx: Context):
    return await res.render('login.html', req=req)
