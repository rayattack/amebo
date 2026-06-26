"""Shared test harness: a lightweight, heaven-free stand-in for the request/
response/context trinity, an in-memory SQLite database matching the production
schema, the outbound-HTTP stub, and seed helpers.

New test modules build on this instead of re-deriving the fakes. It mirrors the
inline fakes in tests/test_recovery.py so behaviour is identical across the suite.

Typical use:

    from tests.harness import SqliteHarness, decode_body, auth_cookie
    import amebo.controllers.applications as applications

    class MyTest(unittest.TestCase):
        def setUp(self): self.h = SqliteHarness()
        def tearDown(self): self.h.close()

        def test_list(self):
            self.h.add_application('orders')
            res = self.h.call(applications.tabulate)
            self.assertEqual(res.status, HTTPStatus.OK)
            self.assertEqual(decode_body(res)[0]['application'], 'orders')
"""
from asyncio import new_event_loop, set_event_loop
from datetime import datetime
from sqlite3 import Connection

import jwt
from bcrypt import gensalt, hashpw
from orjson import dumps, loads

from amebo.constants.scripts import initdbscript
from amebo.decorators.providers import Executor
from amebo.utils.helpers import datasigner


SECRET = 'unit-test-secret'

# Columns the runtime adds via ALTER ... ADD COLUMN at startup (middlewares.database
# .initialize); the base schema script predates them, so apply them here too.
NEW_COLUMNS = [
    'ALTER TABLE gists ADD COLUMN last_status_code integer',
    'ALTER TABLE gists ADD COLUMN last_error text',
    'ALTER TABLE gists ADD COLUMN last_attempted_at text',
    'ALTER TABLE gists ADD COLUMN dead_at text',
]


# --- fake heaven trinity -----------------------------------------------------

class _Ns:
    pass


class FakeApp:
    def __init__(self, db, engine='sqlite', secret=SECRET, config=None):
        self._ = _Ns()
        self._.engine = engine
        self._.db = db
        self._store = {'AMEBO_SECRET': secret}
        self._config = {'envelope_size': 256, 'idles': 0}
        if config:
            self._config.update(config)

    def peek(self, key):
        return self._store.get(key)

    def keep(self, key, value):
        self._store[key] = value

    def CONFIG(self, key):
        return self._config.get(key, 256)


