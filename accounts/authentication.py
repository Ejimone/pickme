"""Clerk session JWT verification for DRF.

Verifies RS256 tokens against Clerk's JWKS (fetched once and cached by
PyJWKClient), then loads — or JIT-provisions — the local User row keyed by
the token's `sub` claim. Webhooks are the primary profile sync path; JIT
creation only covers the gap before the first webhook fires.
"""

import threading

import jwt
from django.conf import settings
from rest_framework import authentication, exceptions

_jwks_client = None
_jwks_lock = threading.Lock()


def get_jwks_client():
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None or _jwks_client.uri != settings.CLERK_JWKS_URL:
            if not settings.CLERK_JWKS_URL:
                raise exceptions.AuthenticationFailed(
                    "Clerk is not configured (CLERK_JWKS_URL missing)."
                )
            _jwks_client = jwt.PyJWKClient(
                settings.CLERK_JWKS_URL, cache_keys=True, lifespan=3600
            )
        return _jwks_client


def verify_clerk_token(token):
    """Return the decoded claims of a valid Clerk session JWT, or raise."""
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.CLERK_ISSUER or None,
            options={
                "require": ["sub", "exp", "iat"],
                "verify_iss": bool(settings.CLERK_ISSUER),
                "verify_aud": False,  # Clerk session tokens carry azp, not aud
            },
        )
    except jwt.PyJWTError as exc:
        raise exceptions.AuthenticationFailed(f"Invalid token: {exc}")

    authorized_parties = settings.CLERK_AUTHORIZED_PARTIES
    azp = claims.get("azp")
    if authorized_parties and azp and azp not in authorized_parties:
        raise exceptions.AuthenticationFailed("Invalid token: azp not allowed")
    return claims


class ClerkJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed(
                "Invalid Authorization header format."
            )

        claims = verify_clerk_token(header[1].decode())
        user = self.get_or_provision_user(claims)
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User is inactive.")
        return (user, claims)

    @staticmethod
    def get_or_provision_user(claims):
        from accounts.models import User

        clerk_user_id = claims["sub"]
        try:
            return User.objects.get(clerk_user_id=clerk_user_id)
        except User.DoesNotExist:
            # Session tokens don't carry email by default; use a resolvable
            # placeholder until the Clerk webhook syncs the real profile.
            email = claims.get("email") or f"{clerk_user_id}@pending.clerk.local"
            return User.objects.create_user(
                email=email,
                clerk_user_id=clerk_user_id,
                full_name=claims.get("name", ""),
            )

    def authenticate_header(self, request):
        return self.keyword
