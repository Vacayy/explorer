"""Real signed synthetic JWTs; no Google network or production credentials."""
import json
import time
import unittest
from types import SimpleNamespace
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from google.auth import crypt, jwt
from security.google_identity import verify_google_identity, InvalidGoogleIdentity


class GoogleIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        cls.signer = crypt.RSASigner.from_string(private, key_id="fixture")
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def transport(self, url, **kwargs):
        self.assertEqual(url, "https://www.googleapis.com/oauth2/v1/certs")
        self.assertEqual(kwargs["timeout"], 10)
        return SimpleNamespace(status=200, data=json.dumps({"fixture": self.public}).encode())

    def token(self, **changes):
        now = int(time.time())
        claims = dict(iss="https://accounts.google.com", sub="fixture-subject", aud="fixture-client",
                      iat=now-1, exp=now+120, nonce="server-nonce", email="fixture@example.invalid",
                      email_verified=True)
        claims.update(changes)
        return jwt.encode(self.signer, claims).decode()

    def verify(self, token):
        return verify_google_identity(token, client_id="fixture-client", expected_nonce="server-nonce",
                                      request=self.transport)

    def test_signed_token_and_issuer_normalization(self):
        for issuer in ("accounts.google.com", "https://accounts.google.com"):
            identity = self.verify(self.token(iss=issuer))
            self.assertEqual(identity.issuer, "https://accounts.google.com")
            self.assertEqual(identity.subject, "fixture-subject")
            self.assertNotIn(identity.subject, repr(identity))
            self.assertNotIn(identity.email, repr(identity))

    def test_rejects_wrong_claims_and_mismatched_login_nonce(self):
        for changes in ({"aud": "other-client"}, {"iss": "https://attacker.invalid"},
                        {"exp": int(time.time())-10}, {"nonce": "other-login"}, {"nonce": None},
                        {"sub": ""}, {"azp": "other-client"}, {"iat": int(time.time())+1000}):
            with self.subTest(changes=list(changes)), self.assertRaises(InvalidGoogleIdentity):
                self.verify(self.token(**changes))

    def test_rejects_tampered_signature_and_truncated_token_without_echo(self):
        token = self.token()
        parts = token.split(".")
        parts[2] = ("a" if parts[2][0] != "a" else "b") + parts[2][1:]
        for invalid in (".".join(parts), "not-a-token", "x"*16385):
            with self.assertRaises(InvalidGoogleIdentity) as caught:
                self.verify(invalid)
            self.assertEqual(str(caught.exception), "Invalid Google identity")

    def test_unverified_email_is_not_an_identity_key(self):
        identity = self.verify(self.token(email_verified=False))
        self.assertIsNone(identity.email)
        self.assertEqual(identity.subject, "fixture-subject")

    def test_missing_server_configuration_is_rejected_before_network(self):
        for client, nonce in (("", "n"), ("c", "")):
            with self.assertRaises(ValueError):
                verify_google_identity("unused", client_id=client, expected_nonce=nonce,
                                       request=lambda *a, **k: self.fail("unexpected network"))
