import asyncio
import uuid
from functools import wraps

import openpyxl
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .consumers import CONNECTED_NODES
from .models import ExclusionRule, GatewayNode, HuecoTipoCategoria, SupplierCategory, UbicacionAlmacen
from .permissions import page_required

REQUEST_TIMEOUT = 20  # segundos: el agente encadena varias consultas SQL


def require_get_async(view_func):
    """Equivalente async de @require_GET (ese decorador de Django no
    soporta vistas async en esta versión)."""
    @wraps(view_func)
    async def wrapped(request, *args, **kwargs):
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
        return await view_func(request, *args, **kwargs)
    return wrapped


class GatewayFetchError(Exception):
    """Error al pedir datos por el túnel: (código HTTP, clave de error)."""

    def __init__(self, status, error):
        self.status = status
        self.error = error


async def _ask_gateway(query, params, timeout=REQUEST_TIMEOUT):
    """Pide `query` a equipo X por el túnel y espera la respuesta. Lanza
    GatewayFetchError si el nodo no está configurado/conectado, si responde
    con error, o si no contesta a tiempo. Compartido por todas las páginas
    que piden datos en vivo (Stock, Stock Tabla...).

    Async nativa a propósito: antes esto se llamaba desde una vista
    síncrona vía async_to_sync, lo que la obligaba a correr en el hilo
    único "thread-sensitive" que usa Django para código síncrono — el
    mismo hilo que necesita el consumer de Channels para reautenticar al
    agente si reconecta. Bloquearlo hasta 20s de golpe coincidía siempre
    con las caídas del túnel que veíamos en producción. Al ser la vista
    entera async, todo corre en el mismo bucle de eventos sin bloquear
    ningún hilo compartido.
    """
    node = await sync_to_async(GatewayNode.objects.filter(active=True).first)()
    if node is None:
        raise GatewayFetchError(503, 'no_node_configured')

    channel_name = CONNECTED_NODES.get(node.slug)
    if not channel_name:
        raise GatewayFetchError(503, 'node_offline')

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
        message = await asyncio.wait_for(channel_layer.receive(reply_channel), timeout=timeout)
    except asyncio.TimeoutError:
        raise GatewayFetchError(504, 'timeout')

    payload = message['payload']
    if not payload.get('ok', True):
        raise GatewayFetchError(502, payload.get('error', 'agent_error'))
    return payload


async def _fetch_ubicaciones():
    return await sync_to_async(list)(
        UbicacionAlmacen.objects.filter(activo=True).values('id_centro', 'id_almacen', 'id_zona')
    )


async def _fetch_tipos_excluidos():
    return await sync_to_async(list)(
        HuecoTipoCategoria.objects.filter(activo=False).values_list('id_tipo_hueco', flat=True)
    )


async def _fetch_stock_rows():
    exclusion_rules = await sync_to_async(list)(
        ExclusionRule.objects.filter(activo=True).values('tipo', 'valor')
    )
    payload = await _ask_gateway('stock_actual', {
        'exclusion_rules': exclusion_rules,
        'ubicaciones': await _fetch_ubicaciones(),
        'tipos_excluidos': await _fetch_tipos_excluidos(),
    })
    await _registrar_tipos_hueco_nuevos(payload.get('tipos_hueco_descubiertos', []))
    return payload.get('rows', [])


async def _registrar_tipos_hueco_nuevos(tipos_vistos):
    """Cualquier tipo de hueco que equipo X vea realmente en la BD y que
    todavía no esté en nuestra configuración se registra automáticamente
    (incluido, salvo el 9 = Salida) para que el usuario lo revise en
    /gateway/config/tipos-hueco/ — nunca se adivina por texto, se usa el
    id real de TipoHueco.idTipoHueco (estable aunque cambie la
    descripción)."""
    existentes = set(await sync_to_async(list)(HuecoTipoCategoria.objects.values_list('id_tipo_hueco', flat=True)))
    for tipo in tipos_vistos or []:
        id_tipo_hueco = tipo.get('id_tipo_hueco')
        if id_tipo_hueco is None or id_tipo_hueco in existentes:
            continue
        await sync_to_async(HuecoTipoCategoria.objects.get_or_create)(
            id_tipo_hueco=id_tipo_hueco,
            defaults={'descripcion': tipo.get('descripcion', ''), 'activo': id_tipo_hueco != 9},
        )
        existentes.add(id_tipo_hueco)


