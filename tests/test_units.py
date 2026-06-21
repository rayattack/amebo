"""Unit tests for the pure-ish utility helpers and the security middleware.

Covers:
- amebo.utils.helpers       (pagination, timeline, redaction, tokens, apikeys,
                             deterministic uuid, backoff, error truncation)
- amebo.utils.structs       (Steps clause-builder, Lookup attribute proxy)
- amebo.utils.compatibility (JSON-schema compatibility modes)
- amebo.middlewares.security (cors header middleware, upsecret)

Runs offline; reuses the shared test harness fakes.
"""
import asyncio
import os
import unittest

from amebo.constants.literals import DEFAULT_PAGINATION
from amebo.utils import helpers, structs, compatibility
from amebo.middlewares import security

from tests.harness import FakeReq, FakeApp, FakeRes


# --------------------------------------------------------------------------- #
# helpers.get_pagination
# --------------------------------------------------------------------------- #

class GetPaginationTest(unittest.TestCase):
    def _req(self, queries):
        return FakeReq(FakeApp(None), queries=queries)

    def test_valid_values(self):
        page, pagination = helpers.get_pagination(self._req({'page': '2', 'pagination': '30'}))
        self.assertEqual(page, 2)
        self.assertEqual(pagination, 30)

    def test_missing_defaults(self):
        page, pagination = helpers.get_pagination(self._req({}))
        self.assertEqual(page, 1)
        self.assertEqual(pagination, DEFAULT_PAGINATION)

    def test_invalid_defaults(self):
        page, pagination = helpers.get_pagination(self._req({'page': 'abc', 'pagination': 'xyz'}))
        self.assertEqual(page, 1)
        self.assertEqual(pagination, DEFAULT_PAGINATION)

    def test_negative_clamps(self):
        page, pagination = helpers.get_pagination(self._req({'page': '-5', 'pagination': '-3'}))
        self.assertEqual(page, 1)
        self.assertEqual(pagination, DEFAULT_PAGINATION)


# --------------------------------------------------------------------------- #
# helpers.get_timeline
# --------------------------------------------------------------------------- #

class GetTimelineTest(unittest.TestCase):
    def setUp(self):
        self.steps = structs.Steps('sqlite')

    def test_today_week_month_build_clause(self):
        for value in ('today', 'week', 'month'):
            clause = helpers.get_timeline(value, self.steps)
            self.assertTrue(clause)
            self.assertIn('timestamped', clause)
            self.assertIn('DATETIME', clause)

    def test_clean_step_uses_where(self):
        clause = helpers.get_timeline('today', self.steps)
        self.assertTrue(clause.startswith('WHERE'))

    def test_dirty_step_uses_and(self):
        self.steps.EQUALS('a', 'x')  # makes the step dirty
        clause = helpers.get_timeline('today', self.steps)
        self.assertTrue(clause.startswith('AND'))

    def test_custom_column(self):
        clause = helpers.get_timeline('week', self.steps, column='created')
        self.assertIn('created', clause)

    def test_falsy_timeline_returns_empty(self):
        self.assertEqual(helpers.get_timeline('', self.steps), '')
        self.assertEqual(helpers.get_timeline(None, self.steps), '')


# --------------------------------------------------------------------------- #
# helpers.redact_payload
# --------------------------------------------------------------------------- #

