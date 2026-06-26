"""Unit tests for the security-hardening primitives:

- HMAC inbound verification with optional, backward-compatible replay protection
  (amebo.utils.helpers.verify_request_signature)
- SSRF guard for user-supplied webhook URLs (amebo.utils.netguard)
- credential-endpoint rate limiter (amebo.utils.throttle)

Runs offline: SSRF cases use IP-literal hosts so getaddrinfo resolves without DNS.
"""
import time
import unittest

from amebo.utils.helpers import (
    datasigner, verify_request_signature, timestamped_signer, replay_tolerance,
)
from amebo.utils import netguard, throttle


SECRET = 'unit-test-secret-key'
PAYLOAD = {'action': 'order.placed', 'payload': {'order_id': 'o-1', 'total': 9.99}}


class VerifyRequestSignatureTest(unittest.TestCase):
    # ---- legacy (no timestamp) path stays backward compatible ---------------

    def test_legacy_valid_signature_accepted(self):
        sig = datasigner(PAYLOAD, SECRET)
        ok, reason = verify_request_signature(PAYLOAD, sig, SECRET)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_legacy_wrong_signature_rejected(self):
        ok, _ = verify_request_signature(PAYLOAD, 'deadbeef', SECRET)
        self.assertFalse(ok)

    def test_missing_signature_rejected(self):
        ok, reason = verify_request_signature(PAYLOAD, None, SECRET)
        self.assertFalse(ok)
        self.assertEqual(reason, 'missing signature')

    # ---- timestamped (replay-protected) path --------------------------------

    def test_timestamped_valid_signature_accepted(self):
        ts = int(time.time())
        sig = timestamped_signer(PAYLOAD, SECRET, ts)
        ok, reason = verify_request_signature(PAYLOAD, sig, SECRET, timestamp=ts)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_stale_timestamp_rejected(self):
        ts = int(time.time()) - (replay_tolerance() + 60)
        sig = timestamped_signer(PAYLOAD, SECRET, ts)  # signature itself is valid
        ok, reason = verify_request_signature(PAYLOAD, sig, SECRET, timestamp=ts)
        self.assertFalse(ok)  # ... but the request is too old to replay
        self.assertEqual(reason, 'stale or future timestamp')

    def test_future_timestamp_rejected(self):
        ts = int(time.time()) + (replay_tolerance() + 60)
        sig = timestamped_signer(PAYLOAD, SECRET, ts)
        ok, _ = verify_request_signature(PAYLOAD, sig, SECRET, timestamp=ts)
        self.assertFalse(ok)

    def test_legacy_signature_does_not_satisfy_timestamped_request(self):
        # an attacker replays a captured body-only signature but adds a fresh
        # timestamp header — must fail because the timestamp isn't in the MAC.
        ts = int(time.time())
        legacy_sig = datasigner(PAYLOAD, SECRET)
        ok, _ = verify_request_signature(PAYLOAD, legacy_sig, SECRET, timestamp=ts)
        self.assertFalse(ok)

    def test_invalid_timestamp_value_rejected(self):
        sig = datasigner(PAYLOAD, SECRET)
        ok, reason = verify_request_signature(PAYLOAD, sig, SECRET, timestamp='not-a-number')
        self.assertFalse(ok)
        self.assertEqual(reason, 'invalid timestamp')

    def test_empty_timestamp_falls_back_to_legacy(self):
        sig = datasigner(PAYLOAD, SECRET)
        ok, _ = verify_request_signature(PAYLOAD, sig, SECRET, timestamp='')
        self.assertTrue(ok)

    def test_tampered_body_rejected_timestamped(self):
        ts = int(time.time())
        sig = timestamped_signer(PAYLOAD, SECRET, ts)
        tampered = {'action': 'order.placed', 'payload': {'order_id': 'o-1', 'total': 999999}}
        ok, _ = verify_request_signature(tampered, sig, SECRET, timestamp=ts)
        self.assertFalse(ok)


class NetguardTest(unittest.TestCase):
    def setUp(self):
        # the guard is opt-in; turn strict mode ON so the block cases below apply
        self._saved = netguard.environ.get('AMEBO_BLOCK_PRIVATE_WEBHOOKS')
        netguard.environ['AMEBO_BLOCK_PRIVATE_WEBHOOKS'] = '1'

    def tearDown(self):
        if self._saved is None:
            netguard.environ.pop('AMEBO_BLOCK_PRIVATE_WEBHOOKS', None)
        else:
            netguard.environ['AMEBO_BLOCK_PRIVATE_WEBHOOKS'] = self._saved

    def test_ip_classification(self):
        for blocked in ('127.0.0.1', '10.0.0.1', '192.168.1.5', '172.16.0.1',
                        '169.254.169.254', '::1', '0.0.0.0', '224.0.0.1'):
            self.assertTrue(netguard._ip_is_blocked(blocked), blocked)
        for ok in ('8.8.8.8', '1.1.1.1'):
            self.assertFalse(netguard._ip_is_blocked(ok), ok)

    def test_loopback_url_blocked(self):
        ok, reason = netguard.validate_webhook_url('http://127.0.0.1/hook')
        self.assertFalse(ok)
        self.assertIn('not publicly routable', reason)

    def test_cloud_metadata_url_blocked(self):
        ok, _ = netguard.validate_webhook_url('http://169.254.169.254/latest/meta-data/')
        self.assertFalse(ok)

    def test_private_url_blocked(self):
        ok, _ = netguard.validate_webhook_url('https://10.0.0.5:8443/webhooks')
        self.assertFalse(ok)

    def test_non_http_scheme_blocked(self):
        ok, reason = netguard.validate_webhook_url('ftp://example.com/x')
        self.assertFalse(ok)
        self.assertIn('scheme', reason)

    def test_default_allows_private(self):
        # with strict mode OFF (the default), localhost/internal targets are allowed
        # — the common self-hosted topology must not be broken.
        netguard.environ.pop('AMEBO_BLOCK_PRIVATE_WEBHOOKS', None)
        ok, reason = netguard.validate_webhook_url('http://127.0.0.1/hook')
        self.assertTrue(ok)
        self.assertIsNone(reason)


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        throttle._buckets.clear()

    def test_blocks_after_max_attempts(self):
        key = 'tokens:1.2.3.4'
        for _ in range(3):
            self.assertFalse(throttle.rate_limited(key, max_attempts=3, window=60))
        # 4th attempt within the window is rejected
        self.assertTrue(throttle.rate_limited(key, max_attempts=3, window=60))

    def test_reset_clears_history(self):
        key = 'tokens:5.6.7.8'
        for _ in range(3):
            throttle.rate_limited(key, max_attempts=3, window=60)
        throttle.reset_attempts(key)
        self.assertFalse(throttle.rate_limited(key, max_attempts=3, window=60))

    def test_client_key_prefers_forwarded_for(self):
        class _H:
            def __init__(self, d): self.d = d
            def get(self, k, default=None): return self.d.get(k, default)
        class _Req:
            headers = _H({'x-forwarded-for': '203.0.113.9, 10.0.0.1'})
        self.assertEqual(throttle.client_key(_Req(), scope='tokens'), 'tokens:203.0.113.9')


if __name__ == '__main__':
    unittest.main()
