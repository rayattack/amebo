"""Tests for the webhook-delivery daemon (amebo/aproko.py) against in-memory
SQLite.

The daemon's `aproko(router)` coroutine runs a single traverse cycle: it selects
all pending, eligible gists (joined across gists/events/subscriptions/applications
/actions), POSTs each to its subscription handler signed with the subscriber
application's secret, then writes the delivery outcome back onto the gist row.

These tests stub the outbound HTTP client (FakeClient) and assert both the POSTs
made and the resulting gist state. The PostgreSQL branch of the daemon is not
exercised here (it requires Postgres); the SQLite path is covered end to end.
"""
import unittest
from datetime import datetime, timedelta

from tests.harness import SqliteHarness, FakeClient
import amebo.aproko as aproko


def past(hours=1):
    return (datetime.now() - timedelta(hours=hours)).isoformat()


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        # The daemon constructs AsyncClient() from a module-level import; swap it
        # for the recording fake and restore in tearDown.
        self._orig = aproko.AsyncClient
        aproko.AsyncClient = FakeClient
        FakeClient.reset()

    def tearDown(self):
        aproko.AsyncClient = self._orig
        self.h.close()

    # ---- seed helpers -------------------------------------------------------

    def _seed(self, completed=0, retries=0, max_retries=3, active=1, sleep_until=None):
        """Build a minimal deliverable setup and return the gist rowid.

        'sub' is the subscriber application: it owns the handler host and the
        secret used to sign the delivery. 'pub' is the publisher that owns the
        action the event belongs to.
        """
        h = self.h
        h.add_application('sub', address='http://sub', secret='subsecret')
        h.add_application('pub', address='http://pub', secret='pubsecret')
        h.add_action('order.created', 'pub')
        h.add_event('evt-1', 'order.created', {'id': 1})
        h.add_subscription('sub-1', 'sub', 'order.created',
                           handler='http://sub/hook', max_retries=max_retries, active=active)
        return h.add_gist('evt-1', 'sub-1', completed=completed, retries=retries,
                          sleep_until=sleep_until or past())

    # ---- tests --------------------------------------------------------------

    def test_successful_delivery_marks_completed(self):
        gid = self._seed(completed=0, retries=0)
        FakeClient.reset(code=200)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(len(FakeClient.calls), 1)
        self.assertEqual(FakeClient.calls[0]['url'], 'http://sub/hook')
        completed = self.h.one("SELECT completed FROM gists WHERE rowid=?", gid)[0]
        self.assertEqual(completed, 1)

    def test_failed_delivery_increments_retry(self):
        gid = self._seed(completed=0, retries=0, max_retries=3)
        FakeClient.reset(code=500)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(len(FakeClient.calls), 1)
        row = self.h.one(
            "SELECT completed, retries, dead_at FROM gists WHERE rowid=?", gid)
        self.assertEqual(row[0], 0)        # completed
        self.assertEqual(row[1], 1)        # retries 0 -> 1
        self.assertIsNone(row[2])          # dead_at still null

    def test_exhaustion_dead_letters_gist(self):
        # retries=2, max_retries=3 -> this failed attempt makes it 3 and dead-letters.
        gid = self._seed(completed=0, retries=2, max_retries=3)
        FakeClient.reset(code=500)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(len(FakeClient.calls), 1)
        row = self.h.one(
            "SELECT retries, dead_at FROM gists WHERE rowid=?", gid)
        self.assertEqual(row[0], 3)        # retries 2 -> 3
        self.assertIsNotNone(row[1])       # dead_at set

    def test_inactive_subscription_is_skipped(self):
        gid = self._seed(completed=0, retries=0, active=0)
        FakeClient.reset(code=200)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(FakeClient.calls, [])
        row = self.h.one(
            "SELECT completed, retries FROM gists WHERE rowid=?", gid)
        self.assertEqual(row[0], 0)        # untouched
        self.assertEqual(row[1], 0)

    def test_completed_gist_is_skipped(self):
        gid = self._seed(completed=1, retries=0)
        FakeClient.reset(code=200)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(FakeClient.calls, [])
        # stays completed; no extra attempt recorded
        row = self.h.one(
            "SELECT completed, retries FROM gists WHERE rowid=?", gid)
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 0)

    def test_no_work_cycle_returns_cleanly(self):
        # empty DB: no gists at all -> count == 0 branch, sleeps(0) and returns.
        FakeClient.reset(code=200)

        result = self.h.run(aproko.aproko(self.h.app))

        self.assertTrue(result)
        self.assertEqual(FakeClient.calls, [])

    def test_delivery_exception_is_recorded_as_failure(self):
        # When the POST itself raises, the daemon records a failed attempt
        # (retries bumped, dead_at still null) rather than crashing the cycle.
        gid = self._seed(completed=0, retries=0, max_retries=3)

        class RaisingClient(FakeClient):
            async def post(self, url, json=None, headers=None):
                raise RuntimeError('connection refused')

        aproko.AsyncClient = RaisingClient

        result = self.h.run(aproko.aproko(self.h.app))

        self.assertTrue(result)
        row = self.h.one(
            "SELECT completed, retries, dead_at FROM gists WHERE rowid=?", gid)
        self.assertEqual(row[0], 0)        # not completed
        self.assertEqual(row[1], 1)        # retries 0 -> 1
        self.assertIsNone(row[2])          # not yet dead

    def test_delivery_carries_signed_headers(self):
        self._seed(completed=0, retries=0)
        FakeClient.reset(code=200)

        self.h.run(aproko.aproko(self.h.app))

        self.assertEqual(len(FakeClient.calls), 1)
        headers = FakeClient.calls[0]['headers']
        self.assertIn('x-amebo-signature', headers)
        self.assertTrue(headers['x-amebo-signature'])
        self.assertEqual(headers['x-amebo-event-id'], 'evt-1')


if __name__ == '__main__':
    unittest.main()
