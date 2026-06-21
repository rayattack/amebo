"""Tests for amebo/controllers/applications.py.

Drives the real (decorated) controller handlers through the shared in-memory
SQLite harness. Covers the credential/token authentication endpoint (including
brute-force throttling), admin-gated provisioning with the SSRF guard, the
Bearer-apikey secret rotation, apikey regeneration, active-flag toggling, and
the listing/filter endpoint.
"""
import os
import unittest
from http import HTTPStatus

from bcrypt import gensalt, hashpw

from tests.harness import SqliteHarness, decode_body, auth_cookie, admin_token

import amebo.controllers.applications as applications
import amebo.utils.throttle as throttle
from amebo.utils.helpers import generate_apikey


def _set_cookie_headers(res):
    return [v for (k, v) in res.headers if k == 'Set-Cookie']


class AuthenticateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()
        throttle._buckets.clear()

    def tearDown(self):
        throttle._buckets.clear()
        self.h.close()

    def test_password_scheme_success(self):
        password = self.h.add_credential('admin', 'admin-pass')
        res = self.h.call(applications.authenticate,
                          body={'username': 'admin', 'password': password, 'scheme': 'password'})
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)
        body = decode_body(res)
        self.assertIn('token', body)
        self.assertTrue(body['token'])
        # a Set-Cookie header carrying the Authentication cookie is emitted
        cookies = _set_cookie_headers(res)
        self.assertTrue(any(c.startswith('Authentication=') for c in cookies))

    def test_wrong_password_unauthorized(self):
        self.h.add_credential('admin', 'admin-pass')
        res = self.h.call(applications.authenticate,
                          body={'username': 'admin', 'password': 'nope', 'scheme': 'password'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
        self.assertIn('error', decode_body(res))

    def test_unknown_user_unauthorized(self):
        res = self.h.call(applications.authenticate,
                          body={'username': 'ghost', 'password': 'whatever', 'scheme': 'password'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_token_scheme_success(self):
        secret_value = 'super-secret-value'
        hashed = hashpw(secret_value.encode(), gensalt()).decode()
        self.h.add_application('orders', secret=hashed)
        res = self.h.call(applications.authenticate,
                          body={'username': 'orders', 'password': secret_value, 'scheme': 'token'})
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)
        self.assertIn('token', decode_body(res))

    def test_token_scheme_wrong_secret_unauthorized(self):
        hashed = hashpw(b'right-value', gensalt()).decode()
        self.h.add_application('orders', secret=hashed)
        res = self.h.call(applications.authenticate,
                          body={'username': 'orders', 'password': 'wrong-value', 'scheme': 'token'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_rate_limit_after_max_attempts(self):
        throttle._buckets.clear()
        self.h.add_credential('admin', 'admin-pass')
        # default MAX_ATTEMPTS is 5: the first five are processed (and fail auth),
        # the sixth is rejected by the limiter before any auth work happens.
        for _ in range(throttle.MAX_ATTEMPTS):
            res = self.h.call(applications.authenticate,
                              body={'username': 'admin', 'password': 'bad', 'scheme': 'password'})
            self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
        res = self.h.call(applications.authenticate,
                          body={'username': 'admin', 'password': 'bad', 'scheme': 'password'})
        self.assertEqual(res.status, HTTPStatus.TOO_MANY_REQUESTS)

    def test_successful_auth_resets_throttle(self):
        throttle._buckets.clear()
        password = self.h.add_credential('admin', 'admin-pass')
        # burn a few failed attempts (below the limit)
        for _ in range(throttle.MAX_ATTEMPTS - 1):
            self.h.call(applications.authenticate,
                        body={'username': 'admin', 'password': 'bad', 'scheme': 'password'})
        key = throttle.client_key
        # a successful auth clears the failed-attempt history
        ok = self.h.call(applications.authenticate,
                         body={'username': 'admin', 'password': password, 'scheme': 'password'})
        self.assertEqual(ok.status, HTTPStatus.ACCEPTED)
        # the bucket for this client is now cleared
        self.assertNotIn('tokens:global', throttle._buckets)


class InsertTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_success(self):
        res = self.h.call(applications.insert, cookies=auth_cookie(),
                          body={'application': 'orders', 'address': 'https://orders.example.com'})
        self.assertEqual(res.status, HTTPStatus.CREATED)
        body = decode_body(res)
        self.assertEqual(body['name'], 'orders')
        self.assertTrue(body['apikey'].startswith('amebo_'))

    def test_no_cookie_unauthorized(self):
        res = self.h.call(applications.insert,
                          body={'application': 'orders', 'address': 'https://orders.example.com'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_invalid_cookie_unauthorized(self):
        res = self.h.call(applications.insert, cookies={'Authentication': 'garbage'},
                          body={'application': 'orders', 'address': 'https://orders.example.com'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_duplicate_conflict(self):
        self.h.add_application('orders')
        res = self.h.call(applications.insert, cookies=auth_cookie(),
                          body={'application': 'orders', 'address': 'https://orders.example.com'})
        self.assertEqual(res.status, HTTPStatus.CONFLICT)

    def test_ssrf_block_strict_mode(self):
        os.environ['AMEBO_BLOCK_PRIVATE_WEBHOOKS'] = '1'
        try:
            res = self.h.call(applications.insert, cookies=auth_cookie(),
                              body={'application': 'internal', 'address': 'http://127.0.0.1/x'})
            self.assertEqual(res.status, HTTPStatus.BAD_REQUEST)
            self.assertIn('error', decode_body(res))
        finally:
            os.environ.pop('AMEBO_BLOCK_PRIVATE_WEBHOOKS', None)

    def test_private_address_allowed_when_strict_off(self):
        # default (strict off): private targets are permitted (self-hosted topology)
        os.environ.pop('AMEBO_BLOCK_PRIVATE_WEBHOOKS', None)
        res = self.h.call(applications.insert, cookies=auth_cookie(),
                          body={'application': 'internal', 'address': 'http://127.0.0.1/x'})
        self.assertEqual(res.status, HTTPStatus.CREATED)


class SetSecretTests(unittest.TestCase):
    GOOD_SECRET = 'a-very-long-secret-value'  # >= 16 chars

    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def _seed_with_key(self, name='orders', active=1):
        plaintext, hashed = generate_apikey()
        self.h.add_application(name, apikey=hashed, active=active)
        return plaintext

    def test_success(self):
        plaintext = self._seed_with_key('orders')
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          headers={'authorization': f'Bearer {plaintext}'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.ACCEPTED)
        self.assertIn('message', decode_body(res))
        # secret was actually persisted
        row = self.h.one("SELECT secret FROM applications WHERE application = ?", 'orders')
        self.assertEqual(row[0], self.GOOD_SECRET)

    def test_missing_authorization_header(self):
        self._seed_with_key('orders')
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_non_bearer_scheme(self):
        self._seed_with_key('orders')
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          headers={'authorization': 'Basic abcdef'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.BAD_REQUEST)

    def test_application_not_found(self):
        res = self.h.call(applications.set_secret,
                          params={'id': 'ghost'},
                          headers={'authorization': 'Bearer amebo_whatever'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.NOT_FOUND)

    def test_inactive_application_forbidden(self):
        plaintext = self._seed_with_key('orders', active=0)
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          headers={'authorization': f'Bearer {plaintext}'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.FORBIDDEN)

    def test_no_apikey_configured_forbidden(self):
        # active app but apikey column is NULL
        self.h.add_application('orders', apikey=None, active=1)
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          headers={'authorization': 'Bearer amebo_whatever'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.FORBIDDEN)

    def test_wrong_apikey_unauthorized(self):
        self._seed_with_key('orders')
        res = self.h.call(applications.set_secret,
                          params={'id': 'orders'},
                          headers={'authorization': 'Bearer amebo_wrongkey'},
                          body={'secret': self.GOOD_SECRET})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)


class RegenerateApikeyTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_success(self):
        plaintext, hashed = generate_apikey()
        self.h.add_application('orders', apikey=hashed)
        res = self.h.call(applications.regenerate_apikey, cookies=auth_cookie(),
                          params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['application'], 'orders')
        self.assertTrue(body['apikey'].startswith('amebo_'))
        self.assertNotEqual(body['apikey'], plaintext)

    def test_no_cookie_unauthorized(self):
        self.h.add_application('orders')
        res = self.h.call(applications.regenerate_apikey, params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_invalid_cookie_unauthorized(self):
        self.h.add_application('orders')
        res = self.h.call(applications.regenerate_apikey,
                          cookies={'Authentication': 'garbage'}, params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)

    def test_not_found(self):
        res = self.h.call(applications.regenerate_apikey, cookies=auth_cookie(),
                          params={'id': 'ghost'})
        self.assertEqual(res.status, HTTPStatus.NOT_FOUND)


class ToggleActiveTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_toggle_off(self):
        self.h.add_application('orders', active=1)
        res = self.h.call(applications.toggle_active, cookies=auth_cookie(),
                          params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.OK)
        body = decode_body(res)
        self.assertEqual(body['application'], 'orders')
        self.assertFalse(body['active'])
        row = self.h.one("SELECT active FROM applications WHERE application = ?", 'orders')
        self.assertEqual(row[0], 0)

    def test_toggle_on(self):
        self.h.add_application('orders', active=0)
        res = self.h.call(applications.toggle_active, cookies=auth_cookie(),
                          params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertTrue(decode_body(res)['active'])

    def test_not_found(self):
        res = self.h.call(applications.toggle_active, cookies=auth_cookie(),
                          params={'id': 'ghost'})
        self.assertEqual(res.status, HTTPStatus.NOT_FOUND)

    def test_no_cookie_unauthorized(self):
        self.h.add_application('orders')
        res = self.h.call(applications.toggle_active, params={'id': 'orders'})
        self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)


class TabulateTests(unittest.TestCase):
    def setUp(self):
        self.h = SqliteHarness()

    def tearDown(self):
        self.h.close()

    def test_empty(self):
        res = self.h.call(applications.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        self.assertEqual(decode_body(res), [])

    def test_list(self):
        self.h.add_application('orders', address='https://orders.example.com')
        self.h.add_application('billing', address='https://billing.example.com')
        res = self.h.call(applications.tabulate)
        self.assertEqual(res.status, HTTPStatus.OK)
        names = {row['application'] for row in decode_body(res)}
        self.assertEqual(names, {'orders', 'billing'})
        # shape check
        for row in decode_body(res):
            self.assertIn('address', row)
            self.assertIn('active', row)
            self.assertIn('timestamped', row)
            self.assertIsInstance(row['active'], bool)

    def test_filter_by_application(self):
        self.h.add_application('orders')
        self.h.add_application('billing')
        res = self.h.call(applications.tabulate, queries={'application': 'ord'})
        self.assertEqual(res.status, HTTPStatus.OK)
        names = {row['application'] for row in decode_body(res)}
        self.assertEqual(names, {'orders'})


if __name__ == '__main__':
    unittest.main()
