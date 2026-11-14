"""Stateless, purpose-separated identities for nonpersistent public chat.

Only digests leave this boundary. Callers must not persist cookies or raw IPs.
"""
import hashlib
import hmac
import ipaddress
import re
import secrets
import time

from security.login_flow import validate_origin

COOKIE_NAME = '__Host-explorer-trial'
COOKIE_TTL = 30 * 86400
_COOKIE = re.compile(r'v1\.([0-9]{1,12})\.([0-9a-f]{64})\.([0-9a-f]{64})', re.ASCII)


class InvalidTrialIdentity(Exception):
    """Unusable identity; deliberately contains no request values."""


def _address(value):
    if (not isinstance(value, str) or len(value) > 45 or '%' in value):
        raise InvalidTrialIdentity('Invalid network identity')
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise InvalidTrialIdentity('Invalid network identity') from None
    return address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address


class TrialIdentity:
    def __init__(self, secret: bytes, origin: str,
                 trusted_proxies: tuple[str, ...] = (), clock=time.time):
        if not isinstance(secret, bytes) or len(secret) != 32:
            raise ValueError('Trial identity requires a 32-byte secret')
        self._secret = secret
        self._origin = validate_origin(origin)
        networks = []
        for cidr in trusted_proxies:
            try:
                if not isinstance(cidr, str) or '/' not in cidr or '%' in cidr:
                    raise ValueError
                network = ipaddress.ip_network(cidr, strict=True)
                if isinstance(network, ipaddress.IPv6Network) and network.network_address.ipv4_mapped:
                    if network.prefixlen < 96:
                        raise ValueError
                    network = ipaddress.ip_network((network.network_address.ipv4_mapped, network.prefixlen - 96))
                networks.append(network)
            except ValueError:
                raise ValueError('Invalid trusted proxy CIDR') from None
        self._trusted_proxies = tuple(networks)
        self._clock = clock

    def _digest(self, purpose, value):
        return hmac.new(self._secret, b'explorer:trial:v1:' + purpose + b'\0' + value.encode('ascii'),
                        hashlib.sha256).hexdigest()

    def issue_cookie(self) -> str:
        issued = int(self._clock())
        if not 0 <= issued < 10**12:
            raise InvalidTrialIdentity('Invalid identity clock')
        payload = f'v1.{issued}.{secrets.token_hex(32)}'
        return payload + '.' + self._digest(b'cookie', payload)

    def _verify(self, cookie):
        if not isinstance(cookie, str) or len(cookie) > 145:
            raise InvalidTrialIdentity('Invalid trial cookie')
        match = _COOKIE.fullmatch(cookie)
        if match is None:
            raise InvalidTrialIdentity('Invalid trial cookie')
        issued_text, _, signature = match.groups()
        payload = cookie.rsplit('.', 1)[0]
        if not hmac.compare_digest(signature, self._digest(b'cookie', payload)):
            raise InvalidTrialIdentity('Invalid trial cookie')
        issued = int(issued_text)
        age = self._clock() - issued
        if issued_text != str(issued) or not 0 <= age < COOKIE_TTL:
            raise InvalidTrialIdentity('Expired or invalid trial cookie')
        return payload

    def actor_hash(self, cookie) -> str:
        return self._digest(b'actor', self._verify(cookie))

    def csrf(self, cookie) -> str:
        return self._digest(b'csrf', self._verify(cookie))

    def network_hash(self, peer: str, forwarded_ip: str | None = None) -> str:
        address = _address(peer)
        if any(address.version == network.version and address in network
               for network in self._trusted_proxies):
            address = _address(forwarded_ip)
        prefix = 32 if address.version == 4 else 64
        network = ipaddress.ip_network((address, prefix), strict=False)
        return self._digest(b'network', str(network))

    def valid_origin(self, origin, sec_fetch_site, write=False) -> bool:
        if sec_fetch_site not in (None, 'same-origin', 'none'):
            return False
        if origin is None:
            return not write
        return origin == self._origin
