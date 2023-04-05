from datetime import datetime, timedelta
from functools import wraps
from os import path, getcwd

from jinja2 import (
    Environment,
    # PackageLoader,
    FileSystemLoader,
    select_autoescape
)
from routerling import HttpRequest, ResponseWriter, Context

from constants import DEFAULT_PAGINATION


autoescape = select_autoescape(['axml', 'htm', 'html'])
loader = FileSystemLoader('./templates')
environment = Environment(loader=loader, autoescape=autoescape)
environment.is_async = True


def _set_content_type(r: HttpRequest, w: ResponseWriter):
    ct = 'Content-Type'
    if(r.url.endswith('.css')): w.headers = ct, 'text/css'
    elif(r.url.endswith('.svg')): w.headers = ct, 'image/svg+xml'


def get_pagination(req: HttpRequest):
    try: page = int(req.params.get('page'))
    except: page = 1
    else: page = 1 if page < 0 else page

    try: pagination = int(req.params.get('pagination'))
    except: pagination = DEFAULT_PAGINATION
    else: pagination = DEFAULT_PAGINATION if pagination < 0 else pagination
    return page, pagination


def get_params(params: list, req: HttpRequest):
    return [req.params.get(p) for p in params]


def get_timeline(timeline, step_or_filter, column: str = None):
    if timeline:
        dateline = datetime.now()
        value = timeline.lower()
        if value == 'month':
            dateline = dateline - timedelta(days=31)
        elif value == 'week':
            dateline = dateline - timedelta(days=7)
        elif value == 'today':
            dateline = dateline - timedelta(hours=24)

        adjunction = 'AND' if step_or_filter.dirty else 'WHERE'
        return f"{adjunction} {column or 'timestamped'} > DATETIME('{dateline.isoformat()}')"
    return ''

def html(func):
    @wraps(func)
    async def delegate(req: HttpRequest, res, ctx):
        page = req.url[1:]
        ctx.keep('appjson', {'Content-Type': 'application/json'})
        res.body = await render(f'{page}.html', context={'req': req, 'ctx': ctx})
        await func(req, res, ctx)
    return delegate


def serve_public_assets(r: HttpRequest, w: ResponseWriter, c: Context):
    """
    Serve css and svg files

    NOTE: This might be improvable to be a streaming response handler i.e. whilst lines streamline
    back to client.
    """
    asset = f"public/{r.params.get('*', '')}"
    location = path.realpath(path.join(getcwd(), path.dirname(__file__)))
    target = path.join(location, asset)
    with open(target, 'rb') as opened:
        _set_content_type(r, w)
        w.body = b''.join(opened.readlines())
        return


async def render(template: str, context={}):
    """
    Return rendered html of template with context interpolated in

    template: name of template file in /templates folder to be rendered
    context: key-value pair to use for replacement in templatea using jinja templating
    """
    return await environment.get_template(template).render_async(context)
