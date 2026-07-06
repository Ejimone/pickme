"""
ASGI config. WebSocket routing (Channels consumers) is added in Stage 4;
until then this serves HTTP only, but already runs under an ASGI server.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
    }
)
