"""ASGI middleware authenticating WebSocket connections with a Clerk JWT.

Per SYSTEMS-DEEP-DIVE.md: the token comes from the WS query string
(`?token=...`) and runs through the same verification function the DRF
authentication class uses. On any failure `scope["user"]` is anonymous and
consumers close with 4001 before joining a group.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed

from accounts.authentication import ClerkJWTAuthentication, verify_clerk_token


@database_sync_to_async
def _resolve_user(token):
    claims = verify_clerk_token(token)
    user = ClerkJWTAuthentication.get_or_provision_user(claims)
    if not user.is_active:
        raise AuthenticationFailed("User is inactive.")
    return user


class JWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()
        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]
        if token:
            try:
                scope["user"] = await _resolve_user(token)
            except AuthenticationFailed:
                pass  # stays anonymous; consumer rejects with 4001
        return await self.inner(scope, receive, send)
