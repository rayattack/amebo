"""Delivery-recovery tests for the gists API, replay/requeue/backfill and metrics.

Runs against in-memory SQLite always. If AMEBO_DSN is set the same suite is run
against PostgreSQL too (so both backends are covered, per the project constraint).

These tests drive the real (decorated) controller handlers through a lightweight
fake request/response/context trinity + a real heaven-free Executor, and stub the
outbound HTTP client so replay/bulk-replay assert the written-back gist state.
"""
import os
import unittest
from asyncio import new_event_loop, set_event_loop
from datetime import datetime, timedelta
from sqlite3 import Connection

import jwt
from orjson import dumps, loads

import amebo.controllers.gists as gists
import amebo.controllers.metrics as metrics
from amebo.constants.scripts import initdbscript
from amebo.decorators.providers import Executor


SECRET = 'unit-test-secret'
NEW_COLUMNS = [
    'ALTER TABLE gists ADD COLUMN last_status_code integer',
    'ALTER TABLE gists ADD COLUMN last_error text',
    'ALTER TABLE gists ADD COLUMN last_attempted_at text',
    'ALTER TABLE gists ADD COLUMN dead_at text',
]


# --- fake heaven trinity -----------------------------------------------------

class _Ns: pass


class FakeApp:
    def __init__(self, db, engine='sqlite'):
        self._ = _Ns(); self._.engine = engine; self._.db = db
        self._store = {'AMEBO_SECRET': SECRET}
    def peek(self, key): return self._store.get(key)
    def CONFIG(self, key): return 256


class _Dict:
    def __init__(self, d): self.d = d or {}
    def get(self, k, default=None): return self.d.get(k, default)


class FakeReq:
    def __init__(self, app, queries=None, params=None, headers=None, cookies=None, body=None):
        self.app = app
        self.queries = _Dict(queries)
        self.params = _Dict(params)
        self.headers = _Dict(headers or {'content-type': 'application/json'})
        self.cookies = _Dict(cookies)
        self.body = body


class FakeRes:
    def __init__(self):
        self.status = None
        self._body = None
        self._headers = []
    @property
    def body(self): return self._body
    @body.setter
    def body(self, v): self._body = v
    @property
    def headers(self): return self._headers
    @headers.setter
    def headers(self, kv): self._headers.append(kv)
    def out(self, status, body):
        self.status = status; self._body = body; return self


class FakeCtx:
    def __init__(self, app):
        object.__setattr__(self, '_data', {})
        object.__setattr__(self, '_application', app)
    def keep(self, k, v): self._data[k] = v
    def __getattr__(self, k): return self._data.get(k)


# --- fake outbound HTTP client ----------------------------------------------

class FakeResp:
    def __init__(self, code, text=''): self.status_code = code; self.text = text


class FakeClient:
    code = 200
    text = ''
    calls = []
    def __init__(self, *a, **k): pass
    async def post(self, url, json=None, headers=None):
        FakeClient.calls.append({'url': url, 'json': json, 'headers': headers})
        return FakeResp(FakeClient.code, FakeClient.text)
    async def aclose(self): pass

    @classmethod
    def reset(cls, code=200, text=''):
        cls.code = code; cls.text = text; cls.calls = []


def _token():
    return jwt.encode({'username': 'admin', 'scheme': 'password'}, SECRET, algorithm='HS256')


def _auth_cookie():
    return {'Authentication': _token()}


class RecoveryTestBase:
    """Backend-agnostic test body. Subclasses set up self.db / self.engine."""

    # subclasses implement setUp to provide self.db, self.engine, self.executor, self.loop

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    def exec0(self, sql, *args):
        return self.run_async(self.executor.fetch(0).execute(sql, *args))

    def query(self, sql, *args):
        return self.run_async(self.executor.fetch(2).execute(sql, *args))

    def one(self, sql, *args):
        return self.run_async(self.executor.fetch(1).execute(sql, *args))

    # ---- seeding -----------------------------------------------------------

    def add_event(self, event, action, payload, ts, deduper=None):
        self.exec0("INSERT INTO events(event, action, deduper, payload, metadata, timestamped) VALUES (?,?,?,?,?,?)",
                   event, action, deduper or event, dumps(payload).decode(), '{}', ts)

    def add_subscription(self, sub, action='order.created', max_retries=3, handler=None):
        now = datetime.now().isoformat()
        handler = handler or f'http://sub/hook/{sub}'  # UNIQUE(application, action, handler)
        self.exec0("INSERT INTO subscriptions(subscription, application, action, max_retries, handler, timestamped) VALUES (?,?,?,?,?,?)",
                   sub, 'sub', action, max_retries, handler, now)

    def add_gist(self, event, subscription, completed, retries, ts):
        self.exec0("INSERT INTO gists(event, subscription, completed, acknowledged, retries, sleep_until, timestamped) VALUES (?,?,?,0,?,?,?)",
                   event, subscription, completed, retries, ts, ts)
        return self.one("SELECT max(rowid) FROM gists")[0]