class _Dict:
    def __init__(self, d):
        self.d = d or {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def __contains__(self, k):
        return k in self.d


class FakeReq:
    def __init__(self, app, queries=None, params=None, headers=None, cookies=None, body=None,
                 method='GET', url='/', ip='127.0.0.1'):
        self.app = app
        self.queries = _Dict(queries)
        self.params = _Dict(params)
        self.headers = _Dict(headers if headers is not None else {'content-type': 'application/json'})
        self.cookies = _Dict(cookies)
        self.body = body
        self.method = method
        self.url = url
        self.ip = ip


class FakeRes:
    def __init__(self):
        self.status = None
        self._body = None
        self._headers = []

    @property
    def body(self):
        return self._body

    @body.setter
    def body(self, v):
        self._body = v

    @property
    def headers(self):
        return self._headers

    @headers.setter
    def headers(self, kv):
        self._headers.append(kv)

    def out(self, status, body):
        self.status = status
        self._body = body
        return self


class FakeCtx:
    def __init__(self, app):
        object.__setattr__(self, '_data', {})
        object.__setattr__(self, '_application', app)

    def keep(self, k, v):
        self._data[k] = v

    def __getattr__(self, k):
        return self._data.get(k)


# --- fake outbound HTTP client ----------------------------------------------

class FakeResp:
    def __init__(self, code, text=''):
        self.status_code = code
        self.text = text


class FakeClient:
    code = 200
    text = ''
    calls = []

    def __init__(self, *a, **k):
        pass

    async def post(self, url, json=None, headers=None):
        FakeClient.calls.append({'url': url, 'json': json, 'headers': headers})
        return FakeResp(FakeClient.code, FakeClient.text)

    async def aclose(self):
        pass

    @classmethod
    def reset(cls, code=200, text=''):
        cls.code = code
        cls.text = text
        cls.calls = []


# --- helpers -----------------------------------------------------------------

def decode_body(res):
    """The body after `@jsonify` is orjson bytes — decode it back to a Python value."""
    b = res.body
    if isinstance(b, (bytes, bytearray, str)):
        try:
            return loads(b)
        except Exception:
            return b
    return b


def admin_token(secret=SECRET, username='admin', scheme='password'):
    return jwt.encode({'username': username, 'scheme': scheme}, secret, algorithm='HS256')


def auth_cookie(secret=SECRET):
    return {'Authentication': admin_token(secret)}


def sign(payload, secret):
    """HMAC signature over the canonical body, matching datasigner (legacy scheme)."""
    return datasigner(payload, secret)


def make_sqlite_db():
    db = Connection(':memory:')
    db.executescript(initdbscript)
    for alter in NEW_COLUMNS:
        db.execute(alter)
    return db


class SqliteHarness:
    """An in-memory SQLite database + Executor + fake app, with seed helpers and a
    `call()` that drives a decorated controller handler end to end."""

    def __init__(self, secret=SECRET, config=None):
        self.loop = new_event_loop()
        set_event_loop(self.loop)
        self.db = make_sqlite_db()
        self.engine = 'sqlite'
        self.app = FakeApp(self.db, self.engine, secret=secret, config=config)
        self.executor = Executor(self.app)

    # ---- lifecycle ----------------------------------------------------------

    def close(self):
        try:
            self.db.close()
        finally:
            self.loop.close()

    # ---- raw access ---------------------------------------------------------

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def exec0(self, sql, *args):
        return self.run(self.executor.fetch(0).execute(sql, *args))

    def one(self, sql, *args):
        return self.run(self.executor.fetch(1).execute(sql, *args))

    def query(self, sql, *args):
        return self.run(self.executor.fetch(2).execute(sql, *args))

    # ---- seeding ------------------------------------------------------------

    def add_credential(self, username='admin', password='admin-pass'):
        pw = hashpw(password.encode(), gensalt()).decode()
        self.exec0("INSERT INTO credentials(username, password) VALUES (?,?)", username, pw)
        return password

    def add_application(self, application, address='https://app.example.com',
                        secret='application-secret-key', active=1, apikey=None):
        now = datetime.now().isoformat()
        self.exec0(
            "INSERT INTO applications(application, address, secret, apikey, active, timestamped) VALUES (?,?,?,?,?,?)",
            application, address, secret, apikey, active, now)
        return secret

    def add_action(self, action, application, schemata='{}', status='active',
                   compatibility='BACKWARD', successor=None, family=None):
        now = datetime.now().isoformat()
        self.exec0(
            "INSERT INTO actions(action, application, schemata, family, status, successor, compatibility, timestamped) "
            "VALUES (?,?,?,?,?,?,?,?)",
            action, application, schemata, family, status, successor, compatibility, now)

    def add_event(self, event, action, payload, deduper=None, metadata=None, ts=None):
        ts = ts or datetime.now().isoformat()
        meta = dumps(metadata).decode() if metadata is not None else '{}'
        self.exec0(
            "INSERT INTO events(event, action, deduper, payload, metadata, timestamped) VALUES (?,?,?,?,?,?)",
            event, action, deduper or event, dumps(payload).decode(), meta, ts)

    def add_subscription(self, subscription, application, action, handler,
                         max_retries=3, active=1, description=None, ts=None):
        ts = ts or datetime.now().isoformat()
        self.exec0(
            "INSERT INTO subscriptions(subscription, application, action, max_retries, handler, description, active, timestamped) "
            "VALUES (?,?,?,?,?,?,?,?)",
            subscription, application, action, max_retries, handler, description, active, ts)

    def add_gist(self, event, subscription, completed=0, retries=0, sleep_until=None, ts=None):
        ts = ts or datetime.now().isoformat()
        self.exec0(
            "INSERT INTO gists(event, subscription, completed, acknowledged, retries, sleep_until, timestamped) "
            "VALUES (?,?,?,0,?,?,?)",
            event, subscription, completed, retries, sleep_until or ts, ts)
        return self.one("SELECT max(rowid) FROM gists")[0]

    def add_redaction(self, action, field_path, ts=None):
        ts = ts or datetime.now().isoformat()
        self.exec0("INSERT INTO redactions(action, field_path, timestamped) VALUES (?,?,?)", action, field_path, ts)

    # ---- driving handlers ---------------------------------------------------

    def call(self, handler, queries=None, params=None, headers=None, cookies=None, body=None):
        """Invoke a decorated controller handler. `body` may be a dict/list (encoded
        to JSON bytes) or raw bytes/str. Returns the FakeRes; use decode_body(res)."""
        merged_headers = {'content-type': 'application/json'}
        if headers:
            merged_headers.update(headers)
        if isinstance(body, (dict, list)):
            body = dumps(body)
        req = FakeReq(self.app, queries=queries, params=params,
                      headers=merged_headers, cookies=cookies, body=body)
        res = FakeRes()
        ctx = FakeCtx(self.app)
        self.run(handler(req, res, ctx))
        return res