async def _fetch_stock_tabla_rows():
    supplier_categories = await sync_to_async(list)(
        SupplierCategory.objects.filter(activo=True).values('codpro', 'organizacion', 'categoria')
    )
    payload = await _ask_gateway('stock_tabla', {
        'supplier_categories': supplier_categories,
        'ubicaciones': await _fetch_ubicaciones(),
        'tipos_excluidos': await _fetch_tipos_excluidos(),
    })
    await _registrar_tipos_hueco_nuevos(payload.get('tipos_hueco_descubiertos', []))
    return payload.get('rows', [])


@login_required
def home_view(request):
    return render(request, 'gateway/home.html')


@page_required('stock')
def stock_view(request):
    return render(request, 'gateway/stock.html')


@page_required('stock')
@require_get_async
async def stock_actual_api(request):
    try:
        rows = await _fetch_stock_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'rows': rows})


@page_required('stock')
@require_get_async
async def stock_export_view(request):
    try:
        rows = await _fetch_stock_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)

    # Solo Artículo + Stock, a propósito (igual que la pantalla): el
    # cálculo trae más columnas por detrás, pero aquí solo se enseñan
    # las dos que importan.
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Stock'
    sheet.append(['Artículo', 'Stock'])
    for row in rows:
        sheet.append([row.get('idArticulo'), row.get('Stock_Total')])

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
@require_get_async
async def stock_tabla_api(request):
    try:
        rows = await _fetch_stock_tabla_rows()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'rows': rows})


@page_required('stock-tabla')
@require_get_async
async def stock_tabla_export_view(request):
    try:
        rows = await _fetch_stock_tabla_rows()
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


@page_required('config-exclusion')
def config_exclusion_view(request):
    rules = ExclusionRule.objects.filter(activo=True)
    return render(request, 'gateway/config_exclusion.html', {
        'articulos': rules.filter(tipo=ExclusionRule.Tipo.ARTICULO),
        'familias': rules.filter(tipo=ExclusionRule.Tipo.FAMILIA),
    })


@page_required('config-exclusion')
@require_POST
def config_add_rule(request):
    tipo = request.POST.get('tipo')
    valor = (request.POST.get('valor') or '').strip()
    if tipo in ExclusionRule.Tipo.values and valor:
        ExclusionRule.objects.update_or_create(
            tipo=tipo, valor=valor.upper(), defaults={'activo': True},
        )
    return redirect('gateway:config_exclusion')


@page_required('config-exclusion')
@require_POST
def config_delete_rule(request, rule_id):
    ExclusionRule.objects.filter(pk=rule_id).update(activo=False)
    return redirect('gateway:config_exclusion')


@page_required('config-proveedores')
def config_suppliers_view(request):
    return render(request, 'gateway/config_suppliers.html', {
        'supplier_categories': SupplierCategory.objects.filter(activo=True),
    })


@page_required('config-proveedores')
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
    return redirect('gateway:config_suppliers')


@page_required('config-proveedores')
@require_POST
def config_delete_supplier_category(request, supplier_id):
    SupplierCategory.objects.filter(pk=supplier_id).update(activo=False)
    return redirect('gateway:config_suppliers')


@page_required('config-hueco-tipos')
def config_hueco_tipos_view(request):
    return render(request, 'gateway/config_hueco_tipos.html', {
        'hueco_tipos': HuecoTipoCategoria.objects.all(),
    })


@page_required('config-hueco-tipos')
@require_POST
def config_save_hueco_tipos(request):
    incluidos = set(request.POST.getlist('incluido'))
    tipos = list(HuecoTipoCategoria.objects.all())
    for ht in tipos:
        ht.activo = str(ht.id) in incluidos
    HuecoTipoCategoria.objects.bulk_update(tipos, ['activo'])
    return redirect('gateway:config_hueco_tipos')


@page_required('config-ubicaciones')
def config_ubicaciones_view(request):
    return render(request, 'gateway/config_ubicaciones.html', {
        'ubicaciones': UbicacionAlmacen.objects.filter(activo=True),
    })


@page_required('config-ubicaciones')
@require_POST
def config_add_ubicacion(request):
    id_centro = (request.POST.get('id_centro') or '').strip()
    id_almacen = (request.POST.get('id_almacen') or '').strip()
    id_zona = (request.POST.get('id_zona') or '').strip()
    if id_centro.isdigit() and id_almacen.isdigit() and id_zona.isdigit():
        UbicacionAlmacen.objects.update_or_create(
            id_centro=int(id_centro), id_almacen=int(id_almacen), id_zona=int(id_zona),
            defaults={'activo': True},
        )
    return redirect('gateway:config_ubicaciones')


@page_required('config-ubicaciones')
@require_POST
def config_delete_ubicacion(request, ubicacion_id):
    UbicacionAlmacen.objects.filter(pk=ubicacion_id).update(activo=False)
    return redirect('gateway:config_ubicaciones')
