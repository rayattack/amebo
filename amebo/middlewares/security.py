import logging
from os import environ
from sqlite3 import Connection

from bcrypt import gensalt, hashpw
from heaven import Application, Response

from amebo.constants.literals import AMEBO_SECRET

logger = logging.getLogger('amebo.security')


async def cors(req, res: Response, ctx):
    hx_req_headers = 'HX-Boosted, HX-Current-URL, HX-History-Restore-Request, HX-Prompt, HX-Request, HX-Target, HX-Trigger-Name, HX-Trigger'
    hx_res_headers = 'HX-Location, HX-Push-Url, HX-Redirect, HX-Refresh, HX-Replace-Url, HX-Reswap, HX-Retarget, HX-Reselect, HX-Trigger, HX-Trigger-After-Settle, HX-Trigger-After-Swap'
    common_headers = f'Accept, Content-Type, Content-Disposition, Authorization, Authentication, Vary, Date, Accept-Encoding, X-CSRF-Token, X-Hint, X-Hosted, Set-Cookie, X-Form-ID, X-Amebo-Signature, {hx_req_headers}'

    # API routes: signature-based auth, no cookies needed — allow any origin
    if req.url.startswith('/v1/') or req.url.startswith('/v8/'):
        res.headers = 'Access-Control-Allow-Origin', '*'
        res.headers = 'Access-Control-Allow-Headers', common_headers
        res.headers = 'Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        res.headers = 'Access-Control-Expose-Headers', 'X-Hint, X-Hosted, X-Other, X-Amebo-Signature'
    else:
        # UI routes: cookie-based auth, restrict to same-origin
        origin = req.headers.get('origin') or ''
        host = req.headers.get('host') or ''
        # only allow same-origin requests for cookie-authenticated UI routes
        if origin and host and origin.rstrip('/').endswith(host):
            res.headers = 'Access-Control-Allow-Origin', origin.rstrip('/')
        else:
            res.headers = 'Access-Control-Allow-Origin', f'{req.scheme}://{host}' if host else ''
        res.headers = 'Access-Control-Allow-Credentials', 'true'
        res.headers = 'Access-Control-Allow-Headers', common_headers
        res.headers = 'Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        res.headers = 'Access-Control-Expose-Headers', f'X-Hint, X-Hosted, X-Other, Set-Cookie, X-Form-ID, HX-History-Restore-Request, {hx_res_headers}'


async def upsudo(app: Application) -> str:
    db: Connection = app.peek('db')
    username = environ.get('AMEBO_USERNAME')
    pwd = environ.get('AMEBO_PASSWORD')
    password = hashpw(pwd.encode(), gensalt())

    # credentials table dropped every time so this is possible, what of producer credentials created after app start?
    # this has the potential to overwrite admin credentials if updated by admin after start? So document
    # to admins the need to set password from environmental variable and that that will always override and reset
    # everything else set afterwards
    try:
        if(app._.engine.startswith('postgres')):
            await db.execute(f'''
                INSERT INTO _amebo_.credentials(username, password) VALUES($1, $2)
                    ON CONFLICT(username) DO UPDATE SET password = EXCLUDED.password;
            ''', username, password.decode())
        else: db.execute('INSERT INTO credentials VALUES(?, ?);', (username, password.decode()))
    except Exception as exc:
        logger.error('SUDO credentials not created: %s', exc)


def upsecret(app: Application):
    secret = environ.get(AMEBO_SECRET)
    app.keep(AMEBO_SECRET, secret)
    logger.info('Amebo secret loaded')
