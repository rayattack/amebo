"""Tests for the operability surface: health/readiness probes, the Prometheus
exposition endpoint, the request-id + access-log middleware, and structured logging.
"""
import logging
import unittest
from http import HTTPStatus

from tests.harness import (
    SqliteHarness, FakeApp, FakeReq, FakeRes, FakeCtx, decode_body,
)
import amebo.controllers.health as health
import amebo.controllers.metrics as metrics
import amebo.middlewares.observability as obs
import amebo.utils.logs as logs


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_health_is_ok(self):
        res = self.h.call(health.health)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res)['status'], 'ok')

    def test_readyz_ok_when_db_reachable(self):
        res = self.h.call(health.readyz)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res)['status'], 'ready')

    def test_readyz_503_when_db_missing(self):
        # an app with no DB connection (engine 'postgres', db None) is not ready
        app = FakeApp(None, engine='postgres')
        req, res, ctx = FakeReq(app), FakeRes(), FakeCtx(app)
        self.h.run(health.readyz(req, res, ctx))
        self.assertEqual(res.status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(decode_body(res)['status'], 'unavailable')


class PrometheusTest(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def _body(self, res):
        return res.body.decode() if isinstance(res.body, (bytes, bytearray)) else res.body

    def test_exposition_format(self):
        self.h.add_application('svc')
        self.h.add_action('a.b', 'svc')
        self.h.add_event('e1', 'a.b', {'x': 1})
        self.h.add_subscription('s1', 'svc', 'a.b', 'http://svc/h')
        self.h.add_gist('e1', 's1', completed=1)
        res = self.h.call(metrics.prometheus)
        self.assertEqual(res.status, HTTPStatus.OK)
        # content-type is the prometheus exposition type
        ctype = dict(res.headers).get('Content-Type', '')
        self.assertIn('text/plain', ctype)
        self.assertIn('version=0.0.4', ctype)
        body = self._body(res)
        self.assertIn('amebo_up 1', body)
        self.assertIn('amebo_gists{status="delivered"} 1', body)
        self.assertIn('amebo_events_published 1', body)
        self.assertIn('amebo_subscriptions_active 1', body)

    def test_help_type_emitted_once_per_family(self):
        res = self.h.call(metrics.prometheus)
        body = self._body(res)
        # spec: HELP/TYPE appear exactly once per metric family even with labels
        self.assertEqual(body.count('# TYPE amebo_gists gauge'), 1)
        self.assertEqual(body.count('# HELP amebo_gists '), 1)

    def test_empty_db_still_renders(self):
        res = self.h.call(metrics.prometheus)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertIn('amebo_gists_total 0', self._body(res))


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class ObservabilityMiddlewareTest(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_request_context_generates_id_and_echoes_header(self):
        app = self.h.app
        req, res, ctx = FakeReq(app), FakeRes(), FakeCtx(app)

        # the contextvar is set within the request's task; assert it from inside the
        # same coroutine (mirrors how before-hook/handler/after-hook share one task).
        async def scenario():
            await obs.request_context(req, res, ctx)
            return logs.get_request_id()

        seen = self.h.run(scenario())
        rid = ctx.request_id
        self.assertTrue(rid and rid != '-')
        self.assertEqual(seen, rid)
        # echoed on the response
        self.assertIn(('X-Request-ID', rid), res.headers)

    def test_request_context_honours_inbound_id(self):
        app = self.h.app
        req = FakeReq(app, headers={'x-request-id': 'trace-abc'})
        res, ctx = FakeRes(), FakeCtx(app)
        self.h.run(obs.request_context(req, res, ctx))
        self.assertEqual(ctx.request_id, 'trace-abc')
        self.assertIn(('X-Request-ID', 'trace-abc'), res.headers)

    def test_access_log_emits_line(self):
        cap = _Capture()
        access_logger = logging.getLogger('amebo.access')
        access_logger.addHandler(cap)
        access_logger.setLevel(logging.DEBUG)
        try:
            app = self.h.app
            req = FakeReq(app, method='POST', url='/v1/events')
            res, ctx = FakeRes(), FakeCtx(app)
            res.status = 201
            self.h.run(obs.request_context(req, res, ctx))
            self.h.run(obs.access_log(req, res, ctx))
        finally:
            access_logger.removeHandler(cap)
        msgs = [r.getMessage() for r in cap.records]
        self.assertTrue(any('/v1/events' in m and '201' in m for m in msgs))


class LoggingConfigTest(unittest.TestCase):
    def test_request_id_round_trip(self):
        logs.set_request_id('rid-123')
        self.assertEqual(logs.get_request_id(), 'rid-123')
        logs.set_request_id(None)  # falsy -> '-'
        self.assertEqual(logs.get_request_id(), '-')

    def test_request_id_filter_stamps_record(self):
        logs.set_request_id('rid-xyz')
        f = logs.RequestIdFilter()
        rec = logging.LogRecord('x', logging.INFO, __file__, 1, 'hi', None, None)
        self.assertTrue(f.filter(rec))
        self.assertEqual(rec.request_id, 'rid-xyz')

    def test_json_formatter_shape(self):
        from orjson import loads
        logs.set_request_id('rid-json')
        fmt = logs.JsonFormatter()
        rec = logging.LogRecord('amebo.test', logging.INFO, __file__, 1, 'hello %s', ('world',), None)
        rec.request_id = 'rid-json'
        rec.status = 200
        out = loads(fmt.format(rec))
        self.assertEqual(out['level'], 'INFO')
        self.assertEqual(out['logger'], 'amebo.test')
        self.assertEqual(out['message'], 'hello world')
        self.assertEqual(out['request_id'], 'rid-json')
        self.assertEqual(out['status'], 200)

    def test_json_formatter_includes_exception(self):
        from orjson import loads
        fmt = logs.JsonFormatter()
        try:
            raise ValueError('boom')
        except ValueError:
            import sys
            rec = logging.LogRecord('amebo.test', logging.ERROR, __file__, 1, 'failed', None, sys.exc_info())
        out = loads(fmt.format(rec))
        self.assertIn('exc', out)
        self.assertIn('boom', out['exc'])

    def test_configure_logging_idempotent(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            logs.configure_logging()
            logs.configure_logging()  # second call must not stack a second amebo handler
            tagged = [h for h in root.handlers if getattr(h, logs._HANDLER_TAG, False)]
            self.assertEqual(len(tagged), 1)
        finally:
            root.handlers = saved


if __name__ == '__main__':
    unittest.main()