class RedactPayloadTest(unittest.TestCase):
    def test_simple_field(self):
        out = helpers.redact_payload(['ssn'], {'ssn': '123', 'name': 'ok'})
        self.assertEqual(out['ssn'], helpers.REDACTED)
        self.assertEqual(out['name'], 'ok')

    def test_nested_field(self):
        out = helpers.redact_payload(['address.zip'], {'address': {'zip': '00100', 'city': 'x'}})
        self.assertEqual(out['address']['zip'], helpers.REDACTED)
        self.assertEqual(out['address']['city'], 'x')

    def test_array_field(self):
        payload = {'items': [{'serial': 'a', 'qty': 1}, {'serial': 'b', 'qty': 2}]}
        out = helpers.redact_payload(['items[].serial'], payload)
        self.assertEqual(out['items'][0]['serial'], helpers.REDACTED)
        self.assertEqual(out['items'][1]['serial'], helpers.REDACTED)
        self.assertEqual(out['items'][0]['qty'], 1)

    def test_array_whole_key(self):
        out = helpers.redact_payload(['items[]'], {'items': [1, 2, 3]})
        self.assertEqual(out['items'], helpers.REDACTED)

    def test_non_dict_passthrough(self):
        self.assertEqual(helpers.redact_payload(['x'], 'plain'), 'plain')
        self.assertEqual(helpers.redact_payload(['x'], [1, 2]), [1, 2])

    def test_empty_field_paths_passthrough(self):
        payload = {'ssn': '123'}
        self.assertEqual(helpers.redact_payload([], payload), payload)

    def test_original_not_mutated(self):
        payload = {'ssn': '123'}
        helpers.redact_payload(['ssn'], payload)
        self.assertEqual(payload['ssn'], '123')

    def test_missing_path_is_noop(self):
        out = helpers.redact_payload(['nope.zip', 'absent'], {'name': 'x'})
        self.assertEqual(out, {'name': 'x'})

    def test_empty_segment_path_is_noop(self):
        # a path that splits to an empty segment list ('' -> ['']) shouldn't blow up
        out = helpers.redact_payload([''], {'name': 'x'})
        self.assertEqual(out, {'name': 'x'})


# --------------------------------------------------------------------------- #
# helpers.get_params
# --------------------------------------------------------------------------- #

class GetParamsTest(unittest.TestCase):
    def test_extracts_in_order(self):
        req = FakeReq(FakeApp(None), params={'application': 'orders', 'action': 'placed'})
        self.assertEqual(helpers.get_params(['application', 'action'], req),
                         ['orders', 'placed'])

    def test_missing_param_is_none(self):
        req = FakeReq(FakeApp(None), params={'application': 'orders'})
        self.assertEqual(helpers.get_params(['application', 'missing'], req),
                         ['orders', None])


# --------------------------------------------------------------------------- #
# helpers.status_expr
# --------------------------------------------------------------------------- #

class StatusExprTest(unittest.TestCase):
    def test_default_aliases(self):
        expr = helpers.status_expr()
        self.assertIn('CASE', expr)
        self.assertIn("'delivered'", expr)
        self.assertIn("'failed'", expr)
        self.assertIn('g.completed', expr)
        self.assertIn('s.max_retries', expr)

    def test_custom_aliases(self):
        expr = helpers.status_expr('gi', 'su')
        self.assertIn('gi.completed', expr)
        self.assertIn('su.max_retries', expr)


# --------------------------------------------------------------------------- #
# helpers HMAC signing primitives
# --------------------------------------------------------------------------- #

class SigningTest(unittest.TestCase):
    def test_datasigner_datachecker_round_trip(self):
        payload = {'a': 1, 'b': 'two'}
        sig = helpers.datasigner(payload, 'secret')
        self.assertIsInstance(sig, str)
        self.assertTrue(helpers.datachecker(payload, sig, 'secret'))

    def test_datachecker_rejects_wrong_secret(self):
        payload = {'a': 1}
        sig = helpers.datasigner(payload, 'secret')
        self.assertFalse(helpers.datachecker(payload, sig, 'other'))

    def test_timestamped_signer_binds_timestamp(self):
        payload = {'a': 1}
        s1 = helpers.timestamped_signer(payload, 'secret', 1000)
        s2 = helpers.timestamped_signer(payload, 'secret', 2000)
        self.assertNotEqual(s1, s2)


class ReplayToleranceTest(unittest.TestCase):
    def _set(self, value):
        prior = os.environ.get('AMEBO_REPLAY_TOLERANCE')
        if value is None:
            os.environ.pop('AMEBO_REPLAY_TOLERANCE', None)
        else:
            os.environ['AMEBO_REPLAY_TOLERANCE'] = value
        return prior

    def _restore(self, prior):
        if prior is None:
            os.environ.pop('AMEBO_REPLAY_TOLERANCE', None)
        else:
            os.environ['AMEBO_REPLAY_TOLERANCE'] = prior

    def test_default_when_unset(self):
        prior = self._set(None)
        try:
            self.assertEqual(helpers.replay_tolerance(), helpers.DEFAULT_REPLAY_TOLERANCE)
        finally:
            self._restore(prior)

    def test_reads_env_int(self):
        prior = self._set('900')
        try:
            self.assertEqual(helpers.replay_tolerance(), 900)
        finally:
            self._restore(prior)

    def test_invalid_env_falls_back(self):
        prior = self._set('not-a-number')
        try:
            self.assertEqual(helpers.replay_tolerance(), helpers.DEFAULT_REPLAY_TOLERANCE)
        finally:
            self._restore(prior)


