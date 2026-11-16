import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

from apps.accounts.consumers import EventsConsumer  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_app,
    "websocket": URLRouter([path("ws/events/", EventsConsumer.as_asgi())]),
})
