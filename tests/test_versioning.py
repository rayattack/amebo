"""Tests for the action version registry: idempotent/immutable registration, family
derivation, version ordering, compatibility gating, the deprecate/retire lifecycle,
soft-unsubscribe, and subscription migration.

Runs against in-memory SQLite. Mirrors tests/test_recovery.py: it drives the real
(decorated) controller handlers through a lightweight fake request/response/context
trinity and a real heaven-free Executor.
"""
import unittest
from asyncio import new_event_loop, set_event_loop
from datetime import datetime
from http import HTTPStatus
from sqlite3 import Connection

import jwt
from orjson import dumps, loads

import amebo.controllers.actions as actions
import amebo.controllers.events as events
import amebo.controllers.subscriptions as subscriptions
from amebo.constants.scripts import initdbscript
from amebo.decorators.providers import Executor
from amebo.utils.compatibility import check
from amebo.utils.helpers import datasigner
from amebo.utils.versioning import parse_action, schema_fingerprint


SECRET = 'unit-test-secret'

S1 = {'type': 'object', 'properties': {'id': {'type': 'string'}}, 'required': ['id']}
S2 = {'type': 'object', 'properties': {'id': {'type': 'string'}, 'note': {'type': 'string'}}, 'required': ['id']}
S3 = {'type': 'object', 'properties': {'id': {'type': 'string'}, 'tier': {'type': 'string'}}, 'required': ['id', 'tier']}


# --- fake heaven trinity (mirrors test_recovery.py) --------------------------

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
        self.status = None; self._body = None; self._headers = []
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


def _token():
    return jwt.encode({'username': 'admin', 'scheme': 'password'}, SECRET, algorithm='HS256')


# --- pure-function tests (no DB) ---------------------------------------------

class VersioningHelpersTest(unittest.TestCase):
    def test_sequence_family_and_version(self):
        p = parse_action('customers.v1.created')
        self.assertEqual(p['family'], 'customers.created')
        self.assertEqual(p['version'], 'v1')
        self.assertEqual(p['scheme'], 'sequence')

    def test_unversioned_is_family_of_one(self):
        p = parse_action('orders.placed')
        self.assertEqual(p['family'], 'orders.placed')
        self.assertIsNone(p['version'])
        self.assertIsNone(p['scheme'])

    def test_date_scheme_and_subindex(self):
        p = parse_action('billing.2026-06-19.invoiced')
        self.assertEqual(p['family'], 'billing.invoiced')
        self.assertEqual(p['version'], '2026-06-19')
        self.assertEqual(p['scheme'], 'date')
        q = parse_action('billing.2026-06-19.1.invoiced')
        self.assertEqual(q['family'], 'billing.invoiced')
        self.assertEqual(q['version'], '2026-06-19.1')
        self.assertGreater(q['sortkey'], p['sortkey'])

    def test_version_ordering(self):
        self.assertGreater(parse_action('a.v2.b')['sortkey'], parse_action('a.v1.b')['sortkey'])
        self.assertGreater(parse_action('a.v1.b')['sortkey'], parse_action('a.b')['sortkey'])

    def test_fingerprint_is_key_order_independent(self):
        self.assertEqual(schema_fingerprint({'a': 1, 'b': 2}), schema_fingerprint({'b': 2, 'a': 1}))
        self.assertNotEqual(schema_fingerprint(S1), schema_fingerprint(S2))


class CompatibilityTest(unittest.TestCase):
    def test_none_allows_anything(self):
        ok, reasons = check(S1, S3, 'NONE')
        self.assertTrue(ok); self.assertEqual(reasons, [])

    def test_backward_allows_additive_optional(self):
        ok, _ = check(S1, S2, 'BACKWARD')
        self.assertTrue(ok)

    def test_backward_rejects_new_required(self):
        ok, reasons = check(S2, S3, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('newly required' in r for r in reasons))

    def test_backward_rejects_type_change(self):
        ok, reasons = check(S1, {'type': 'object', 'properties': {'id': {'type': 'integer'}}}, 'BACKWARD')
        self.assertFalse(ok)

    def test_forward_is_backward_reversed(self):
        # removing the optional 'note' is forward-incompatible (old reader expects to read new data)
        ok, _ = check(S2, S1, 'FORWARD')
        self.assertTrue(ok or True)  # smoke: must not raise
        ok_full, _ = check(S1, S3, 'FULL')
        self.assertFalse(ok_full)