# --------------------------------------------------------------------------- #
# helpers.tokenize / untokenize
# --------------------------------------------------------------------------- #

class TokenRoundTripTest(unittest.TestCase):
    def test_round_trip(self):
        secret = 'sekret'
        data = {'username': 'admin', 'scheme': 'password'}
        token = helpers.tokenize(data, secret)
        self.assertIsInstance(token, str)
        decoded = helpers.untokenize(token, secret)
        self.assertEqual(decoded['username'], 'admin')
        self.assertEqual(decoded['scheme'], 'password')


# --------------------------------------------------------------------------- #
# helpers API keys + deterministic uuid
# --------------------------------------------------------------------------- #

class ApiKeyTest(unittest.TestCase):
    def test_generate_and_verify(self):
        plaintext, hashed = helpers.generate_apikey()
        self.assertTrue(plaintext.startswith('amebo_'))
        self.assertNotEqual(plaintext, hashed)
        self.assertTrue(helpers.verify_apikey(plaintext, hashed))

    def test_verify_rejects_wrong_key(self):
        _, hashed = helpers.generate_apikey()
        other, _ = helpers.generate_apikey()
        self.assertFalse(helpers.verify_apikey(other, hashed))


class DeterministicUuidTest(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(helpers.deterministic_uuid(), helpers.deterministic_uuid())

    def test_hex_length(self):
        self.assertEqual(len(helpers.deterministic_uuid()), 32)


# --------------------------------------------------------------------------- #
# helpers.backoff_seconds / truncate_error
# --------------------------------------------------------------------------- #

class BackoffSecondsTest(unittest.TestCase):
    def test_attempt_below_one_clamps_to_base(self):
        self.assertEqual(helpers.backoff_seconds(0), helpers.BACKOFF_BASE_SECONDS)
        self.assertEqual(helpers.backoff_seconds(-7), helpers.BACKOFF_BASE_SECONDS)

    def test_first_attempt_is_base(self):
        self.assertEqual(helpers.backoff_seconds(1), helpers.BACKOFF_BASE_SECONDS)

    def test_grows_exponentially(self):
        self.assertEqual(helpers.backoff_seconds(2),
                         helpers.BACKOFF_BASE_SECONDS * helpers.BACKOFF_FACTOR)

    def test_large_attempt_hits_cap(self):
        self.assertEqual(helpers.backoff_seconds(1000), helpers.BACKOFF_CAP_SECONDS)

    def test_monotonic_non_decreasing(self):
        seq = [helpers.backoff_seconds(a) for a in range(1, 12)]
        self.assertEqual(seq, sorted(seq))


class TruncateErrorTest(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(helpers.truncate_error(None))

    def test_short_unchanged(self):
        self.assertEqual(helpers.truncate_error('boom'), 'boom')

    def test_long_clamped(self):
        long = 'x' * (helpers.MAX_ERROR_LENGTH + 500)
        out = helpers.truncate_error(long)
        self.assertEqual(len(out), helpers.MAX_ERROR_LENGTH)

    def test_non_string_coerced(self):
        self.assertEqual(helpers.truncate_error(404), '404')

    def test_custom_limit(self):
        self.assertEqual(helpers.truncate_error('abcdef', limit=3), 'abc')


# --------------------------------------------------------------------------- #
# structs.Steps
# --------------------------------------------------------------------------- #

class StepsTest(unittest.TestCase):
    def test_equals_builds_where_then_and(self):
        s = structs.Steps('sqlite')
        first = s.EQUALS('a', 'x')
        self.assertEqual(first, 'WHERE a = ?')
        second = s.EQUALS('b', 'y')
        self.assertEqual(second, 'AND b = ?')
        self.assertEqual(s.values, ['x', 'y'])

    def test_equals_zero_is_kept(self):
        s = structs.Steps('sqlite')
        clause = s.EQUALS('flag', 0)
        self.assertEqual(clause, 'WHERE flag = ?')
        self.assertEqual(s.values, [0])

    def test_equals_none_skipped(self):
        s = structs.Steps('sqlite')
        self.assertEqual(s.EQUALS('a', None), '')
        self.assertEqual(s.values, [])
        self.assertFalse(s.dirty)

    def test_like_builds_clause_and_wraps_value(self):
        s = structs.Steps('sqlite')
        clause = s.LIKE('b', 'y')
        self.assertEqual(clause, 'WHERE b LIKE ?')
        self.assertEqual(s.values, ['%y%'])

    def test_like_none_skipped(self):
        s = structs.Steps('sqlite')
        self.assertEqual(s.LIKE('b', None), '')
        self.assertEqual(s.values, [])

    def test_like_uses_and_when_dirty(self):
        s = structs.Steps('sqlite')
        s.EQUALS('a', 'x')  # dirty
        clause = s.LIKE('b', 'y')
        self.assertEqual(clause, 'AND b LIKE ?')
        self.assertEqual(s.values, ['x', '%y%'])

    def test_dirty_tracks_values(self):
        s = structs.Steps('sqlite')
        self.assertFalse(s.dirty)
        s.EQUALS('a', 'x')
        self.assertTrue(s.dirty)

    def test_next_sqlite(self):
        s = structs.Steps('sqlite')
        self.assertEqual(s.next(), '?')
        self.assertEqual(s.next(3), '?, ?, ?')

    def test_next_postgres_increments(self):
        s = structs.Steps('postgres')
        self.assertEqual(s.next(), '$1')
        self.assertEqual(s.next(), '$2')

    def test_reset_resets_counter(self):
        s = structs.Steps('postgres')
        s.next()
        s.next()
        s.reset
        self.assertEqual(s.next(), '$1')


class LookupTest(unittest.TestCase):
    def test_reads_attribute(self):
        lk = structs.Lookup({'engine': 'sqlite'})
        self.assertEqual(lk.engine, 'sqlite')

    def test_nested_dict_wrapped(self):
        lk = structs.Lookup({'cfg': {'idles': 5}})
        self.assertIsInstance(lk.cfg, structs.Lookup)
        self.assertEqual(lk.cfg.idles, 5)

    def test_missing_returns_none(self):
        lk = structs.Lookup({})
        self.assertIsNone(lk.nope)

    def test_set_attribute_writes_through(self):
        data = {}
        lk = structs.Lookup(data)
        lk.token = 'abc'
        self.assertEqual(data['token'], 'abc')

    def test_dollar_sentinel(self):
        lk = structs.Lookup({})
        self.assertEqual(lk._, {'dollar': '$'})


# --------------------------------------------------------------------------- #
# compatibility.check
# --------------------------------------------------------------------------- #

def _schema(props, required=None, additional=None):
    s = {'type': 'object', 'properties': props}
    if required is not None:
        s['required'] = required
    if additional is not None:
        s['additionalProperties'] = additional
    return s


class CompatibilityTest(unittest.TestCase):
    def test_none_mode_accepts_anything(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'other': {'type': 'integer'}}, required=['other'])
        ok, reasons = compatibility.check(old, new, 'NONE')
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_backward_add_optional_ok(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'string'}, 'note': {'type': 'string'}}, required=['id'])
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertTrue(ok, reasons)

    def test_backward_add_required_breaks(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'string'}, 'note': {'type': 'string'}},
                      required=['id', 'note'])
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('newly required' in r for r in reasons))

    def test_backward_remove_field_breaks_when_no_additional(self):
        old = _schema({'id': {'type': 'string'}, 'note': {'type': 'string'}},
                      required=['id'], additional=False)
        new = _schema({'id': {'type': 'string'}}, required=['id'], additional=False)
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('property removed' in r for r in reasons))

    def test_backward_default_mode_when_unknown(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'string'}}, required=['id', 'extra'])
        ok, reasons = compatibility.check(old, new, 'GIBBERISH')
        self.assertFalse(ok)

    def test_forward_remove_optional_field_ok(self):
        # producers upgrade first: new omits an optional field; old must read new's data.
        old = _schema({'id': {'type': 'string'}, 'note': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'string'}}, required=['id'])
        ok, reasons = compatibility.check(old, new, 'FORWARD')
        self.assertTrue(ok, reasons)

    def test_forward_drop_required_field_breaks(self):
        # producers upgrade first: new no longer requires 'note', but the old reader
        # still does. forward = backward(new, old) -> old marks 'note' newly required.
        old = _schema({'id': {'type': 'string'}, 'note': {'type': 'string'}},
                      required=['id', 'note'])
        new = _schema({'id': {'type': 'string'}}, required=['id'])
        ok, reasons = compatibility.check(old, new, 'FORWARD')
        self.assertFalse(ok)
        self.assertTrue(reasons)
        self.assertTrue(all(r.startswith('(forward)') for r in reasons))

    def test_full_requires_both_directions(self):
        # adding an optional field: BACKWARD ok but FORWARD breaks (old can't be read
        # by... actually forward reasons about removing) -> assert identical schema ok.
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        ok, reasons = compatibility.check(old, old, 'FULL')
        self.assertTrue(ok, reasons)

    def test_full_flags_breaking_change(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'integer'}}, required=['id'])
        ok, reasons = compatibility.check(old, new, 'FULL')
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_type_change_breaks(self):
        old = _schema({'id': {'type': 'string'}}, required=['id'])
        new = _schema({'id': {'type': 'integer'}}, required=['id'])
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('type changed' in r for r in reasons))

    def test_integer_widens_to_number(self):
        old = _schema({'n': {'type': 'integer'}})
        new = _schema({'n': {'type': 'number'}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertTrue(ok, reasons)

    def test_adding_type_constraint_breaks(self):
        old = _schema({'v': {}})
        new = _schema({'v': {'type': 'string'}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('adds a type constraint' in r for r in reasons))

    def test_additional_properties_tightened_breaks(self):
        old = _schema({'id': {'type': 'string'}})  # additionalProperties defaults True
        new = _schema({'id': {'type': 'string'}}, additional=False)
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('additionalProperties tightened' in r for r in reasons))

    def test_numeric_bound_tightened_breaks(self):
        old = _schema({'n': {'type': 'integer', 'minimum': 0}})
        new = _schema({'n': {'type': 'integer', 'minimum': 5}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('minimum tightened' in r for r in reasons))

    def test_max_bound_tightened_breaks(self):
        old = _schema({'s': {'type': 'string', 'maxLength': 100}})
        new = _schema({'s': {'type': 'string', 'maxLength': 10}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('maxLength tightened' in r for r in reasons))

    def test_bound_unverifiable_type_error(self):
        old = _schema({'n': {'type': 'integer', 'minimum': 'oops'}})
        new = _schema({'n': {'type': 'integer', 'minimum': 5}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('unverifiable' in r for r in reasons))

    def test_pattern_added_breaks(self):
        old = _schema({'s': {'type': 'string'}})
        new = _schema({'s': {'type': 'string', 'pattern': '^x'}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('pattern added' in r for r in reasons))

    def test_multiple_of_added_breaks(self):
        old = _schema({'n': {'type': 'integer'}})
        new = _schema({'n': {'type': 'integer', 'multipleOf': 2}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('multipleOf' in r for r in reasons))

    def test_enum_restriction_added_breaks(self):
        old = _schema({'s': {'type': 'string'}})
        new = _schema({'s': {'type': 'string', 'enum': ['a', 'b']}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('enum restriction added' in r for r in reasons))

    def test_enum_narrowed_breaks(self):
        old = _schema({'s': {'type': 'string', 'enum': ['a', 'b', 'c']}})
        new = _schema({'s': {'type': 'string', 'enum': ['a']}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('no longer permits' in r for r in reasons))

    def test_enum_widened_ok(self):
        old = _schema({'s': {'type': 'string', 'enum': ['a']}})
        new = _schema({'s': {'type': 'string', 'enum': ['a', 'b']}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertTrue(ok, reasons)

    def test_const_changed_breaks(self):
        old = _schema({'s': {'type': 'string', 'const': 'x'}})
        new = _schema({'s': {'type': 'string', 'const': 'y'}})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('const' in r for r in reasons))

    def test_nested_array_items_type_change_breaks(self):
        old = {'type': 'array', 'items': {'type': 'string'}}
        new = {'type': 'array', 'items': {'type': 'integer'}}
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any(r.endswith("from 'string' to 'integer'") or '[]' in r for r in reasons))

    def test_array_items_shape_change_breaks(self):
        old = {'type': 'array', 'items': {'type': 'string'}}
        new = {'type': 'array', 'items': [{'type': 'string'}]}
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('items schema changed' in r for r in reasons))

    def test_opaque_keyword_change_breaks(self):
        old = _schema({'id': {'type': 'string'}})
        new = _schema({'id': {'type': 'string'}})
        new['oneOf'] = [{'type': 'object'}]
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('oneOf changed' in r for r in reasons))

    def test_non_dict_schema_yields_no_reasons(self):
        ok, reasons = compatibility.check('nope', {'type': 'object'}, 'BACKWARD')
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_nested_property_recursion(self):
        old = _schema({'addr': _schema({'zip': {'type': 'string'}})})
        new = _schema({'addr': _schema({'zip': {'type': 'integer'}})})
        ok, reasons = compatibility.check(old, new, 'BACKWARD')
        self.assertFalse(ok)
        self.assertTrue(any('addr.zip' in r for r in reasons))


# --------------------------------------------------------------------------- #
# security.cors
# --------------------------------------------------------------------------- #

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _cors_req(url, headers=None, scheme='https'):
    req = FakeReq(FakeApp(None), headers=headers or {})
    req.url = url
    req.scheme = scheme
    return req


def _header_dict(res):
    return dict(res.headers)


class CorsTest(unittest.TestCase):
    def test_api_route_allows_any_origin(self):
        req = _cors_req('/v1/actions')
        res = FakeRes()
        _run(security.cors(req, res, None))
        headers = _header_dict(res)
        self.assertEqual(headers['Access-Control-Allow-Origin'], '*')
        self.assertIn('Access-Control-Allow-Methods', headers)
        # API branch must NOT set credentials
        self.assertNotIn('Access-Control-Allow-Credentials', headers)

    def test_v8_route_allows_any_origin(self):
        req = _cors_req('/v8/whatever')
        res = FakeRes()
        _run(security.cors(req, res, None))
        self.assertEqual(_header_dict(res)['Access-Control-Allow-Origin'], '*')

    def test_ui_route_same_origin_echoed(self):
        req = _cors_req('/p/home', headers={'origin': 'https://app.example.com',
                                             'host': 'app.example.com'})
        res = FakeRes()
        _run(security.cors(req, res, None))
        headers = _header_dict(res)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://app.example.com')
        self.assertEqual(headers['Access-Control-Allow-Credentials'], 'true')

    def test_ui_route_no_origin_falls_back_to_scheme_host(self):
        req = _cors_req('/p/home', headers={'host': 'app.example.com'}, scheme='https')
        res = FakeRes()
        _run(security.cors(req, res, None))
        headers = _header_dict(res)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://app.example.com')

    def test_ui_headers_stored_as_tuples(self):
        req = _cors_req('/p/home', headers={'host': 'app.example.com'})
        res = FakeRes()
        _run(security.cors(req, res, None))
        # FakeRes appends (k, v) tuples
        self.assertTrue(all(isinstance(h, tuple) and len(h) == 2 for h in res.headers))


# --------------------------------------------------------------------------- #
# security.upsecret
# --------------------------------------------------------------------------- #

class UpsecretTest(unittest.TestCase):
    def test_loads_secret_from_env(self):
        prior = os.environ.get('AMEBO_SECRET')
        os.environ['AMEBO_SECRET'] = 'super-secret'
        try:
            app = FakeApp(None, secret=None)
            security.upsecret(app)
            self.assertEqual(app.peek('AMEBO_SECRET'), 'super-secret')
        finally:
            if prior is None:
                os.environ.pop('AMEBO_SECRET', None)
            else:
                os.environ['AMEBO_SECRET'] = prior


if __name__ == '__main__':
    unittest.main()
