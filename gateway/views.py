import asyncio
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .consumers import CONNECTED_NODES
from .models import GatewayNode

REQUEST_TIMEOUT = 10  # segundos


@staff_member_required
def stock_view(request):
    return render(request, 'gateway/stock.html')


@staff_member_required
@require_GET
def stock_actual_api(request):
    node = GatewayNode.objects.filter(active=True).first()
    if node is None:
        return JsonResponse({'error': 'no_node_configured'}, status=503)

    channel_name = CONNECTED_NODES.get(node.slug)
    if not channel_name:
        return JsonResponse({'error': 'node_offline'}, status=503)

    async def _ask():
        channel_layer = get_channel_layer()
        reply_channel = await channel_layer.new_channel()
        request_id = str(uuid.uuid4())
        await channel_layer.send(channel_name, {
            'type': 'gateway.query',
            'request_id': request_id,
            'query': 'stock_actual',
            'params': {},
            'reply_channel': reply_channel,
        })
        try:
            return await asyncio.wait_for(channel_layer.receive(reply_channel), timeout=REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            return None

    message = async_to_sync(_ask)()
    if message is None:
        return JsonResponse({'error': 'timeout'}, status=504)

    payload = message['payload']
    if not payload.get('ok', True):
        return JsonResponse({'error': payload.get('error', 'agent_error')}, status=502)
    return JsonResponse({'rows': payload.get('rows', [])})
