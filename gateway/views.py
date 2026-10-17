import asyncio
import datetime
import json
import time
import uuid
from functools import wraps

import openpyxl
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import informes as informes_catalogo
from .consumers import CONNECTED_NODES
from .models import (
    ExclusionRule, GatewayNode, HuecoTipoCategoria, StockTablaConfig, SupplierCategory, UbicacionAlmacen,
)
from .permissions import get_accessible_pages, page_required
from .tabs import check_and_register

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


def require_post_async(view_func):
    """Equivalente async de @require_POST, para config_save_stock_tabla
    (necesita ser async para poder avisar a equipo X al momento)."""
    @wraps(view_func)
    async def wrapped(request, *args, **kwargs):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
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


async def _fetch_stock_tabla_data():
    """Devuelve (columns, rows) — columnar, no una lista de diccionarios:
    con ~44 columnas por artículo, repetir el nombre de cada una en cada
    fila infla el JSON que cruza el túnel un ~65% de más (medido). El
    frontend (stock_tabla.html) y el export a Excel reconstruyen lo que
    necesiten a partir de estas dos listas."""
    supplier_categories = await sync_to_async(list)(
        SupplierCategory.objects.filter(activo=True).values('codpro', 'organizacion', 'categoria')
    )
    payload = await _ask_gateway('stock_tabla', {
        'supplier_categories': supplier_categories,
        'ubicaciones': await _fetch_ubicaciones(),
        'tipos_excluidos': await _fetch_tipos_excluidos(),
        'activo': await sync_to_async(lambda: StockTablaConfig.get_solo().activo)(),
    })
    await _registrar_tipos_hueco_nuevos(payload.get('tipos_hueco_descubiertos', []))
    return payload.get('columns', []), payload.get('rows', [])


@login_required
def home_view(request):
    return render(request, 'gateway/home.html')


@login_required
@require_POST
def tab_heartbeat_view(request):
    """Latido de gateway/base.html: si el usuario tiene single_tab_only,
    solo una pestaña puede quedar registrada como activa a la vez (ver
    gateway/tabs.py). Usuarios sin esa marca siempre reciben ok=True."""
    single_tab_only = getattr(getattr(request.user, 'profile', None), 'single_tab_only', False)
    tab_id = (request.POST.get('tab_id') or '').strip()
    if not single_tab_only or not tab_id:
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': check_and_register(request.user.pk, tab_id)})


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
        columns, rows = await _fetch_stock_tabla_data()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({'columns': columns, 'rows': rows})


@page_required('stock-tabla')
@require_get_async
async def stock_tabla_export_view(request):
    try:
        columns, rows = await _fetch_stock_tabla_data()
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Stock Tabla'
    if columns:
        sheet.append(columns)
        for row in rows:
            sheet.append(row)

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


@page_required('config-stock-tabla')
def config_stock_tabla_view(request):
    return render(request, 'gateway/config_stock_tabla.html', {
        'config': StockTablaConfig.get_solo(),
    })


@page_required('config-stock-tabla')
@require_post_async
async def config_save_stock_tabla(request):
    """Guarda el interruptor y avisa a equipo X al momento (query
    'stock_tabla_config') — si el nodo está desconectado, no pasa nada:
    el valor ya quedó en BD y viajará en la siguiente petición real de
    Stock Tabla (ver _fetch_stock_tabla_data)."""
    activo = request.POST.get('activo') == 'on'
    await sync_to_async(StockTablaConfig.objects.update_or_create)(pk=1, defaults={'activo': activo})
    try:
        await _ask_gateway('stock_tabla_config', {'activo': activo}, timeout=5)
    except GatewayFetchError:
        pass
    return redirect('gateway:config_stock_tabla')


# =============================================================================
# Informes (réplica web de Informe Susana / Informe Cobros / Informe Almacén)
# Catálogo en gateway/informes.py; conjuntos de datos en edge_agent/informes.py.
# =============================================================================

# Algunos conjuntos tardan 15-20 s la primera vez (facturas, ventas): el
# agente los cachea después, pero la primera petición necesita más margen
# que las 20 s de Stock.
INFORMES_TIMEOUT = 120
# Caché corta en el portal: varias personas abriendo la misma página no
# hacen viajar los mismos megas por el túnel una y otra vez.
INFORMES_CACHE_SEGUNDOS = 60
_INFORMES_CACHE = {}


