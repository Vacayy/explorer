import unittest

from security.trial_identity import COOKIE_NAME, COOKIE_TTL, InvalidTrialIdentity, TrialIdentity


class TrialIdentityTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.identity = self.make_identity()

    def make_identity(self, **kwargs):
        return TrialIdentity(b'a' * 32, 'https://example.test', clock=lambda: self.now, **kwargs)

    def test_cookie_randomness_digest_stability_and_domain_separation(self):
        first, second = self.identity.issue_cookie(), self.identity.issue_cookie()
        self.assertNotEqual(first, second)
        actor, csrf = self.identity.actor_hash(first), self.identity.csrf(first)
        self.assertRegex(actor, r'^[0-9a-f]{64}$')
        self.assertRegex(csrf, r'^[0-9a-f]{64}$')
        self.assertEqual(actor, self.make_identity().actor_hash(first))
        self.assertEqual(csrf, self.make_identity().csrf(first))
        self.assertEqual(len({actor, csrf, first.rsplit('.', 1)[1]}), 3)
        self.assertNotEqual(actor, self.identity.actor_hash(second))
        self.assertNotEqual(csrf, self.identity.csrf(second))
        self.assertEqual(COOKIE_NAME, '__Host-explorer-trial')
        self.assertNotIn('a' * 32, repr(self.identity))

    def test_tampering_format_and_other_key_rejected(self):
        cookie = self.identity.issue_cookie()
        parts = cookie.split('.')
        parts[2] = ('0' if parts[2][0] != '0' else '1') + parts[2][1:]
        changed_nonce = '.'.join(parts)
        for value in (None, '', 'x' * 10000, cookie + '\n', cookie + 'x',
                      changed_nonce,
                      cookie.replace('v1.', 'v2.', 1), cookie.replace('.1800000000.', '.1800000001.'),
                      cookie[:-1] + ('0' if cookie[-1] != '0' else '1'),
                      cookie[:14] + 'z' + cookie[15:], cookie.upper()):
            with self.subTest(value_type=type(value).__name__):
                for operation in (self.identity.actor_hash, self.identity.csrf):
                    with self.assertRaises(InvalidTrialIdentity):
                        operation(value)
        other = TrialIdentity(b'b' * 32, 'https://example.test', clock=lambda: self.now)
        with self.assertRaises(InvalidTrialIdentity):
            other.actor_hash(cookie)

    def test_expiry_and_future_cookie(self):
        cookie = self.identity.issue_cookie()
        self.now += COOKIE_TTL - 1
        self.identity.actor_hash(cookie)
        self.now += 1
        with self.assertRaises(InvalidTrialIdentity):
            self.identity.actor_hash(cookie)
        self.now = 1_799_999_999
        with self.assertRaises(InvalidTrialIdentity):
            self.identity.csrf(cookie)

    def test_direct_peer_ignores_forged_forwarding(self):
        original = self.identity.network_hash('192.0.2.1')
        for forwarded in (None, '198.51.100.7', 'invalid', '1.1.1.1, 2.2.2.2'):
            self.assertEqual(original, self.identity.network_hash('192.0.2.1', forwarded))
        self.assertNotEqual(original, self.identity.network_hash('192.0.2.2'))

    def test_ipv6_rotation_and_mapped_normalization(self):
        first = self.identity.network_hash('2001:db8:1:2::1')
        self.assertEqual(first, self.identity.network_hash('2001:db8:1:2:ffff:ffff:ffff:ffff'))
        self.assertNotEqual(first, self.identity.network_hash('2001:db8:1:3::1'))
        self.assertEqual(self.identity.network_hash('192.0.2.1'),
                         self.identity.network_hash('::ffff:192.0.2.1'))

    def test_trusted_proxy_requires_single_valid_forwarded_ip(self):
        trusted = self.make_identity(trusted_proxies=('192.0.2.0/24', '2001:db8:1::/48'))
        target = self.identity.network_hash('198.51.100.7')
        for peer in ('192.0.2.1', '::ffff:192.0.2.1', '2001:db8:1::1'):
            self.assertEqual(target, trusted.network_hash(peer, '198.51.100.7'))
            for value in (None, '', '198.51.100.7, 198.51.100.8', ' 198.51.100.7',
                          '[2001:db8::1]', '198.51.100.7:443', 'fe80::1%en0'):
                with self.assertRaises(InvalidTrialIdentity):
                    trusted.network_hash(peer, value)
        self.assertEqual(self.identity.network_hash('192.0.3.1'),
                         trusted.network_hash('192.0.3.1', '198.51.100.7'))
        mapped = self.make_identity(trusted_proxies=('::ffff:192.0.2.0/120',))
        self.assertEqual(target, mapped.network_hash('192.0.2.1', '198.51.100.7'))

    def test_invalid_peer_and_config(self):
        for peer in (None, '', 'bad', '127.0.0.1, 127.0.0.2', 'fe80::1%en0', '127.0.0.1/32'):
            with self.assertRaises(InvalidTrialIdentity):
                self.identity.network_hash(peer)
        for cidr in ('127.0.0.1', '192.0.2.1/24', 'bad', 'fe80::%en0/64'):
            with self.assertRaises(ValueError):
                self.make_identity(trusted_proxies=(cidr,))
        for secret in (b'', b'x' * 31, b'x' * 33, 'x' * 32):
            with self.assertRaises(ValueError):
                TrialIdentity(secret, 'https://example.test')
        with self.assertRaises(ValueError):
            TrialIdentity(b'x' * 32, 'http://example.test')

    def test_origin_and_fetch_site_matrix(self):
        for site in (None, 'same-origin', 'none'):
            self.assertTrue(self.identity.valid_origin(None, site))
            self.assertFalse(self.identity.valid_origin(None, site, write=True))
            self.assertTrue(self.identity.valid_origin('https://example.test', site, write=True))
            for origin in ('', 'null', 'https://evil.test', 'https://example.test/', 'https://EXAMPLE.test'):
                self.assertFalse(self.identity.valid_origin(origin, site))
        for site in ('cross-site', 'same-site', '', 'Same-Origin'):
            self.assertFalse(self.identity.valid_origin(None, site))
            self.assertFalse(self.identity.valid_origin('https://example.test', site, write=True))


if __name__ == '__main__':
    unittest.main()
