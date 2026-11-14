"""Verify Google OIDC ID tokens; HTTP state/PKCE/CSRF remains caller responsibility.

No DB, session issuance, claims logging or identity linking occurs here.
"""
from dataclasses import dataclass, field
import hmac
from google.auth import exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token


class InvalidGoogleIdentity(ValueError):
    """Public-safe validation failure; never include tokens or provider exceptions."""


@dataclass(frozen=True)
class GoogleIdentity:
    issuer: str
    subject: str = field(repr=False)
    email: str | None = field(default=None, repr=False)


def verify_google_identity(token: str, *, client_id: str, expected_nonce: str,
                           request=None) -> GoogleIdentity:
    """Verify signature/issuer/audience/time with google-auth, then bind nonce.

    expected_nonce must come from a single-use server login transaction, never
    from a second client-provided value. This function alone is not a login flow.
    request injection permits offline signed-token tests, not unchecked claims.
    """
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("Google client ID is required")
    if not isinstance(expected_nonce, str) or not expected_nonce:
        raise ValueError("Server login nonce is required")
    if not isinstance(token, str) or not token or len(token) > 16384:
        raise InvalidGoogleIdentity("Invalid Google identity")
    transport = request if request is not None else Request()

    def bounded_request(*args, **kwargs):
        kwargs["timeout"] = 10
        return transport(*args, **kwargs)

    try:
        claims = id_token.verify_oauth2_token(token, bounded_request, audience=client_id)
        nonce = claims.get("nonce")
        subject = claims.get("sub")
        if (claims.get("aud") != client_id
                or claims.get("azp", client_id) != client_id
                or not isinstance(nonce, str)
                or not hmac.compare_digest(nonce.encode(), expected_nonce.encode())
                or not isinstance(subject, str) or not subject or len(subject) > 255):
            raise InvalidGoogleIdentity("Invalid Google identity")
        email = claims.get("email") if claims.get("email_verified") is True else None
        if email is not None and not isinstance(email, str):
            raise InvalidGoogleIdentity("Invalid Google identity")
        return GoogleIdentity("https://accounts.google.com", subject, email)
    except (ValueError, TypeError, KeyError, exceptions.GoogleAuthError):
        raise InvalidGoogleIdentity("Invalid Google identity") from None
