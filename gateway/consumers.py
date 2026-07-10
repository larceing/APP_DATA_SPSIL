import json
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import GatewayNode

# Registros válidos solo dentro de este proceso (ver limitaciones en el README:
# requieren un único proceso daphne mientras se use InMemoryChannelLayer).
CONNECTED_NODES = {}   # slug -> channel_name del consumer conectado
PENDING_REQUESTS = {}  # request_id -> reply_channel de la vista que espera


class GatewayNodeConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.slug = self.scope['url_route']['kwargs']['slug']
        query = parse_qs(self.scope['query_string'].decode())
        token = (query.get('token') or [''])[0]

        node = await self._authenticate(self.slug, token)
        if node is None:
            await self.close(code=4001)
            return

        self.node = node
        CONNECTED_NODES[self.slug] = self.channel_name
        await self._touch_last_connected()
        await self.accept()

    async def disconnect(self, code):
        if CONNECTED_NODES.get(getattr(self, 'slug', None)) == self.channel_name:
            del CONNECTED_NODES[self.slug]

    async def receive(self, text_data):
        """Frame JSON que llega del socket real de equipo X con la respuesta a una query."""
        payload = json.loads(text_data)
        reply_channel = PENDING_REQUESTS.pop(payload.get('request_id'), None)
        if reply_channel:
            await self.channel_layer.send(reply_channel, {
                'type': 'gateway.reply',
                'payload': payload,
            })

    async def gateway_query(self, event):
        """Invocado vía channel_layer.send(self.channel_name, {"type": "gateway.query", ...})."""
        PENDING_REQUESTS[event['request_id']] = event['reply_channel']
        await self.send(text_data=json.dumps({
            'request_id': event['request_id'],
            'query': event['query'],
            'params': event.get('params', {}),
        }))

    @database_sync_to_async
    def _authenticate(self, slug, token):
        try:
            node = GatewayNode.objects.get(slug=slug, active=True)
        except GatewayNode.DoesNotExist:
            return None
        return node if node.check_token(token) else None

    @database_sync_to_async
    def _touch_last_connected(self):
        self.node.last_connected_at = timezone.now()
        self.node.save(update_fields=['last_connected_at'])