def _resolver_anios(objeto):
    """Sustituye {Y0}..{Y3} (año actual y tres anteriores) en el catálogo:
    las columnas de Pedidos Clientes se llaman con el año real, como en el
    modelo de Power BI."""
    anio = datetime.date.today().year
    texto = json.dumps(objeto, ensure_ascii=False)
    for i in range(4):
        texto = texto.replace('{Y%d}' % i, str(anio - i))
    return json.loads(texto)


def _acceso_informe(user, pagina):
    slug = informes_catalogo.page_slug(pagina)
    return any(page.slug == slug for page in get_accessible_pages(user))


async def _fetch_dataset(nombre, refrescar=False):
    entrada = _INFORMES_CACHE.get(nombre)
    if entrada and not refrescar and time.time() - entrada[0] < INFORMES_CACHE_SEGUNDOS:
        return entrada[1]
    if nombre == 'stock_tabla':
        # Mismo cálculo que la página Stock Tabla (cachés de fondo del agente).
        columnas, filas = await _fetch_stock_tabla_data()
        datos = {'columns': columnas, 'rows': filas, 'dicts': {}, 'updated_at': None}
    else:
        supplier_categories = await sync_to_async(list)(
            SupplierCategory.objects.filter(activo=True).values('codpro', 'organizacion', 'categoria')
        )
        payload = await _ask_gateway('dataset', {
            'name': nombre,
            'refrescar': refrescar,
            'ubicaciones': await _fetch_ubicaciones(),
            'tipos_excluidos': await _fetch_tipos_excluidos(),
            'supplier_categories': supplier_categories,
        }, timeout=INFORMES_TIMEOUT)
        datos = {clave: payload.get(clave) for clave in ('columns', 'rows', 'dicts', 'updated_at', 'query_seconds')}
    _INFORMES_CACHE[nombre] = (time.time(), datos)
    return datos


@login_required
def informe_view(request, slug):
    pagina = informes_catalogo.PAGINAS_POR_SLUG.get(slug)
    if pagina is None:
        raise Http404
    if not _acceso_informe(request.user, pagina):
        raise PermissionDenied('No tienes acceso a esta página.')
    return render(request, 'gateway/informe.html', {
        'pagina': pagina,
        'spec': _resolver_anios(pagina),
        'datos_url': reverse('gateway:informe_datos', args=[slug]),
    })


@require_get_async
async def informe_datos_api(request, slug):
    pagina = informes_catalogo.PAGINAS_POR_SLUG.get(slug)
    if pagina is None:
        raise Http404

    def _comprobar():
        if not request.user.is_authenticated:
            return 401
        return 200 if _acceso_informe(request.user, pagina) else 403

    estado = await sync_to_async(_comprobar)()
    if estado != 200:
        return JsonResponse({'error': 'forbidden' if estado == 403 else 'login'}, status=estado)

    refrescar = request.GET.get('refrescar') == '1'
    resultado, errores = {}, {}
    for nombre in informes_catalogo.datasets_de(pagina):
        try:
            resultado[nombre] = await _fetch_dataset(nombre, refrescar)
        except GatewayFetchError as exc:
            errores[nombre] = exc.error
    if not resultado:
        primer_error = next(iter(errores.values()), 'agent_error')
        status = 503 if primer_error in ('node_offline', 'no_node_configured') else 502
        return JsonResponse({'error': primer_error, 'errores': errores}, status=status)
    return JsonResponse({'datasets': resultado, 'errores': errores})


@page_required('config-origenes')
def config_origenes_view(request):
    return render(request, 'gateway/config_origenes.html')


@page_required('config-origenes')
@require_get_async
async def config_origenes_api(request):
    try:
        payload = await _ask_gateway('sources_status', {'comprobar': True}, timeout=60)
    except GatewayFetchError as exc:
        return JsonResponse({'error': exc.error}, status=exc.status)
    return JsonResponse({
        'config': payload.get('config', {}),
        'status': payload.get('status', {}),
        'datasets': payload.get('datasets', []),
    })
