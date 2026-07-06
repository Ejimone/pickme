"""ASGI config: HTTP via Django, WebSockets via Channels with Clerk-JWT auth
on connect (token in the query string, verified like the REST auth class).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from accounts.middleware import JWTAuthMiddleware  # noqa: E402
from chat.routing import websocket_urlpatterns as chat_ws_urls  # noqa: E402
from notifications.routing import (  # noqa: E402
    websocket_urlpatterns as notification_ws_urls,
)
from trips.routing import websocket_urlpatterns as trip_ws_urls  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddleware(
            URLRouter(trip_ws_urls + chat_ws_urls + notification_ws_urls)
        ),
    }
)
