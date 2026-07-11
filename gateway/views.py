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
from .models import ExclusionRule, GatewayNode, SupplierCategory
from .permissions import page_required

REQUEST_TIMEOUT = 20  # segundos: el agente encadena varias consultas SQL

staff_required = user_passes_test(lambda u: u.is_staff)


class GatewayFetchError(Exception):
    """Error al pedir datos por el túnel: (código HTTP, clave de error)."""

    def __init__(self, status, error):
        self.status = status
        self.error = error


def _ask_gateway(query, params, timeout=REQUEST_TIMEOUT):
    """Pide `query` a equipo X por el túnel y espera la respuesta. Lanza
    GatewayFetchError si el nodo no está configurado/conectado, si responde
    con error, o si no contesta a tiempo. Compartido por todas las páginas
    que piden datos en vivo (Stock, Stock Tabla...)."""
    node = GatewayNode.objects.filter(active=True).first()
    if node is None:
        raise GatewayFetchError(503, 'no_node_configured')

    channel_name = CONNECTED_NODES.get(node.slug)
    if not channel_name:
        raise GatewayFetchError(503, 'node_offline')

    async def _ask():
        channel_layer = get_channel_layer()
        reply_channel = await channel_layer.new_channel()
        request_id = str(uuid.uuid4())
        await channel_layer.send(channel_name, {
            'type': 'gateway.query',
            'request_id': request_id,
            'query': query,
            'params': params,
            'reply_channel': reply_channel,
        })
        try:
            return await asyncio.wait_for(channel_layer.receive(reply_channel), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    message = async_to_sync(_ask)()
    if message is None:
        raise GatewayFetchError(504, 'timeout')

    payload = message['payload']
    if not payload.get('ok', True):
        raise GatewayFetchError(502, payload.get('error', 'agent_error'))
    return payload.get('rows', [])


def _fetch_stock_rows():
    exclusion_rules = list(ExclusionRule.objects.filter(activo=True).values('tipo', 'valor'))
    return _ask_gateway('stock_actual', {'exclusion_rules': exclusion_rules})


def _fetch_stock_tabla_rows():
    supplier_categories = list(
        SupplierCategory.objects.filter(activo=True).values('codpro', 'organizacion', 'categoria')
    )
    return _ask_gateway('stock_tabla', {'supplier_categories': supplier_categories})


@login_required
def home_view(request):
    return render(request, 'gateway/home.html')


@page_required('stock')
def stock_view(request):
    return render(request, 'gateway/stock.html')


@page_required('stock')
@require_GET
def stock_actual_api(request):
    try:
        rows = _fetch_stock_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'rows': rows})


@page_required('stock')
@require_GET
def stock_export_view(request):
    try:
        rows = _fetch_stock_rows()
    except GatewayFetchError as exc:
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


@page_required('stock-tabla')
def stock_tabla_view(request):
    return render(request, 'gateway/stock_tabla.html')


@page_required('stock-tabla')
@require_GET
def stock_tabla_api(request):
    try:
        rows = _fetch_stock_tabla_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'rows': rows})


@page_required('stock-tabla')
@require_GET
def stock_tabla_export_view(request):
    try:
        rows = _fetch_stock_tabla_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Stock Tabla'
    if rows:
        columns = list(rows[0].keys())
        sheet.append(columns)
        for row in rows:
            sheet.append([row.get(col) for col in columns])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="stock_tabla.xlsx"'
    workbook.save(response)
    return response


@staff_required
def config_view(request):
    rules = ExclusionRule.objects.filter(activo=True)
    return render(request, 'gateway/config.html', {
        'articulos': rules.filter(tipo=ExclusionRule.Tipo.ARTICULO),
        'familias': rules.filter(tipo=ExclusionRule.Tipo.FAMILIA),
        'supplier_categories': SupplierCategory.objects.filter(activo=True),
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


@staff_required
@require_POST
def config_save_supplier_category(request):
    supplier_id = request.POST.get('id')
    codpro = (request.POST.get('codpro') or '').strip()
    organizacion = (request.POST.get('organizacion') or '').strip()
    categoria_raw = (request.POST.get('categoria') or '').strip()

    if codpro and categoria_raw.isdigit():
        categoria = int(categoria_raw)
        if supplier_id:
            SupplierCategory.objects.filter(pk=supplier_id).update(
                codpro=codpro, organizacion=organizacion, categoria=categoria,
            )
        else:
            SupplierCategory.objects.update_or_create(
                codpro=codpro,
                defaults={'organizacion': organizacion, 'categoria': categoria, 'activo': True},
            )
    return redirect('gateway:config')


@staff_required
@require_POST
def config_delete_supplier_category(request, supplier_id):
    SupplierCategory.objects.filter(pk=supplier_id).update(activo=False)
    return redirect('gateway:config')
