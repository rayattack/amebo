"""Tests for the redactions, metrics, events and subscriptions controllers.

Drives the real (decorated) controller handlers through the shared in-memory
SQLite harness in tests/harness.py. Every assertion checks the actual status
code / body key emitted by the controller source (not a guessed contract).

Two SQLite-specific quirks are exercised and documented inline:
  - redactions.insert only catches asyncpg's UniqueViolationError, so a duplicate
    on SQLite (sqlite3.IntegrityError) falls through to the generic handler and
    returns 426 UPGRADE_REQUIRED rather than 409 CONFLICT.
  - events.insert / subscriptions.insert catch (UniqueViolationError, IntegrityError),
    so de-duplication / idempotent re-subscribe work on SQLite.
"""
import unittest
from http import HTTPStatus

from tests.harness import SqliteHarness, decode_body, auth_cookie, sign

import amebo.controllers.redactions as redactions
import amebo.controllers.metrics as metrics
import amebo.controllers.events as events
import amebo.controllers.subscriptions as subscriptions


# --- redactions --------------------------------------------------------------

class RedactionsTabulateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_empty(self):
        res = self.h.call(redactions.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res), [])

    def test_list(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_action('billing.v1.charged', 'svc')
        self.h.add_redaction('orders.v1.created', 'card')
        self.h.add_redaction('billing.v1.charged', 'iban')
        res = self.h.call(redactions.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 2)
        # shape: id/action/field_path/timestamped + parsed family/version
        row = body[0]
        for key in ('id', 'action', 'field_path', 'timestamped', 'family', 'version'):
            self.assertIn(key, row)
        fields = {r['field_path'] for r in body}
        self.assertEqual(fields, {'card', 'iban'})

    def test_filter_by_action(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_action('billing.v1.charged', 'svc')
        self.h.add_redaction('orders.v1.created', 'card')
        self.h.add_redaction('billing.v1.charged', 'iban')
        res = self.h.call(redactions.tabulate, queries={'action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['action'], 'orders.v1.created')
        self.assertEqual(body[0]['field_path'], 'card')

    def test_filter_by_field_path_like(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_redaction('orders.v1.created', 'card')
        self.h.add_redaction('orders.v1.created', 'cvv')
        res = self.h.call(redactions.tabulate, queries={'field_path': 'car'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual({r['field_path'] for r in body}, {'card'})


class RedactionsInsertTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        # an application owning an action, with its own secret
        self.h.add_application('svc', secret='svc-secret')
        self.h.add_action('a.b', 'svc')

    def tearDown(self):
        self.h.close()

    def test_signature_auth_created(self):
        body = {'action': 'a.b', 'field_path': 'card'}
        res = self.h.call(redactions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'svc-secret')})
        self.assertEqual(res.status, HTTPStatus.CREATED)
        out = decode_body(res)
        self.assertEqual(out['action'], 'a.b')
        self.assertEqual(out['field_path'], 'card')
        # persisted
        row = self.h.one("SELECT field_path FROM redactions WHERE action = ?", 'a.b')
        self.assertEqual(row[0], 'card')

    def test_secret_in_body_created(self):
        # no signature header: the body must carry the owning app's correct secret
        body = {'action': 'a.b', 'field_path': 'pan', 'secret': 'svc-secret'}
        res = self.h.call(redactions.insert, body=body)
        self.assertEqual(res.status, HTTPStatus.CREATED)
        self.assertEqual(decode_body(res)['field_path'], 'pan')

    def test_invalid_signature_unauthorized(self):
        body = {'action': 'a.b', 'field_path': 'card'}
        res = self.h.call(redactions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'wrong-secret')})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
        self.assertIn('error', decode_body(res))

    def test_wrong_secret_in_body_unauthorized(self):
        body = {'action': 'a.b', 'field_path': 'card', 'secret': 'nope'}
        res = self.h.call(redactions.insert, body=body)
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_action_not_found_unauthorized(self):
        body = {'action': 'does.not.exist', 'field_path': 'card'}
        res = self.h.call(redactions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'svc-secret')})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
        self.assertIn('not found', decode_body(res)['error'])

    def test_duplicate_returns_upgrade_required(self):
        # SQLite raises sqlite3.IntegrityError on the UNIQUE(action, field_path)
        # constraint, which the controller does NOT catch as UniqueViolationError,
        # so it falls through to the generic handler -> 426 UPGRADE_REQUIRED.
        self.h.add_redaction('a.b', 'card')
        body = {'action': 'a.b', 'field_path': 'card'}
        res = self.h.call(redactions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'svc-secret')})
        self.assertEqual(res.status, HTTPStatus.UPGRADE_REQUIRED)
        self.assertIn('error', decode_body(res))

    def test_validation_error_empty_field_path(self):
        # field_path validator rejects empty -> @expects returns 400
        body = {'action': 'a.b', 'field_path': '   '}
        res = self.h.call(redactions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'svc-secret')})
        self.assertEqual(res.status, HTTPStatus.BAD_REQUEST)


class RedactionsBulkInsertTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc')
        self.h.add_action('a.b', 'svc')

    def tearDown(self):
        self.h.close()

    def test_bulk_insert_skips_blank_and_persists(self):
        # exercises bulk_insert_redactions: strips, skips empties, inserts the rest
        self.h.run(redactions.bulk_insert_redactions(
            self.h.executor, 'a.b', [' card ', '', '  ', 'cvv']))
        rows = self.h.query("SELECT field_path FROM redactions WHERE action = ? ORDER BY field_path", 'a.b')
        self.assertEqual([r[0] for r in rows], ['card', 'cvv'])

    def test_fetch_redacted_paths(self):
        self.h.add_redaction('a.b', 'card')
        self.h.add_redaction('a.b', 'cvv')
        paths = self.h.run(redactions.fetch_redacted_paths(self.h.executor, 'a.b'))
        self.assertEqual(set(paths), {'card', 'cvv'})
        # action with no redactions -> empty list
        self.assertEqual(self.h.run(redactions.fetch_redacted_paths(self.h.executor, 'x.y')), [])


class RedactionsRemoveTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_remove_accepted(self):
        self.h.add_application('svc')
        self.h.add_action('a.b', 'svc')
        self.h.add_redaction('a.b', 'card')
        rowid = self.h.one("SELECT rowid FROM redactions WHERE action = ?", 'a.b')[0]
        res = self.h.call(redactions.remove, params={'id': rowid})
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)
        self.assertEqual(decode_body(res)['removed'], rowid)
        # gone
        self.assertIsNone(self.h.one("SELECT rowid FROM redactions WHERE rowid = ?", rowid))


# --- metrics -----------------------------------------------------------------

