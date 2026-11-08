"""WebSocket событий (п. 2.2, 12.1): ws/events/?token=<JWT access>."""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


@database_sync_to_async
def _user(token):
    from rest_framework_simplejwt.tokens import AccessToken

    from .models import User

    try:
        return User.objects.get(id=AccessToken(token)["user_id"], is_active=True)
    except Exception:
        return None


class EventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        token = parse_qs(self.scope["query_string"].decode()).get("token", [""])[0]
        self.user = await _user(token)
        if not self.user:
            await self.close(code=4401)
            return
        self.groups_joined = ["all", f"user_{self.user.id}"]
        for g in self.groups_joined:
            await self.channel_layer.group_add(g, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        for g in getattr(self, "groups_joined", []):
            await self.channel_layer.group_discard(g, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def event(self, message):
        await self.send_json(message["event"])