# ----------------------------------------------------------------------------
# The actual tests
# ----------------------------------------------------------------------------

class SqliteRecoveryTest(RecoveryTestBase, unittest.TestCase):
    def setUp(self):
        self.loop = new_event_loop(); set_event_loop(self.loop)
        self.db = Connection(':memory:')
        self.db.executescript(initdbscript)
        for alter in NEW_COLUMNS:
            self.db.execute(alter)
        self.engine = 'sqlite'
        self.app = FakeApp(self.db, self.engine)
        self.executor = Executor(self.app)
        self._orig_client = gists.AsyncClient
        gists.AsyncClient = FakeClient
        FakeClient.reset()
        # seed: distinct subscriptions per state so UNIQUE(event, subscription) holds
        now = datetime.now().isoformat()
        self.exec0("INSERT INTO applications(application, address, secret, active, timestamped) VALUES (?,?,?,?,?)", 'pub', 'http://pub', 'pubsecret', 1, now)
        self.exec0("INSERT INTO applications(application, address, secret, active, timestamped) VALUES (?,?,?,?,?)", 'sub', 'http://sub', 'subsecret', 1, now)
        self.exec0("INSERT INTO actions(action, application, schemata, timestamped) VALUES (?,?,?,?)", 'order.created', 'pub', '{}', now)
        self.add_event('evt-1', 'order.created', {'id': 1}, now)
        self.add_subscription('s-deliv'); self.delivered_id = self.add_gist('evt-1', 's-deliv', 1, 1, now)
        self.add_subscription('s-failed'); self.failed_id = self.add_gist('evt-1', 's-failed', 0, 3, now)
        self.add_subscription('s-retry'); self.retry_id = self.add_gist('evt-1', 's-retry', 0, 1, now)
        self.add_subscription('s-pend'); self.pending_id = self.add_gist('evt-1', 's-pend', 0, 0, now)

    def tearDown(self):
        gists.AsyncClient = self._orig_client
        self.db.close()
        self.loop.close()

    # -- helpers to call handlers --

    def call(self, handler, queries=None, params=None, body=None, auth=True):
        req = FakeReq(self.app, queries=queries, params=params,
                      cookies=_auth_cookie() if auth else None,
                      body=dumps(body) if body is not None else None)
        res = FakeRes(); ctx = FakeCtx(self.app)
        self.run_async(handler(req, res, ctx))
        body_out = res.body
        if isinstance(body_out, (bytes, bytearray)):
            body_out = loads(body_out)
        return res.status, body_out

    # -- tests --

    def test_list_envelope_and_total(self):
        status, body = self.call(gists.tabulate)
        self.assertEqual(int(status), 200)
        self.assertIn('data', body); self.assertIn('total', body)
        self.assertEqual(body['total'], 4)
        self.assertEqual(len(body['data']), 4)

    def test_status_filter_failed(self):
        status, body = self.call(gists.tabulate, queries={'status': 'failed'})
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['data'][0]['status'], 'failed')
        self.assertEqual(str(body['data'][0]['id']), str(self.failed_id))

    def test_status_filter_distinguishes_retrying_and_pending(self):
        _, retrying = self.call(gists.tabulate, queries={'status': 'retrying'})
        _, pending = self.call(gists.tabulate, queries={'status': 'pending'})
        self.assertEqual(retrying['total'], 1)
        self.assertEqual(pending['total'], 1)
        self.assertEqual(retrying['data'][0]['status'], 'retrying')
        self.assertEqual(pending['data'][0]['status'], 'pending')

    def test_publisher_subscriber_action_filters_do_not_crash(self):
        # the previously-broken filters (e.producer / a.event / p.name)
        s1, b1 = self.call(gists.tabulate, queries={'origin': 'pub'})
        s2, b2 = self.call(gists.tabulate, queries={'destination': 'sub'})
        s3, b3 = self.call(gists.tabulate, queries={'action': 'order'})
        self.assertEqual(int(s1), 200); self.assertEqual(int(s2), 200); self.assertEqual(int(s3), 200)
        self.assertEqual(b1['total'], 4)   # all four belong to publisher 'pub'
        self.assertEqual(b3['total'], 4)

    def test_single_replay_success_is_stateful(self):
        FakeClient.reset(code=200)
        status, body = self.call(gists.replay, params={'id': self.failed_id})
        self.assertTrue(body['delivered'])
        row = self.one("SELECT completed, retries, last_status_code, last_attempted_at FROM gists WHERE rowid = ?", self.failed_id)
        self.assertEqual(row[0], 1)              # completed
        self.assertEqual(row[1], 4)              # retries incremented 3 -> 4
        self.assertEqual(row[2], 200)            # last_status_code
        self.assertIsNotNone(row[3])             # last_attempted_at recorded

    def test_single_replay_failure_records_error(self):
        FakeClient.reset(code=500, text='boom')
        status, body = self.call(gists.replay, params={'id': self.failed_id})
        self.assertFalse(body['delivered'])
        row = self.one("SELECT completed, last_status_code, last_error FROM gists WHERE rowid = ?", self.failed_id)
        self.assertEqual(row[0], 0)              # still not delivered
        self.assertEqual(row[1], 500)
        self.assertEqual(row[2], 'boom')

    def test_replay_requires_auth(self):
        status, body = self.call(gists.replay, params={'id': self.failed_id}, auth=False)
        self.assertNotEqual(int(status), 200)    # protected -> redirect, not a delivery

    def test_bulk_replay_chronological_order(self):
        # three failed gists for events at t1<t2<t3, inserted newest-first
        base = datetime(2026, 1, 1, 12, 0, 0)
        self.add_subscription('s-bulk', action='order.created')
        t3 = (base + timedelta(minutes=2)).isoformat()
        t2 = (base + timedelta(minutes=1)).isoformat()
        t1 = base.isoformat()
        self.add_event('e-t3', 'order.bulk', {'n': 3}, t3)
        self.add_event('e-t2', 'order.bulk', {'n': 2}, t2)
        self.add_event('e-t1', 'order.bulk', {'n': 1}, t1)
        # action must exist for the join
        self.exec0("INSERT INTO actions(action, application, schemata, timestamped) VALUES (?,?,?,?)", 'order.bulk', 'pub', '{}', t1)
        self.add_subscription('s-bulk2', action='order.bulk')
        self.add_gist('e-t3', 's-bulk2', 0, 3, t3)
        self.add_gist('e-t2', 's-bulk2', 0, 3, t2)
        self.add_gist('e-t1', 's-bulk2', 0, 3, t1)
        FakeClient.reset(code=200)
        status, body = self.call(gists.bulk_replay, queries={'action': 'order.bulk', 'status': 'failed'})
        self.assertEqual(body['total'], 3)
        self.assertEqual(body['succeeded'], 3)
        delivered_order = [c['json']['payload']['n'] for c in FakeClient.calls]
        self.assertEqual(delivered_order, [1, 2, 3])   # oldest -> newest

    def test_bulk_dry_run_counts(self):
        status, body = self.call(gists.time_travel, queries={'status': 'failed'})
        self.assertTrue(body['dry_run'])
        self.assertEqual(body['count'], 1)

    def test_requeue_clears_exhaustion(self):
        status, body = self.call(gists.requeue, queries={'gist': self.failed_id})
        self.assertEqual(body['requeued'], 1)
        row = self.one("SELECT completed, retries, last_error, sleep_until FROM gists WHERE rowid = ?", self.failed_id)
        self.assertEqual(row[0], 0); self.assertEqual(row[1], 0)
        self.assertIsNone(row[2])                 # last_error cleared
        self.assertIsNotNone(row[3])              # sleep_until set
        # daemon pick predicate now includes it again
        pick = self.query("""SELECT g.rowid FROM gists g JOIN subscriptions s ON g.subscription = s.subscription
            WHERE g.completed <> 1 AND g.retries < s.max_retries AND g.rowid = ?""", self.failed_id)
        self.assertEqual(len(pick), 1)

    def test_backfill_creates_missing_gists(self):
        # an event for order.created that has NO gist for subscription sub-1
        self.add_subscription('sub-1', action='order.created')
        now = datetime.now().isoformat()
        self.add_event('evt-bf', 'order.created', {'id': 99}, now)
        # dry run
        _, dry = self.call(gists.backfill, body={'subscription': 'sub-1', 'dry_run': True})
        self.assertTrue(dry['dry_run'])
        self.assertGreaterEqual(dry['count'], 2)  # evt-1 + evt-bf
        # real backfill
        _, body = self.call(gists.backfill, body={'subscription': 'sub-1'})
        created = self.one("SELECT completed, retries FROM gists WHERE event = ? AND subscription = ?", 'evt-bf', 'sub-1')
        self.assertIsNotNone(created)
        self.assertEqual(created[0], 0); self.assertEqual(created[1], 0)

    def test_metrics_deliveries_counts(self):
        status, body = self.call(metrics.deliveries, queries={'window': 'all'})
        self.assertEqual(body['delivered'], 1)
        self.assertEqual(body['failed'], 1)
        self.assertEqual(body['retrying'], 1)
        self.assertEqual(body['pending'], 1)
        self.assertEqual(body['success_rate'], 50.0)
        self.assertEqual(body['published'], 1)    # one event seeded

    def test_metrics_subscriptions_reports_failures(self):
        # give the failed sub a recorded error so it surfaces
        self.exec0("UPDATE gists SET last_error = 'kaboom', last_attempted_at = ? WHERE rowid = ?", datetime.now().isoformat(), self.failed_id)
        status, body = self.call(metrics.subscriptions)
        by_sub = {r['subscription']: r for r in body['data']}
        self.assertEqual(by_sub['s-failed']['failed'], 1)
        self.assertEqual(by_sub['s-failed']['last_error'], 'kaboom')
        self.assertEqual(by_sub['s-deliv']['delivered'], 1)

    def test_writeback_helper_records_both_outcomes(self):
        at = datetime.now().isoformat()
        self.run_async(gists.writeback_attempt(self.executor, self.pending_id, True, 201, None, at))
        row = self.one("SELECT completed, last_status_code FROM gists WHERE rowid = ?", self.pending_id)
        self.assertEqual(row[0], 1); self.assertEqual(row[1], 201)
        self.run_async(gists.writeback_attempt(self.executor, self.retry_id, False, 503, 'down', at))
        row = self.one("SELECT completed, last_status_code, last_error FROM gists WHERE rowid = ?", self.retry_id)
        self.assertEqual(row[0], 0); self.assertEqual(row[1], 503); self.assertEqual(row[2], 'down')

    # ---- P2: exponential backoff + dead-letter ----

    def test_backoff_seconds_grows_and_caps(self):
        from amebo.utils.helpers import backoff_seconds, BACKOFF_CAP_SECONDS
        self.assertEqual(backoff_seconds(1), 10)
        self.assertEqual(backoff_seconds(2), 20)
        self.assertEqual(backoff_seconds(3), 40)
        self.assertEqual(backoff_seconds(100), BACKOFF_CAP_SECONDS)   # capped

    def test_failed_attempt_schedules_backoff(self):
        # a retrying gist (retries=1, max=3): a failed replay backs off, does NOT die
        FakeClient.reset(code=500, text='nope')
        before = datetime.now()
        self.call(gists.replay, params={'id': self.retry_id})
        row = self.one("SELECT retries, dead_at, sleep_until FROM gists WHERE rowid = ?", self.retry_id)
        self.assertEqual(row[0], 2)                 # incremented
        self.assertIsNone(row[1])                   # not dead yet
        self.assertIsNotNone(row[2])                # next attempt scheduled
        nxt = datetime.fromisoformat(row[2])
        self.assertGreater(nxt, before)             # scheduled in the future (backoff)

    def test_exhaustion_dead_letters(self):
        # gist at retries=2, max=3: one more failure exhausts -> dead_at set
        self.add_subscription('s-dl')
        gid = self.add_gist('evt-1', 's-dl', 0, 2, datetime.now().isoformat())
        FakeClient.reset(code=500, text='still down')
        self.call(gists.replay, params={'id': gid})
        row = self.one("SELECT retries, dead_at FROM gists WHERE rowid = ?", gid)
        self.assertEqual(row[0], 3)
        self.assertIsNotNone(row[1])                # dead-lettered
        # and it now reports as failed via the status filter
        _, failed = self.call(gists.tabulate, queries={'status': 'failed'})
        self.assertIn(str(gid), [r['id'] for r in failed['data']])

    def test_status_failed_via_dead_at_even_with_retries_left(self):
        # terminal: a dead_at row is 'failed' even if retries < max_retries
        self.exec0("UPDATE gists SET dead_at = ? WHERE rowid = ?", datetime.now().isoformat(), self.pending_id)
        _, body = self.call(gists.tabulate, queries={'gist': str(self.pending_id)})
        self.assertEqual(body['data'][0]['status'], 'failed')
        self.assertIsNotNone(body['data'][0]['dead_at'])

    def test_requeue_clears_dead_at(self):
        self.exec0("UPDATE gists SET dead_at = ? WHERE rowid = ?", datetime.now().isoformat(), self.failed_id)
        self.call(gists.requeue, queries={'gist': self.failed_id})
        row = self.one("SELECT dead_at, retries, completed FROM gists WHERE rowid = ?", self.failed_id)
        self.assertIsNone(row[0]); self.assertEqual(row[1], 0); self.assertEqual(row[2], 0)