class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc', secret='svc-secret')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/hook', max_retries=3)
        self.h.add_event('evt-1', 'orders.v1.created', {'id': 1})
        self.h.add_event('evt-2', 'orders.v1.created', {'id': 2}, deduper='evt-2')
        self.h.add_event('evt-3', 'orders.v1.created', {'id': 3}, deduper='evt-3')
        # one delivered, one retrying (retries>0, < max), one pending (retries 0)
        self.h.add_gist('evt-1', 'sub-1', completed=1)
        self.h.add_gist('evt-2', 'sub-1', completed=0, retries=1)
        self.h.add_gist('evt-3', 'sub-1', completed=0, retries=0)

    def tearDown(self):
        self.h.close()

    def test_deliveries_all_window(self):
        res = self.h.call(metrics.deliveries)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['window'], 'all')
        self.assertEqual(body['published'], 3)
        self.assertEqual(body['delivered'], 1)
        self.assertEqual(body['retrying'], 1)
        self.assertEqual(body['pending'], 1)
        self.assertEqual(body['failed'], 0)
        self.assertEqual(body['total'], 3)
        # success_rate = delivered / (delivered + failed) * 100 = 100.0
        self.assertEqual(body['success_rate'], 100.0)

    def test_deliveries_windowed(self):
        # exercises the cutoff branch (window != all)
        res = self.h.call(metrics.deliveries, queries={'window': 'today'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['window'], 'today')
        # all rows were just inserted, so they fall inside the 24h window
        self.assertEqual(body['total'], 3)
        self.assertEqual(body['published'], 3)

    def test_subscriptions_health(self):
        res = self.h.call(metrics.subscriptions)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertIn('data', body)
        self.assertEqual(len(body['data']), 1)
        row = body['data'][0]
        self.assertEqual(row['subscription'], 'sub-1')
        self.assertEqual(row['subscriber'], 'svc')
        self.assertEqual(row['action'], 'orders.v1.created')
        self.assertEqual(row['delivered'], 1)
        self.assertEqual(row['retrying'], 1)
        self.assertEqual(row['pending'], 1)
        self.assertEqual(row['total'], 3)
        # no last_error set on any gist
        self.assertIsNone(row['last_error'])

    def test_subscriptions_health_with_last_error(self):
        # set a last_error on one gist so the errors_sql branch is exercised
        self.h.exec0(
            "UPDATE gists SET last_error = ?, last_attempted_at = ?, last_status_code = ? "
            "WHERE event = ? AND subscription = ?",
            'boom', '2026-06-21T00:00:00', 500, 'evt-2', 'sub-1')
        res = self.h.call(metrics.subscriptions)
        self.assertEqual(res.status, HTTPStatus.OK)
        row = decode_body(res)['data'][0]
        self.assertEqual(row['last_error'], 'boom')
        self.assertEqual(row['last_status_code'], 500)

    def test_versions(self):
        # add a deprecated + retired action with active subscribers (migration debt)
        self.h.add_action('orders.v2.created', 'svc', status='deprecated',
                          family='orders.created', successor='orders.v3.created')
        self.h.add_action('orders.v0.created', 'svc', status='retired', family='orders.created')
        self.h.add_subscription('sub-dep', 'svc', 'orders.v2.created', 'https://svc/dep')
        res = self.h.call(metrics.versions)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertIn('by_status', body)
        self.assertEqual(body['by_status']['deprecated'], 1)
        self.assertEqual(body['by_status']['retired'], 1)
        self.assertEqual(body['total_actions'], 3)
        # one active subscriber pinned to deprecated/retired
        self.assertEqual(body['subscriptions_on_deprecated'], 1)
        self.assertIn('at_risk', body)
        at_risk_actions = {r['action'] for r in body['at_risk']}
        self.assertEqual(at_risk_actions, {'orders.v2.created', 'orders.v0.created'})


# --- events ------------------------------------------------------------------

class EventsTabulateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_empty(self):
        res = self.h.call(events.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res), [])

    def test_list_with_redaction_applies_mask(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_event('evt-1', 'orders.v1.created', {'id': 1, 'card': '4111111111111111'})
        self.h.add_redaction('orders.v1.created', 'card')
        res = self.h.call(events.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['payload']['card'], '**redacted**')
        self.assertEqual(body[0]['payload']['id'], 1)
        self.assertEqual(body[0]['family'], 'orders.created')
        self.assertEqual(body[0]['version'], 'v1')

    def test_filter_by_action(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_action('billing.v1.charged', 'svc')
        self.h.add_event('evt-1', 'orders.v1.created', {'id': 1})
        self.h.add_event('evt-2', 'billing.v1.charged', {'id': 2})
        res = self.h.call(events.tabulate, queries={'action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['action'], 'orders.v1.created')


class EventsInsertTests(unittest.TestCase):
    SECRET = 'producer-secret'

    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc', secret=self.SECRET)

    def tearDown(self):
        self.h.close()

    def _publish(self, action, payload, deduper='dd-1', sleep_until=None, secret=None):
        body = {
            'action': action,
            'payload': payload,
            'deduper': deduper,
            'sleep_until': sleep_until,
            'metadata': {},
        }
        return body, self.h.call(
            events.insert, body=body,
            headers={'x-amebo-signature': sign(body, secret or self.SECRET)})

    def test_publish_active_created(self):
        self.h.add_action('orders.v1.created', 'svc', schemata='{}')
        _, res = self._publish('orders.v1.created', {'id': 1})
        self.assertEqual(res.status, HTTPStatus.CREATED)
        body = decode_body(res)
        self.assertEqual(body['action'], 'orders.v1.created')
        self.assertEqual(body['payload'], {'id': 1})
        self.assertIn('event', body)
        self.assertNotIn('deprecated', body)

    def test_publish_fans_out_gist(self):
        self.h.add_action('orders.v1.created', 'svc', schemata='{}')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/hook')
        self._publish('orders.v1.created', {'id': 1})
        # a gist should have been created for the active subscription
        count = self.h.one("SELECT COUNT(*) FROM gists WHERE subscription = ?", 'sub-1')[0]
        self.assertEqual(count, 1)

    def test_publish_deprecated_created_with_flag(self):
        self.h.add_action('orders.v1.created', 'svc', schemata='{}', status='deprecated',
                          successor='orders.v2.created')
        _, res = self._publish('orders.v1.created', {'id': 1})
        self.assertEqual(res.status, HTTPStatus.CREATED)
        body = decode_body(res)
        self.assertTrue(body['deprecated'])
        self.assertEqual(body['successor'], 'orders.v2.created')
        # a Warning header is emitted
        warnings = [v for (k, v) in res.headers if k == 'Warning']
        self.assertTrue(warnings)

    def test_publish_retired_unprocessable(self):
        self.h.add_action('orders.v1.created', 'svc', schemata='{}', status='retired',
                          successor='orders.v2.created')
        _, res = self._publish('orders.v1.created', {'id': 1})
        self.assertEqual(res.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        body = decode_body(res)
        self.assertIn('retired', body['error'])
        self.assertEqual(body['successor'], 'orders.v2.created')

    def test_publish_unknown_action_unprocessable(self):
        _, res = self._publish('ghost.v1.created', {'id': 1})
        self.assertEqual(res.status, HTTPStatus.UNPROCESSABLE_ENTITY)
        self.assertIn('error', decode_body(res))

    def test_publish_bad_signature_unauthorized(self):
        self.h.add_action('orders.v1.created', 'svc', schemata='{}')
        body = {'action': 'orders.v1.created', 'payload': {'id': 1},
                'deduper': 'dd-1', 'sleep_until': None, 'metadata': {}}
        res = self.h.call(events.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'wrong-secret')})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_publish_schema_violation_not_acceptable(self):
        # require an integer `id`; send a string to trip schema validation
        schema = '{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}'
        self.h.add_action('orders.v1.created', 'svc', schemata=schema)
        _, res = self._publish('orders.v1.created', {'id': 'not-an-int'})
        self.assertEqual(res.status, HTTPStatus.NOT_ACCEPTABLE)

    def test_publish_with_sleep_until(self):
        # sleep_until set -> the gist sleep_until is pushed into the future (line 134 branch)
        self.h.add_action('orders.v1.created', 'svc', schemata='{}')
        _, res = self._publish('orders.v1.created', {'id': 1}, sleep_until=60)
        self.assertEqual(res.status, HTTPStatus.CREATED)
        self.assertIn('sleep_until', decode_body(res))

    def test_publish_duplicate_returns_ok(self):
        # events.insert catches IntegrityError, so a duplicate deduper+payload
        # is treated as an idempotent re-publish -> 200 OK with duplicate: True.
        self.h.add_action('orders.v1.created', 'svc', schemata='{}')
        self._publish('orders.v1.created', {'id': 1}, deduper='same')
        _, res = self._publish('orders.v1.created', {'id': 1}, deduper='same')
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertTrue(decode_body(res)['duplicate'])


# --- subscriptions -----------------------------------------------------------

class SubscriptionsTabulateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_list_and_filter(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_action('billing.v1.charged', 'svc')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/a')
        self.h.add_subscription('sub-2', 'svc', 'billing.v1.charged', 'https://svc/b', active=0)
        res = self.h.call(subscriptions.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 2)
        row = body[0]
        for key in ('subscription', 'action', 'application', 'endpoint', 'active',
                    'family', 'version', 'action_status'):
            self.assertIn(key, row)
        self.assertIsInstance(row['active'], bool)

    def test_filter_by_active(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/a', active=1)
        self.h.add_subscription('sub-2', 'svc', 'orders.v1.created', 'https://svc/b', active=0)
        res = self.h.call(subscriptions.tabulate, queries={'active': '1'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['subscription'], 'sub-1')

    def test_filter_by_action_status_populated(self):
        self.h.add_application('svc')
        self.h.add_action('orders.v1.created', 'svc', status='deprecated')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/a')
        res = self.h.call(subscriptions.tabulate, queries={'action': 'orders.v1.created'})
        body = decode_body(res)
        self.assertEqual(body[0]['action_status'], 'deprecated')


class SubscriptionsInsertTests(unittest.TestCase):
    SECRET = 'svc-secret'

    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc', address='https://svc.example.com/', secret=self.SECRET)
        self.h.add_action('orders.v1.created', 'svc')

    def tearDown(self):
        self.h.close()

    def _body(self, handler='/hook', action='orders.v1.created', app='svc', max_retries=3):
        return {'application': app, 'action': action, 'handler': handler, 'max_retries': max_retries}

    def test_subscribe_created(self):
        body = self._body()
        res = self.h.call(subscriptions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, self.SECRET)})
        self.assertEqual(res.status, HTTPStatus.CREATED)
        out = decode_body(res)
        self.assertIn('subscription', out)
        self.assertEqual(out['action'], 'orders.v1.created')
        # handler stored as host + path (address joined)
        row = self.h.one("SELECT handler FROM subscriptions WHERE subscription = ?", out['subscription'])
        self.assertEqual(row[0], 'https://svc.example.com/hook')

    def test_subscribe_unknown_application_expectation_failed(self):
        body = self._body(app='ghost')
        res = self.h.call(subscriptions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, self.SECRET)})
        self.assertEqual(res.status, HTTPStatus.EXPECTATION_FAILED)

    def test_subscribe_bad_signature_unauthorized(self):
        body = self._body()
        res = self.h.call(subscriptions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, 'wrong')})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_subscribe_duplicate_reactivates(self):
        # insert catches IntegrityError on UNIQUE(application, action, handler):
        # the second call reactivates instead of conflicting -> 200 with reactivated: True
        body = self._body()
        self.h.call(subscriptions.insert, body=body,
                    headers={'x-amebo-signature': sign(body, self.SECRET)})
        # soft-unsubscribe then re-subscribe to confirm reactivation
        self.h.exec0("UPDATE subscriptions SET active = 0 WHERE action = ?", 'orders.v1.created')
        res = self.h.call(subscriptions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, self.SECRET)})
        self.assertEqual(res.status, HTTPStatus.OK)
        out = decode_body(res)
        self.assertTrue(out['reactivated'])
        # active flag restored
        row = self.h.one("SELECT active FROM subscriptions WHERE subscription = ?", out['subscription'])
        self.assertEqual(row[0], 1)

    def test_subscribe_invalid_handler_bad_request(self):
        # handler must start with '/': model validation -> @expects 400
        body = self._body(handler='hook')
        res = self.h.call(subscriptions.insert, body=body,
                          headers={'x-amebo-signature': sign(body, self.SECRET)})
        self.assertEqual(res.status, HTTPStatus.BAD_REQUEST)


class SubscriptionsRemoveTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc', secret='svc-secret')
        self.h.add_action('orders.v1.created', 'svc')
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/a', active=1)

    def tearDown(self):
        self.h.close()

    def test_admin_remove_accepted(self):
        res = self.h.call(subscriptions.remove, params={'id': 'sub-1'}, cookies=auth_cookie())
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)
        body = decode_body(res)
        self.assertEqual(body['unsubscribed'], 'sub-1')
        self.assertFalse(body['active'])
        # active flag flipped to 0
        row = self.h.one("SELECT active FROM subscriptions WHERE subscription = ?", 'sub-1')
        self.assertEqual(row[0], 0)

    def test_signature_remove_accepted(self):
        # subscriber-signed remove path (no admin cookie)
        body = {}
        res = self.h.call(subscriptions.remove, params={'id': 'sub-1'}, body=body,
                          headers={'x-amebo-signature': sign(body, 'svc-secret')})
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)

    def test_not_found(self):
        res = self.h.call(subscriptions.remove, params={'id': 'ghost'}, cookies=auth_cookie())
        self.assertEqual(res.status, HTTPStatus.NOT_FOUND)

    def test_no_auth_unauthorized(self):
        res = self.h.call(subscriptions.remove, params={'id': 'sub-1'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_bad_signature_unauthorized(self):
        body = {}
        res = self.h.call(subscriptions.remove, params={'id': 'sub-1'}, body=body,
                          headers={'x-amebo-signature': sign(body, 'wrong-secret')})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_bad_admin_cookie_unauthorized(self):
        # cookie present but untokenize fails (line 174 branch)
        res = self.h.call(subscriptions.remove, params={'id': 'sub-1'},
                          cookies={'Authentication': 'garbage'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)


class SubscriptionsMigrateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        self.h.add_application('svc', secret='svc-secret')
        # v1 with a declared successor v2; both actions exist
        self.h.add_action('orders.v2.created', 'svc', family='orders.created')
        self.h.add_action('orders.v1.created', 'svc', family='orders.created',
                          successor='orders.v2.created')
        # an active subscription on v1 to be cloned forward
        self.h.add_subscription('sub-1', 'svc', 'orders.v1.created', 'https://svc/a', active=1)

    def tearDown(self):
        self.h.close()

    def test_migrate_via_successor_default(self):
        # to_action omitted -> defaults to from_action's successor
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['from_action'], 'orders.v1.created')
        self.assertEqual(body['to_action'], 'orders.v2.created')
        self.assertEqual(body['created'], 1)
        # a v2 subscription now exists
        cnt = self.h.one("SELECT COUNT(*) FROM subscriptions WHERE action = ? AND active <> 0",
                         'orders.v2.created')[0]
        self.assertEqual(cnt, 1)

    def test_migrate_explicit_to_action(self):
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'orders.v1.created',
                                'to_action': 'orders.v2.created'})
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res)['created'], 1)

    def test_migrate_deactivate_source(self):
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'orders.v1.created', 'deactivate_source': True})
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertTrue(decode_body(res)['deactivated_source'])
        # source subscription is now inactive
        row = self.h.one("SELECT active FROM subscriptions WHERE subscription = ?", 'sub-1')
        self.assertEqual(row[0], 0)

    def test_migrate_reactivates_existing(self):
        # pre-existing inactive v2 sub with same (app, action, handler) -> reactivated
        self.h.add_subscription('sub-2', 'svc', 'orders.v2.created', 'https://svc/a', active=0)
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['reactivated'], 1)
        self.assertEqual(body['created'], 0)

    def test_migrate_source_not_found(self):
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'ghost.v1.created'})
        self.assertEqual(res.status, HTTPStatus.NOT_FOUND)

    def test_migrate_no_successor_unprocessable(self):
        # action exists but has no successor and no to_action passed -> 422
        self.h.add_action('solo.v1.created', 'svc')
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'solo.v1.created'})
        self.assertEqual(res.status, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_migrate_target_missing_unprocessable(self):
        # explicit to_action that doesn't exist -> 422
        res = self.h.call(subscriptions.migrate, cookies=auth_cookie(),
                          body={'from_action': 'orders.v1.created',
                                'to_action': 'orders.v9.created'})
        self.assertEqual(res.status, HTTPStatus.UNPROCESSABLE_ENTITY)

    def test_migrate_no_cookie_unauthorized(self):
        res = self.h.call(subscriptions.migrate,
                          body={'from_action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_migrate_bad_cookie_unauthorized(self):
        res = self.h.call(subscriptions.migrate, cookies={'Authentication': 'garbage'},
                          body={'from_action': 'orders.v1.created'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)


if __name__ == '__main__':
    unittest.main()
