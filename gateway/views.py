import asyncio
import uuid

import openpyxl
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from openpyxl.utils import get_column_letter

from .consumers import CONNECTED_NODES
from .models import ExclusionRule, GatewayNode

REQUEST_TIMEOUT = 20  # segundos: el agente ahora encadena MariaDB + SQL Server

staff_required = user_passes_test(lambda u: u.is_staff)


class StockFetchError(Exception):
    """Error al pedir el stock por el túnel: (código HTTP, clave de error)."""

    def __init__(self, status, error):
        self.status = status
        self.error = error


def _fetch_stock_rows():
    """Pide el stock actual a equipo X por el túnel. Lanza StockFetchError si
    el nodo no está configurado/conectado, si responde con error, o si no
    contesta a tiempo. Usado tanto por la API JSON como por la exportación."""
    node = GatewayNode.objects.filter(active=True).first()
    if node is None:
        raise StockFetchError(503, 'no_node_configured')

    channel_name = CONNECTED_NODES.get(node.slug)
    if not channel_name:
        raise StockFetchError(503, 'node_offline')

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
        raise StockFetchError(504, 'timeout')

    payload = message['payload']
    if not payload.get('ok', True):
        raise StockFetchError(502, payload.get('error', 'agent_error'))
    return payload.get('rows', [])


@login_required
def stock_view(request):
    return render(request, 'gateway/stock.html')


@login_required
@require_GET
def stock_actual_api(request):
    try:
        rows = _fetch_stock_rows()
    except StockFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'rows': rows})


@login_required
@require_GET
def stock_export_view(request):
    try:
        rows = _fetch_stock_rows()
    except StockFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Stock'
    sheet.append(['Artículo', 'Stock'])
    for row in rows:
        sheet.append([row.get('idArticulo'), row.get('Suma_Stock')])
    for col, width in ((1, 20), (2, 14)):
        sheet.column_dimensions[get_column_letter(col)].width = width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="stock.xlsx"'
    workbook.save(response)
    return response


@staff_required
def config_view(request):
    rules = ExclusionRule.objects.filter(activo=True)
    return render(request, 'gateway/config.html', {
        'articulos': rules.filter(tipo=ExclusionRule.Tipo.ARTICULO),
        'familias': rules.filter(tipo=ExclusionRule.Tipo.FAMILIA),
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