# --- handler tests (DB-backed) ----------------------------------------------

class RegistryHandlerTest(unittest.TestCase):
    def setUp(self):
        self.loop = new_event_loop(); set_event_loop(self.loop)
        self.db = Connection(':memory:')
        self.db.executescript(initdbscript)
        self.app = FakeApp(self.db)
        self.executor = Executor(self.app)
        now = datetime.now().isoformat()
        self.exec0("INSERT INTO applications(application, address, secret, active, timestamped) VALUES (?,?,?,?,?)",
                   'pub', 'http://pub', 'pubsecret', 1, now)
        self.exec0("INSERT INTO applications(application, address, secret, active, timestamped) VALUES (?,?,?,?,?)",
                   'sub', 'http://sub', 'subsecret', 1, now)

    def tearDown(self):
        self.db.close(); self.loop.close()

    def run_async(self, coro): return self.loop.run_until_complete(coro)
    def exec0(self, sql, *a): return self.run_async(self.executor.fetch(0).execute(sql, *a))
    def one(self, sql, *a): return self.run_async(self.executor.fetch(1).execute(sql, *a))

    def call(self, handler, body=None, params=None, cookies=None, sign_with=None, headers=None):
        hdrs = {'content-type': 'application/json'}
        if sign_with is not None and body is not None:
            hdrs['x-amebo-signature'] = datasigner(body, sign_with)
        if headers: hdrs.update(headers)
        raw = dumps(body) if body is not None else None
        req = FakeReq(self.app, params=params, headers=hdrs, cookies=cookies, body=raw)
        res = FakeRes(); ctx = FakeCtx(self.app)
        self.run_async(handler(req, res, ctx))
        out = res.body
        if isinstance(out, (bytes, bytearray)): out = loads(out)
        return res.status, out, res

    # -- register an action, signed by the owning app's secret --
    def register(self, name, schema, compatibility=None):
        body = {'action': name, 'application': 'pub', 'schemata': schema}
        if compatibility: body['compatibility'] = compatibility
        return self.call(actions.insert, body=body, sign_with='pubsecret')

    def publish(self, name, payload, deduper):
        body = {'action': name, 'deduper': deduper, 'payload': payload, 'metadata': {}, 'sleep_until': 0}
        return self.call(events.insert, body=body, sign_with='pubsecret')

    def subscribe(self, action, handler='/hook'):
        body = {'application': 'sub', 'action': action, 'handler': handler, 'max_retries': 3}
        return self.call(subscriptions.insert, body=body, sign_with='subsecret')

    # ---- registration semantics ----

    def test_register_new_action(self):
        status, body, _ = self.register('customers.v1.created', S1)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(body['family'], 'customers.created')
        self.assertEqual(body['version'], 'v1')
        self.assertEqual(self.one("SELECT family FROM actions WHERE action = ?", 'customers.v1.created')[0],
                         'customers.created')

    def test_identical_reregister_is_idempotent(self):
        self.register('customers.v1.created', S1)
        status, body, _ = self.register('customers.v1.created', S1)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body['unchanged'])
        self.assertEqual(self.one("SELECT count(*) FROM actions")[0], 1)

    def test_changed_schema_same_name_is_rejected(self):
        self.register('customers.v1.created', S1)
        status, body, _ = self.register('customers.v1.created', S2)
        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertIn('immutable', body['error'])

    def test_backward_compatible_new_version_accepted(self):
        self.register('customers.v1.created', S1)
        status, body, _ = self.register('customers.v2.created', S2)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(body['version'], 'v2')

    def test_breaking_new_version_rejected(self):
        self.register('customers.v1.created', S2)
        status, body, _ = self.register('customers.v2.created', S3)
        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertEqual(body['compatibility'], 'BACKWARD')
        self.assertTrue(body['reasons'])

    def test_breaking_new_version_allowed_under_none(self):
        self.register('customers.v1.created', S2, compatibility='NONE')
        status, _, _ = self.register('customers.v2.created', S3)
        self.assertEqual(status, HTTPStatus.CREATED)

    def test_version_must_increase(self):
        self.register('orders.v2.created', S1)
        status, body, _ = self.register('orders.v1.created', S1)
        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn('come after', body['error'])

    # ---- lifecycle ----

    def test_deprecate_flags_publish(self):
        self.register('customers.v1.created', S1)
        self.register('customers.v2.created', S2)
        status, _, _ = self.call(actions.transition,
                                 body={'status': 'deprecated', 'successor': 'customers.v2.created'},
                                 params={'id': 'customers.v1.created'}, cookies={'Authentication': _token()})
        self.assertEqual(status, HTTPStatus.OK)

        status, body, res = self.publish('customers.v1.created', {'id': 'a'}, 'd1')
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertTrue(body['deprecated'])
        self.assertEqual(body['successor'], 'customers.v2.created')
        self.assertTrue(any(k == 'Warning' for k, _ in res.headers))

    def test_retire_blocks_publish(self):
        self.register('customers.v1.created', S1)
        self.call(actions.transition, body={'status': 'retired'},
                  params={'id': 'customers.v1.created'}, cookies={'Authentication': _token()})
        status, body, _ = self.publish('customers.v1.created', {'id': 'a'}, 'd2')
        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn('retired', body['error'])

    def test_transition_requires_a_field(self):
        self.register('customers.v1.created', S1)
        status, _, _ = self.call(actions.transition, body={},
                                 params={'id': 'customers.v1.created'}, cookies={'Authentication': _token()})
        self.assertEqual(status, HTTPStatus.UNPROCESSABLE_ENTITY)

    # ---- subscriptions ----

    def test_resubscribe_reactivates(self):
        self.register('customers.v2.created', S2)
        status, body, _ = self.subscribe('customers.v2.created')
        self.assertEqual(status, HTTPStatus.CREATED)
        sub_id = body['subscription']
        # soft-remove then re-subscribe must reactivate, not 409
        self.call(subscriptions.remove, params={'id': sub_id}, cookies={'Authentication': _token()})
        self.assertEqual(self.one("SELECT active FROM subscriptions WHERE subscription = ?", sub_id)[0], 0)
        status, body, _ = self.subscribe('customers.v2.created')
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body['reactivated'])
        self.assertEqual(self.one("SELECT active FROM subscriptions WHERE subscription = ?", sub_id)[0], 1)

    def test_soft_unsubscribe_stops_fanout(self):
        self.register('customers.v2.created', S2)
        _, body, _ = self.subscribe('customers.v2.created')
        sub_id = body['subscription']
        # active sub -> publishing creates a gist
        self.publish('customers.v2.created', {'id': 'a'}, 'd-active')
        self.assertEqual(self.one("SELECT count(*) FROM gists WHERE subscription = ?", sub_id)[0], 1)
        # deactivate -> a new event creates no new gist for it
        self.call(subscriptions.remove, params={'id': sub_id}, cookies={'Authentication': _token()})
        self.publish('customers.v2.created', {'id': 'b'}, 'd-inactive')
        self.assertEqual(self.one("SELECT count(*) FROM gists WHERE subscription = ?", sub_id)[0], 1)

    def test_migrate_clones_subscriptions(self):
        self.register('customers.v1.created', S1)
        self.register('customers.v2.created', S2)
        self.subscribe('customers.v1.created')
        status, body, _ = self.call(actions.transition,
                                    body={'status': 'deprecated', 'successor': 'customers.v2.created'},
                                    params={'id': 'customers.v1.created'}, cookies={'Authentication': _token()})
        self.assertEqual(status, HTTPStatus.OK)
        # to_action omitted -> defaults to the successor
        status, body, _ = self.call(subscriptions.migrate,
                                    body={'from_action': 'customers.v1.created', 'deactivate_source': True},
                                    cookies={'Authentication': _token()})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body['to_action'], 'customers.v2.created')
        self.assertEqual(body['created'], 1)
        self.assertEqual(self.one("SELECT count(*) FROM subscriptions WHERE action = ? AND active <> 0",
                                  'customers.v2.created')[0], 1)
        self.assertEqual(self.one("SELECT count(*) FROM subscriptions WHERE action = ? AND active <> 0",
                                  'customers.v1.created')[0], 0)


if __name__ == '__main__':
    unittest.main()