PG_DSN = os.environ.get('AMEBO_TEST_DSN')


@unittest.skipUnless(PG_DSN, 'set AMEBO_TEST_DSN to run the PostgreSQL variant')
class PostgresRecoveryTest(unittest.TestCase):
    """Same recovery behaviours, exercised against a real PostgreSQL instance so the
    `$n` placeholders, uuid/int casts and `::timestamptz` paths are all validated."""

    def setUp(self):
        from asyncpg import create_pool
        from amebo.database.pg import pgscript
        self.loop = new_event_loop(); set_event_loop(self.loop)

        async def boot():
            pool = await create_pool(PG_DSN)
            async with pool.acquire() as c:
                await c.execute('DROP SCHEMA IF EXISTS _amebo_ CASCADE;')
                await c.execute(pgscript)
            return pool
        self.pool = self.loop.run_until_complete(boot())
        self.app = FakeApp(self.pool, 'postgres')
        self.executor = Executor(self.app)
        self._orig_client = gists.AsyncClient
        gists.AsyncClient = FakeClient
        FakeClient.reset()
        self.ids = self.loop.run_until_complete(self._seed())

    def tearDown(self):
        gists.AsyncClient = self._orig_client
        self.loop.run_until_complete(self.pool.close())
        self.loop.close()

    async def _exec(self, sql, *args):
        async with self.pool.acquire() as c: return await c.execute(sql, *args)

    async def _row(self, sql, *args):
        async with self.pool.acquire() as c: return await c.fetchrow(sql, *args)

    async def _seed(self):
        dt = datetime.now()
        now = dt.isoformat()
        await self._exec("INSERT INTO _amebo_.applications(application,address,secret,active,timestamped) VALUES ($1,$2,$3,$4,$5)", 'pub', 'http://pub', 'pubsecret', 1, now)
        await self._exec("INSERT INTO _amebo_.applications(application,address,secret,active,timestamped) VALUES ($1,$2,$3,$4,$5)", 'sub', 'http://sub', 'subsecret', 1, now)
        await self._exec("INSERT INTO _amebo_.actions(action,application,schemata,timestamped) VALUES ($1,$2,$3,$4)", 'order.created', 'pub', '{}', now)
        evt = await self._row("INSERT INTO _amebo_.events(action,deduper,payload,metadata,timestamped) VALUES ($1,$2,$3,$4,$5) RETURNING event", 'order.created', 'd1', dumps({'id': 1}).decode(), '{}', now)
        event = evt[0]
        ids = {}
        states = [('s-deliv', 1, 1, 'delivered'), ('s-failed', 0, 3, 'failed'), ('s-retry', 0, 1, 'retrying'), ('s-pend', 0, 0, 'pending')]
        for name, completed, retries, label in states:
            sub = await self._row("INSERT INTO _amebo_.subscriptions(application,action,max_retries,handler,timestamped) VALUES ($1,$2,$3,$4,$5) RETURNING subscription", 'sub', 'order.created', 3, f'http://sub/{name}', now)
            g = await self._row("INSERT INTO _amebo_.gists(event,subscription,completed,retries,sleep_until,timestamped) VALUES ($1,$2,$3,$4,$5,$6) RETURNING rowid", event, sub[0], completed, retries, dt, now)
            ids[label] = g[0]
        ids['event'] = event
        return ids

    def call(self, handler, queries=None, params=None, body=None, auth=True):
        req = FakeReq(self.app, queries=queries, params=params,
                      cookies=_auth_cookie() if auth else None,
                      body=dumps(body) if body is not None else None)
        res = FakeRes(); ctx = FakeCtx(self.app)
        self.loop.run_until_complete(handler(req, res, ctx))
        out = res.body
        if isinstance(out, (bytes, bytearray)): out = loads(out)
        return res.status, out

    def test_list_and_status_filter(self):
        _, body = self.call(gists.tabulate)
        self.assertEqual(body['total'], 4)
        _, failed = self.call(gists.tabulate, queries={'status': 'failed'})
        self.assertEqual(failed['total'], 1)
        self.assertEqual(failed['data'][0]['status'], 'failed')

    def test_single_replay_stateful(self):
        FakeClient.reset(code=200)
        _, body = self.call(gists.replay, params={'id': str(self.ids['failed'])})
        self.assertTrue(body['delivered'])
        row = self.loop.run_until_complete(self._row("SELECT completed,last_status_code,last_attempted_at FROM _amebo_.gists WHERE rowid=$1", self.ids['failed']))
        self.assertEqual(row[0], 1); self.assertEqual(row[1], 200); self.assertIsNotNone(row[2])

    def test_replay_failure_records_error(self):
        FakeClient.reset(code=500, text='boom')
        _, body = self.call(gists.replay, params={'id': str(self.ids['failed'])})
        self.assertFalse(body['delivered'])
        row = self.loop.run_until_complete(self._row("SELECT completed,last_status_code,last_error FROM _amebo_.gists WHERE rowid=$1", self.ids['failed']))
        self.assertEqual(row[0], 0); self.assertEqual(row[1], 500); self.assertEqual(row[2], 'boom')

    def test_requeue_clears_exhaustion(self):
        _, body = self.call(gists.requeue, queries={'gist': str(self.ids['failed'])})
        self.assertEqual(body['requeued'], 1)
        row = self.loop.run_until_complete(self._row("SELECT completed,retries,last_error FROM _amebo_.gists WHERE rowid=$1", self.ids['failed']))
        self.assertEqual(row[0], 0); self.assertEqual(row[1], 0); self.assertIsNone(row[2])

    def test_backfill_creates_gists(self):
        # subscription with action order.created; a new event with no gist for it
        sub = self.loop.run_until_complete(self._row("SELECT subscription FROM _amebo_.subscriptions WHERE handler=$1", 'http://sub/s-pend'))
        subid = str(sub[0])
        now = datetime.now().isoformat()
        self.loop.run_until_complete(self._exec("INSERT INTO _amebo_.events(action,deduper,payload,metadata,timestamped) VALUES ($1,$2,$3,$4,$5)", 'order.created', 'd2', dumps({'id': 2}).decode(), '{}', now))
        _, dry = self.call(gists.backfill, body={'subscription': subid, 'dry_run': True})
        self.assertGreaterEqual(dry['count'], 2)
        _, body = self.call(gists.backfill, body={'subscription': subid})
        cnt = self.loop.run_until_complete(self._row("SELECT COUNT(*) FROM _amebo_.gists WHERE subscription=$1::uuid", subid))
        self.assertGreaterEqual(cnt[0], 2)

    def test_metrics(self):
        _, body = self.call(metrics.deliveries, queries={'window': 'all'})
        self.assertEqual(body['delivered'], 1); self.assertEqual(body['failed'], 1)
        self.assertEqual(body['success_rate'], 50.0)
        _, subs = self.call(metrics.subscriptions)
        self.assertTrue(any(r['failed'] == 1 for r in subs['data']))

    def test_dead_letter_and_backoff(self):
        # retrying gist (retries=1) failing -> backs off (timestamptz), not dead
        FakeClient.reset(code=500, text='x')
        self.call(gists.replay, params={'id': str(self.ids['retrying'])})
        row = self.loop.run_until_complete(self._row("SELECT retries, dead_at, sleep_until FROM _amebo_.gists WHERE rowid=$1", self.ids['retrying']))
        self.assertEqual(row[0], 2); self.assertIsNone(row[1]); self.assertIsNotNone(row[2])
        # exhausted gist (retries=3, max=3) failing -> dead-lettered
        self.call(gists.replay, params={'id': str(self.ids['failed'])})
        dead = self.loop.run_until_complete(self._row("SELECT dead_at FROM _amebo_.gists WHERE rowid=$1", self.ids['failed']))
        self.assertIsNotNone(dead[0])


if __name__ == '__main__':
    unittest.main()
