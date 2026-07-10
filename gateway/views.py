import asyncio
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .consumers import CONNECTED_NODES
from .models import ExclusionRule, GatewayNode

REQUEST_TIMEOUT = 20  # segundos: el agente ahora encadena MariaDB + SQL Server

staff_required = user_passes_test(lambda u: u.is_staff)


@login_required
def stock_view(request):
    return render(request, 'gateway/stock.html')


@login_required
@require_GET
def stock_actual_api(request):
    node = GatewayNode.objects.filter(active=True).first()
    if node is None:
        return JsonResponse({'error': 'no_node_configured'}, status=503)

    channel_name = CONNECTED_NODES.get(node.slug)
    if not channel_name:
        return JsonResponse({'error': 'node_offline'}, status=503)

    exclusion_rules = list(
        ExclusionRule.objects.filter(activo=True).values('tipo', 'valor')
    )

    async def _ask():
        channel_layer = get_channel_layer()
        reply_channel = await channel_layer.new_channel()
        request_id = str(uuid.uuid4())
        await channel_layer.send(channel_name, {
            'type': 'gateway.query',
            'request_id': request_id,
            'query': 'stock_actual',
            'params': {'exclusion_rules': exclusion_rules},
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


@staff_required
def config_view(request):
    rules = ExclusionRule.objects.filter(activo=True)
    return render(request, 'gateway/config.html', {
        'articulos': rules.filter(tipo=ExclusionRule.Tipo.ARTICULO),
        'familias': rules.filter(tipo=ExclusionRule.Tipo.FAMILIA),
        'tipo_choices': ExclusionRule.Tipo.choices,
    })


@staff_required
@require_POST
def config_add_rule(request):
    tipo = request.POST.get('tipo')
    valor = (request.POST.get('valor') or '').strip()
    if tipo in ExclusionRule.Tipo.values and valor:
        ExclusionRule.objects.update_or_create(
            tipo=tipo, valor=valor.upper(), defaults={'activo': True},
        )
    return redirect('gateway:config')


@staff_required
@require_POST
def config_delete_rule(request, rule_id):
    ExclusionRule.objects.filter(pk=rule_id).update(activo=False)
    return redirect('gateway:config')
