"""Conjuntos de datos de los informes de Power BI (Informe Susana, Informe
Cobros), traducidos a SQL + Python.

Cada conjunto es una función registrada en DATASETS que devuelve una lista
de diccionarios (una fila por registro, como la tabla del modelo de Power
BI). El portal pide un conjunto por nombre (query `dataset`) y hace en el
navegador lo que en Power BI hacían las segmentaciones y las medidas.

Las consultas SQL son las mismas que las de los Power Query originales
(INC_SPSIL_20261006 / INC_SPSIL_20261002); lo que en M era un cruce con
otra consulta se hace aquí con diccionarios. Ningún host ni hoja va escrito
a mano: todo sale de fuentes.py (variables de entorno).

Solo lectura: ninguna consulta escribe en el ERP ni en Innertia.
"""

import csv
import datetime
import hashlib
import json
import logging
import math
import os
import re
import threading
import time

import fuentes
from db import _query_stock as stock_disponible_innertia
from db import query_hueco_breakdown

log = logging.getLogger('edge_agent')

CACHE_SEGUNDOS = int(os.environ.get('INFORMES_CACHE_SEGUNDOS', '300'))
CACHE_AUX_SEGUNDOS = int(os.environ.get('INFORMES_CACHE_AUX_SEGUNDOS', '900'))
# Cuántos años hacia atrás se cargan las tablas de hechos grandes (las
# consultas originales tenían "YEAR(FECHA) >= 2024" fijo; aquí es móvil).
ANIOS_HISTORICO = int(os.environ.get('INFORMES_ANIOS_HISTORICO', '2'))

DATOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datos')

DATASETS = {}


def dataset(nombre, ttl=None, descripcion=''):
    def registrar(func):
        DATASETS[nombre] = {'func': func, 'ttl': ttl or CACHE_SEGUNDOS, 'descripcion': descripcion}
        return func
    return registrar


# --- Caché por (dataset, parámetros) -----------------------------------------

_CACHE = {}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _clave_cache(nombre, params):
    crudo = json.dumps(params or {}, sort_keys=True, default=str)
    return nombre + ':' + hashlib.sha1(crudo.encode()).hexdigest()[:12]


def _memo(clave, ttl, calcular):
    """Devuelve el valor cacheado si es reciente; si no, lo calcula una sola
    vez aunque lleguen varias peticiones a la vez (lock por clave)."""
    entrada = _CACHE.get(clave)
    if entrada and time.time() - entrada['t'] < ttl:
        return entrada
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(clave, threading.Lock())
    with lock:
        entrada = _CACHE.get(clave)
        if entrada and time.time() - entrada['t'] < ttl:
            return entrada
        inicio = time.monotonic()
        valor = calcular()
        entrada = {
            'valor': valor, 't': time.time(),
            'actualizado': datetime.datetime.now().isoformat(sep=' ', timespec='seconds'),
            'segundos': round(time.monotonic() - inicio, 1),
        }
        _CACHE[clave] = entrada
        return entrada


def _aux(nombre, calcular):
    return _memo('aux:' + nombre, CACHE_AUX_SEGUNDOS, calcular)['valor']


# --- Utilidades ------------------------------------------------------------------

def _num(valor, defecto=0.0):
    if valor is None or valor == '':
        return defecto
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace('€', '').replace(' ', '')
    # Formato español 1.234,56 → 1234.56 (las hojas de Google lo traen así)
    if ',' in texto and '.' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    elif ',' in texto:
        texto = texto.replace(',', '.')
    try:
        return float(texto)
    except ValueError:
        return defecto


def _fecha(valor):
    """Fecha ISO (YYYY-MM-DD) desde ISO, dd/mm/yyyy o datetime; None si no se entiende."""
    if valor in (None, ''):
        return None
    if isinstance(valor, (datetime.date, datetime.datetime)):
        return valor.strftime('%Y-%m-%d')
    texto = str(valor).strip()
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y', '%d/%m/%Y %H:%M:%S', '%d/%m/%y', '%d-%m-%Y'):
        try:
            return datetime.datetime.strptime(texto[:19] if 'H' in fmt else texto[:10], fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def clave_rep(valor):
    """Clave de representante para cruzar tablas: los dígitos iniciales sin
    ceros a la izquierda ('     838', '838-HAO', '0838' → '838'). Sustituye a
    las normalizaciones de fnCambiarComercial / Text.PadStart del modelo."""
    if valor is None:
        return None
    texto = str(valor).strip()
    m = re.match(r'\s*0*(\d+)', texto)
    if not m:
        return texto or None
    return m.group(1) or '0'


def _tipo_pedido(pedido_web):
    pedido = (pedido_web or '').strip()
    if len(pedido) > 5 and pedido.startswith('Y'):
        return 'Y'
    if len(pedido) > 5 and pedido.startswith('P'):
        return 'P'
    return 'Otro'


def _anio_desde():
    return datetime.date.today().year - ANIOS_HISTORICO


# --- Tablas auxiliares (hojas de Google y maestros) ---------------------------------

def comerciales():
    """COMERCIALES_CORRECTOS + COMERCIALES_CAMBIOS (hoja de Google): qué
    representantes entran en los listados, su grupo (A/B/C...) y qué códigos
    antiguos se sustituyen por otros."""
    def calcular():
        correctos = {}
        for fila in fuentes.leer_gsheet('COMERCIALES', 'correctos'):
            clave = clave_rep(fila.get('CODREP'))
            if clave:
                correctos[clave] = {
                    'GRUPOS': (fila.get('TYPE') or '').strip().upper() or None,
                    'ENTRA': (fila.get('ENTRA') or '').strip().upper(),
                    'ZIP': fila.get('ZIP'),
                }
        cambios = {}
        for fila in fuentes.leer_gsheet('COMERCIALES', 'cambios'):
            original, nuevo = clave_rep(fila.get('original')), clave_rep(fila.get('nuevo'))
            if original and nuevo:
                cambios.setdefault(original, nuevo)
        return {'correctos': correctos, 'cambios': cambios}
    try:
        return _aux('comerciales', calcular)
    except Exception:
        log.exception('No se pudo leer la hoja de comerciales; se sigue sin grupos')
        return {'correctos': {}, 'cambios': {}}


def representantes():
    """REPRESEN: clave → {'NOMREP', 'Nombre'}."""
    def calcular():
        salida = {}
        for fila in fuentes.consultar('a3', 'SELECT CODREP, NOMREP FROM REPRESEN'):
            clave = clave_rep(fila['CODREP'])
            if not clave:
                continue
            nomrep = fila.get('NOMREP') or ''
            nombre = nomrep.split('-', 1)[1].strip() if '-' in nomrep else nomrep
            salida.setdefault(clave, {'NOMREP': nomrep, 'Nombre': nombre})
        return salida
    return _aux('representantes', calcular)


def enriquecer_rep(fila, columna, normalizar=True, grupo_defecto='Z'):
    """Añade CODREP_NORM, NOMREP, GRUPOS y Listado a una fila a partir del
    código de representante de `columna` (con la sustitución de
    COMERCIALES_CAMBIOS si `normalizar`)."""
    com = comerciales()
    clave = clave_rep(fila.get(columna))
    if normalizar and clave in com['cambios']:
        clave = com['cambios'][clave]
    info = com['correctos'].get(clave, {})
    rep = representantes().get(clave, {})
    fila['CODREP_NORM'] = clave
    fila['NOMREP'] = rep.get('NOMREP') or clave
    fila['GRUPOS'] = info.get('GRUPOS') or grupo_defecto
    fila['Listado'] = 'LISTADO' if info.get('ENTRA') == 'LISTADO' else 'NO LISTADO'
    return fila


def filtro_cobros():
    """Documentos de pago fuera del informe de cobros (hoja FILTRO)."""
    def calcular():
        return sorted({(f.get('FUERA_FILTRO') or '').strip().lower() for f in fuentes.leer_gsheet('FILTRO_COBROS')} - {''})
    try:
        return _aux('filtro_cobros', calcular)
    except Exception:
        log.exception('No se pudo leer la hoja FILTRO; solo se excluye REEMBOLSO')
        return []


def provincias():
    """PROVINCI con la "Provincia Limpia" del modelo (para cruzar con tarifas)."""
    def calcular():
        salida = {}
        for fila in fuentes.consultar('a3', 'SELECT CODPROVI, NOMPROVI FROM PROVINCI'):
            cod = (fila.get('CODPROVI') or '').strip()
            if not cod.isdigit():
                continue
            valor = (fila.get('NOMPROVI') or '').strip().upper()
            limpia = {
                '': 'PORTUGAL LISBOA', '0': 'PORTUGAL LISBOA', '00': 'PORTUGAL LISBOA',
                'SANTA CRUZ DE TENERIFE': 'SANTA CRUZ', 'MELILLA': 'MELILLA', 'CEUTA': 'MELILLA',
                'BALEARES': 'ISLAS BALEARES', 'GUIPUZCOA': 'GIPUZKOA',
            }.get(valor, valor)
            salida[cod.zfill(2)] = {'NOMPROVI': fila.get('NOMPROVI'), 'Provincia Limpia': limpia}
        return salida
    return _aux('provincias', calcular)


def articulos():
    """ARTICULO: CODART → familia, proveedor, descripción, unidades por paquete."""
    def calcular():
        return {
            (f['CODART'] or '').strip().upper(): f
            for f in fuentes.consultar(
                'a3', 'SELECT CODART, DESCART, CAR1 AS Familia, CODPRO, UNIPAQV FROM ARTICULO',
            )
            if f.get('CODART')
        }
    return _aux('articulos', calcular)


def categorias_proveedor(params):
    """Categoría de proveedor: la que manda el portal (SupplierCategory,
    editable en Configuración) o, si no llega, la hoja de Google."""
    recibidas = params.get('supplier_categories')
    if recibidas:
        return {str(c['codpro']).strip(): c for c in recibidas}
    try:
        return {
            (f.get('CODPRO') or '').strip(): {'codpro': f.get('CODPRO'), 'organizacion': f.get('Organización'), 'categoria': f.get('CATEGORÍA')}
            for f in fuentes.leer_gsheet('CATEGORIA_PROVEEDORES')
        }
    except Exception:
        log.exception('Sin categorías de proveedor')
        return {}


def _poner_categoria(fila, columna_codpro, categorias):
    cat = categorias.get(str(fila.get(columna_codpro) or '').strip(), {})
    fila['Categoria_Proveedor'] = cat.get('categoria')
    fila['Organizacion_Proveedor'] = cat.get('organizacion')
    return fila


def _ubicaciones(params):
    """Ubicaciones del almacén (centro/almacén/zona) para los cruces con
    Innertia: las de Configuración del portal o, si no llegan, ID_CENTRO=6."""
    ubicaciones = params.get('ubicaciones')
    if ubicaciones:
        return ubicaciones
    return [{'id_centro': int(os.environ.get('ID_CENTRO', '6')),
             'id_almacen': int(os.environ.get('ID_ALMACEN', '1')),
             'id_zona': int(os.environ.get('ID_ZONA', '1'))}]


def huecos(params):
    """Picking/Almacenamiento/etiquetas por artículo (Innertia)."""
    ubic = _ubicaciones(params)
    excl = params.get('tipos_excluidos') or [9]
    clave = 'huecos:' + json.dumps([ubic, sorted(excl)], sort_keys=True)
    return _memo(clave, CACHE_SEGUNDOS, lambda: query_hueco_breakdown(ubic, excl)[0])['valor']


# =============================================================================
# COBROS
# =============================================================================

@dataset('cobros_clientes', descripcion='Cobros pendientes (VW_COBROS) sin reembolsos ni documentos excluidos')
def ds_cobros_clientes(params):
    filas = fuentes.consultar('a3', """
        SELECT CODCLI, NOMCLI, Cliente, [Documento de pago], [Documento de pago - Tr], Tipo, Banco,
               CODREP, Representante, [Nº Documento], DOCUFACTURA, FECHAFACTURA, FECHAVTO,
               Importe, [Nº PEDIDO WEB], SW3_MULTIFORTE_OBSERVACIONES, OBSERVACIONES,
               [Días de adeudo], [Dirección], NUMDOC, Ejercicio, Mes
        FROM dbo.VW_COBROS
    """)
    excluidos = set(filtro_cobros())
    salida = []
    for f in filas:
        doc = (f.get('Documento de pago') or '')
        if 'REEMBOLSO' in doc.upper() or doc.strip().lower() in excluidos:
            continue
        f['FECHAFACTURA'] = _fecha(f.get('FECHAFACTURA'))
        f['FECHAVTO'] = _fecha(f.get('FECHAVTO'))
        f['Importe'] = _num(f.get('Importe'))
        f['COD-CLIENTE'] = f"{f.get('NOMCLI') or ''} - {f.get('CODCLI') or ''}"
        obs = (f.get('SW3_MULTIFORTE_OBSERVACIONES') or '').strip()
        f['Con observaciones'] = 'SÍ' if obs else 'NO'
        enriquecer_rep(f, 'CODREP', normalizar=False)
        salida.append(f)

    # "Importe Total Pedido" y "Repeticiones Nº Pedido Web" (columnas DAX):
    # suma de todas las líneas que comparten pedido web.
    por_pedido = {}
    for f in salida:
        pedido = (f.get('Nº PEDIDO WEB') or '').strip()
        if pedido:
            agg = por_pedido.setdefault(pedido, [0, 0.0])
            agg[0] += 1
            agg[1] += f['Importe']
    # "Suma Importe Por Cliente": deuda total del cliente sin las líneas con
    # observaciones; 0 en las filas que tienen observaciones.
    deuda_cliente = {}
    for f in salida:
        if f['Con observaciones'] == 'NO':
            deuda_cliente[f.get('CODCLI')] = deuda_cliente.get(f.get('CODCLI'), 0.0) + f['Importe']
    for f in salida:
        pedido = (f.get('Nº PEDIDO WEB') or '').strip()
        n, total = por_pedido.get(pedido, (1, f['Importe']))
        f['Repeticiones Nº Pedido Web'] = n if pedido else 0
        f['Importe Total Pedido'] = total if pedido and n > 1 else f['Importe']
        f['Suma Importe Por Cliente'] = 0.0 if f['Con observaciones'] == 'SÍ' else round(deuda_cliente.get(f.get('CODCLI'), 0.0), 2)
    return salida


@dataset('facturas_clientes', descripcion='Facturas de venta con su cobro (VW_FACTURACION)')
def ds_facturas_clientes(params):
    filas = fuentes.consultar('a3', f"""
        SELECT CODCLI, ClienteFacturado, CODCLIFAC, ClientePedido, CODREP, Representante,
               DocumentoFactura, [Fecha Factura], FechaCobro, FechaVencimiento,
               [Importe Factura], ImporteCobrado, IDFACV, [Nº PEDIDO WEB], DocumentoPago, Ejercicio
        FROM dbo.VW_FACTURACION
        WHERE Ejercicio >= {_anio_desde()}
    """)
    for f in filas:
        f['Fecha Factura'] = _fecha(f.get('Fecha Factura'))
        f['FechaCobro'] = _fecha(f.get('FechaCobro'))
        f['FechaVencimiento'] = _fecha(f.get('FechaVencimiento'))
        f['Importe Factura'] = _num(f.get('Importe Factura'))
        f['ImporteCobrado'] = _num(f.get('ImporteCobrado'))
        f['COD-CLIENTE'] = f"{f.get('ClientePedido') or ''} - {f.get('CODCLI') or ''}"
        enriquecer_rep(f, 'CODREP', normalizar=False)
    return filas


# =============================================================================
# PEDIDOS
# =============================================================================

@dataset('pedidos_diarios', descripcion='Líneas de pedidos/ofertas de venta con tipo de pedido web (Informe Cobros)')
def ds_pedidos_diarios(params):
    filas = fuentes.consultar('a3', f"""
        SELECT A.FECHA, LEFT(RTRIM(LTRIM(A.CODREP)), 3) AS CODREP, A.CODCLI, CLI.NOMCLI, A.NUMDOC,
               B.CODART, C.CAR1 AS Familia,
               CASE WHEN C.UNIPAQV IS NULL OR C.UNIPAQV = 0 THEN 0
                    ELSE CEILING(B.UNIDADES * 1.0 / C.UNIPAQV) END AS [Paquetes Vendidos],
               A.PARAM8 AS [Pedido Web], A.TOTDOC
        FROM CABEOFEV A
        LEFT JOIN LINEOFER B ON A.IDOFEV = B.IDOFEV
        LEFT JOIN ARTICULO C ON B.CODART = C.CODART
        LEFT JOIN CLIENTES CLI ON LTRIM(RTRIM(A.CODCLI)) = LTRIM(RTRIM(CLI.CODCLI))
        WHERE A.IDOFEV > 0 AND A.FECHA IS NOT NULL AND A.CODCLI IS NOT NULL
          AND A.CODREP IS NOT NULL AND C.CAR1 IS NOT NULL AND YEAR(A.FECHA) >= {_anio_desde()}
    """)
    for f in filas:
        f['FECHA'] = _fecha(f['FECHA'])
        f['Tipo pedido'] = _tipo_pedido(f.get('Pedido Web'))
        f['Tipología Avanzada'] = 'P' if f['Tipo pedido'] == 'P' else 'Extra'
        enriquecer_rep(f, 'CODREP')
    return filas


@dataset('pedidos_grandes', descripcion='Pedidos de 500 € o más con el representante de la última factura (Informe Susana)')
def ds_pedidos_grandes(params):
    filas = fuentes.consultar('a3', f"""
        WITH FacturasValidas AS (
            SELECT LTRIM(RTRIM(F.CODCLI)) AS CODCLI_NORM, F.FECHA AS FECHA_FACTURA, F.IDFACV,
                   LTRIM(RTRIM(F.CODREP)) AS CODREP_ULTIMO_RAW, LTRIM(RTRIM(F.CODPROVI)) AS CODPROVI_ULTIMO,
                   ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(F.CODCLI)) ORDER BY F.FECHA DESC, F.IDFACV DESC) AS RN
            FROM CABEFACV F
            WHERE F.CODCLI IS NOT NULL AND F.FECHA IS NOT NULL AND F.CODREP IS NOT NULL
              AND (F.SERIE IS NULL OR UPPER(LTRIM(RTRIM(F.SERIE))) <> 'R')
        ),
        UltFac AS (
            SELECT CODCLI_NORM, FECHA_FACTURA AS UltimaFacturacion, CODREP_ULTIMO_RAW, CODPROVI_ULTIMO
            FROM FacturasValidas WHERE RN = 1
        )
        SELECT A.FECHA,
               LEFT(LTRIM(RTRIM(COALESCE(UF.CODREP_ULTIMO_RAW, A.CODREP))), 3) AS CODREP,
               E.NOMREP AS NOMREP_A3, A.CODCLI, D.NOMCLI, P.NOMPROVI AS Provincia, B.CODART,
               C.CAR1 AS Familia,
               CASE WHEN C.UNIPAQV IS NULL OR C.UNIPAQV = 0 THEN 0
                    ELSE CEILING(B.UNIDADES * 1.0 / C.UNIPAQV) END AS [Paquetes Vendidos],
               A.PARAM8 AS [Pedido Web], A.NUMDOC AS NUMDOC, A.TOTDOC AS [INGRESO TOTAL],
               UF.UltimaFacturacion
        FROM CABEOFEV A
        LEFT JOIN LINEOFER B ON A.IDOFEV = B.IDOFEV
        LEFT JOIN ARTICULO C ON B.CODART = C.CODART
        LEFT JOIN CLIENTES D ON LTRIM(RTRIM(A.CODCLI)) = LTRIM(RTRIM(D.CODCLI))
        LEFT JOIN UltFac UF ON UF.CODCLI_NORM = LTRIM(RTRIM(A.CODCLI))
        LEFT JOIN REPRESEN E ON LEFT(LTRIM(RTRIM(E.CODREP)), 3) = LEFT(LTRIM(RTRIM(COALESCE(UF.CODREP_ULTIMO_RAW, A.CODREP))), 3)
        LEFT JOIN PROVINCI P ON LTRIM(RTRIM(P.CODPROVI)) = LTRIM(RTRIM(UF.CODPROVI_ULTIMO))
        WHERE A.IDOFEV > 0 AND A.FECHA IS NOT NULL AND A.CODCLI IS NOT NULL AND A.CODREP IS NOT NULL
          AND C.CAR1 IS NOT NULL AND A.TOTDOC >= 500.0 AND YEAR(A.FECHA) >= {_anio_desde()}
    """)
    for f in filas:
        f['FECHA'] = _fecha(f['FECHA'])
        f['UltimaFacturacion'] = _fecha(f.get('UltimaFacturacion'))
        f['Tipo pedido'] = _tipo_pedido(f.get('Pedido Web'))
        f['Tipología Avanzada'] = 'P' if f['Tipo pedido'] == 'P' else 'Extra'
        enriquecer_rep(f, 'CODREP', normalizar=False)
        if f.get('NOMREP_A3'):
            f['NOMREP'] = f['NOMREP_A3']
        del f['NOMREP_A3']
    return filas


@dataset('pedidos_clientes', descripcion='Ritmo de pedidos por cliente (VW_PEDIDOS_CLIENTES) con años reales')
def ds_pedidos_clientes(params):
    filas = fuentes.consultar('a3', 'SELECT * FROM dbo.VW_PEDIDOS_CLIENTES')
    anio = datetime.date.today().year
    y = {f'Y{i}': str(anio - i) for i in range(4)}
    renombres = {}
    for base in ('TOTAL_PEDIDOS', 'SKU_DISTINTOS', 'IMPORTE_TOTAL', 'IMPORTE_MEDIO', 'MEDIA_MENSUAL',
                 'TOTAL_ABONOS', 'IMPORTE_ABONOS', 'PAQUETES_ABONADOS'):
        for i in range(4):
            renombres[f'{base}_Y{i}'] = f'{base}_{y[f"Y{i}"]}'
    renombres['IMPORTE_TOTAL_Y0_Y1'] = f'IMPORTE_TOTAL_{y["Y1"]}_{y["Y0"]}'
    renombres['IMPORTE_SUBIDA_BAJADA_Y0_Y1'] = f'IMPORTE_SUBIDA_BAJADA_{y["Y1"]}_{y["Y0"]}'
    renombres['IMPORTE_SUBIDA_BAJADA_Y1_Y2'] = f'IMPORTE_SUBIDA_BAJADA_{y["Y2"]}_{y["Y1"]}'
    renombres['IMPORTE_SUBIDA_BAJADA_Y0_Y2'] = f'IMPORTE_SUBIDA_BAJADA_{y["Y2"]}_{y["Y0"]}'
    hoy = datetime.date.today()
    salida = []
    for f in filas:
        nueva = {renombres.get(k, k): v for k, v in f.items()}
        provincia = (nueva.get('NOMPROVI') or '').strip()
        nueva['NOMPROVI'] = {'': 'SIN ZONA', '0': 'INTERNACIONAL (0)', '00': 'INTERNACIONAL (00)'}.get(provincia, provincia)
        telefonos = []
        for t in (nueva.pop('TELCLI', None), nueva.pop('TELCLI2', None)):
            t = (t or '').strip()
            if t and t not in telefonos:
                telefonos.append(t)
        nueva['Telefonos Cliente'] = ';'.join(telefonos) or None
        ultima = _fecha(nueva.get('UltimaPedido'))
        nueva['UltimaPedido'] = ultima
        nueva['Dias_Transcurridos'] = (hoy - datetime.date.fromisoformat(ultima)).days if ultima else None
        pedidos = _num(nueva.get(f'TOTAL_PEDIDOS_{y["Y0"]}'))
        sku = _num(nueva.get(f'SKU_DISTINTOS_{y["Y0"]}'))
        nueva['SKU / PEDIDOS'] = round(sku / pedidos, 2) if pedidos else 0
        salida.append(nueva)
    return salida


# =============================================================================
# VENTAS
# =============================================================================

@dataset('ventas_familia', descripcion='Ventas por familia con importe con IVA (Informe Cobros)')
def ds_ventas_familia(params):
    filas = fuentes.consultar('a3', f"""
        SELECT A.FECHA, B.CODART, C.CAR1 AS Familia, A.CODCLI, CLI.NOMCLI,
               C.CODPRO AS [Código Proveedor], LEFT(LTRIM(RTRIM(A.CODREP)), 3) AS Representante,
               B.UNIDADES,
               CASE WHEN C.UNIPAQV IS NULL OR C.UNIPAQV = 0 THEN 0
                    ELSE CEILING(B.UNIDADES * 1.0 / C.UNIPAQV) END AS PaquetesVendidos,
               B.BASE + (B.BASE * (A.PORIVA1 / 100)) AS Importe
        FROM CABEOFEV A
        LEFT JOIN LINEOFER B ON A.IDOFEV = B.IDOFEV
        LEFT JOIN ARTICULO C ON B.CODART = C.CODART
        LEFT JOIN CLIENTES CLI ON A.CODCLI = CLI.CODCLI
        WHERE A.IDOFEV > 0 AND A.FECHA IS NOT NULL AND A.CODCLI IS NOT NULL AND A.CODREP IS NOT NULL
          AND B.CODART IS NOT NULL AND C.CAR1 IS NOT NULL AND YEAR(A.FECHA) >= {_anio_desde()}
    """)
    for f in filas:
        f['FECHA'] = _fecha(f['FECHA'])
        f['CODCLI - NOMCLI'] = f"{f.get('CODCLI') or ''} - {f.get('NOMCLI') or ''}"
        f['Semana'] = datetime.date.fromisoformat(f['FECHA']).isocalendar()[1] if f['FECHA'] else None
        f['Importe'] = round(_num(f.get('Importe')), 2)
        enriquecer_rep(f, 'Representante')
    return filas


@dataset('ventas_familia_detalle', descripcion='Ventas (ofertas) y abonos por familia, con el representante de la última factura (Informe Susana)')
def ds_ventas_familia_detalle(params):
    desde = _anio_desde()
    filas = fuentes.consultar('a3', f"""
        WITH FacturasValidas AS (
            SELECT LTRIM(RTRIM(F.CODCLI)) AS CODCLI_NORM, F.FECHA AS FECHA_FACTURA, F.IDFACV,
                   LTRIM(RTRIM(F.CODREP)) AS CODREP_ULTIMO_RAW,
                   ROW_NUMBER() OVER (PARTITION BY LTRIM(RTRIM(F.CODCLI)) ORDER BY F.FECHA DESC, F.IDFACV DESC) AS RN
            FROM CABEFACV F
            WHERE F.CODCLI IS NOT NULL AND F.FECHA IS NOT NULL AND F.CODREP IS NOT NULL
              AND (F.SERIE IS NULL OR UPPER(LTRIM(RTRIM(F.SERIE))) <> 'R')
        ),
        UltFac AS (
            SELECT CODCLI_NORM, FECHA_FACTURA AS UltimaFacturacion, CODREP_ULTIMO_RAW
            FROM FacturasValidas WHERE RN = 1
        )
        SELECT A.FECHA, A.SERIE, B.BASEMONEDAMASIVA, B.CODART, C.CAR1 AS Familia,
               C.FAMARTDESCVEN AS [Familia Descuento], A.CODCLI, CL.NOMCLI, C.CODPRO AS [Código Proveedor],
               LEFT(LTRIM(RTRIM(COALESCE(UF.CODREP_ULTIMO_RAW, A.CODREP))), 3) AS Representante,
               B.UNIDADES,
               CASE WHEN C.UNIPAQV IS NULL OR C.UNIPAQV = 0 THEN 0
                    ELSE CEILING(B.UNIDADES * 1.0 / C.UNIPAQV) END AS PaquetesVendidos,
               UF.UltimaFacturacion
        FROM CABEOFEV A
        JOIN CLIENTES CL ON LTRIM(RTRIM(A.CODCLI)) = LTRIM(RTRIM(CL.CODCLI))
        LEFT JOIN LINEOFER B ON A.IDOFEV = B.IDOFEV
        LEFT JOIN ARTICULO C ON B.CODART = C.CODART
        LEFT JOIN UltFac UF ON UF.CODCLI_NORM = LTRIM(RTRIM(A.CODCLI))
        WHERE A.FECHA IS NOT NULL AND A.CODCLI IS NOT NULL AND A.CODREP IS NOT NULL
          AND B.CODART IS NOT NULL AND C.CAR1 IS NOT NULL AND YEAR(A.FECHA) >= {desde}
          AND (A.SERIE IS NULL OR UPPER(LTRIM(RTRIM(A.SERIE))) <> 'R') AND B.UNIDADES > 0
        UNION ALL
        SELECT F.FECHA, F.SERIE, L.BASEMONEDAMASIVA, L.CODART, C.CAR1 AS Familia,
               C.FAMARTDESCVEN AS [Familia Descuento], F.CODCLI, CL.NOMCLI, C.CODPRO AS [Código Proveedor],
               LEFT(LTRIM(RTRIM(COALESCE(UF.CODREP_ULTIMO_RAW, F.CODREP))), 3) AS Representante,
               L.UNIDADES,
               CASE WHEN C.UNIPAQV IS NULL OR C.UNIPAQV = 0 THEN 0
                    ELSE CEILING(L.UNIDADES * 1.0 / C.UNIPAQV) END AS PaquetesVendidos,
               UF.UltimaFacturacion
        FROM CABEFACV F
        JOIN CLIENTES CL ON LTRIM(RTRIM(F.CODCLI)) = LTRIM(RTRIM(CL.CODCLI))
        JOIN LINEFACT L ON F.IDFACV = L.IDFACV
        LEFT JOIN ARTICULO C ON L.CODART = C.CODART
        LEFT JOIN UltFac UF ON UF.CODCLI_NORM = LTRIM(RTRIM(F.CODCLI))
        WHERE F.FECHA IS NOT NULL AND F.CODCLI IS NOT NULL AND F.CODREP IS NOT NULL
          AND L.CODART IS NOT NULL AND C.CAR1 IS NOT NULL AND YEAR(F.FECHA) >= {desde}
          AND UPPER(LTRIM(RTRIM(COALESCE(F.SERIE, '')))) = 'R'
    """)
    # Los abonos traen una línea por artículo y factura (decenas de miles):
    # se agregan por día, cliente, artículo y representante, que es el
    # detalle más fino que usan las páginas (las medidas cuentan pares
    # cliente/día).
    agrupado = {}
    for f in filas:
        fecha = _fecha(f['FECHA'])
        tipologia = fecha[:4] if not (f.get('SERIE') or '').strip() else 'Abono'
        clave = (fecha, f.get('CODCLI'), f.get('CODART'), tipologia, f.get('Representante'))
        fila = agrupado.get(clave)
        if fila is None:
            fila = {
                'FECHA': fecha, 'CODCLI': f.get('CODCLI'), 'NOMCLI': f.get('NOMCLI'),
                'CODCLI - NOMCLI': f"{f.get('CODCLI') or ''} - {f.get('NOMCLI') or ''}",
                'CODART': f.get('CODART'), 'Familia': f.get('Familia'),
                'Familia Descuento': f.get('Familia Descuento'), 'Código Proveedor': f.get('Código Proveedor'),
                'Representante': f.get('Representante'), 'Tipologia': tipologia,
                'UltimaFacturacion': _fecha(f.get('UltimaFacturacion')),
                'UNIDADES': 0.0, 'PaquetesVendidos': 0.0, 'BASEMONEDAMASIVA': 0.0,
            }
            enriquecer_rep(fila, 'Representante')
            fila['REPRESENTANTE LISTADO'] = fila['Listado']
            agrupado[clave] = fila
        fila['UNIDADES'] += _num(f.get('UNIDADES'))
        fila['PaquetesVendidos'] += _num(f.get('PaquetesVendidos'))
        fila['BASEMONEDAMASIVA'] += _num(f.get('BASEMONEDAMASIVA'))
    for fila in agrupado.values():
        fila['BASEMONEDAMASIVA'] = round(fila['BASEMONEDAMASIVA'], 2)
    return list(agrupado.values())


@dataset('ofertas_representantes', descripcion='Ofertas de venta por representante para rankings (Informe Cobros)')
def ds_ofertas_representantes(params):
    filas = fuentes.consultar('a3', """
        SELECT FECHA, CODCLI, NOMCLI, CODREP, TOTDOC, NUMDOC, PARAM8
        FROM CABEOFEV
        WHERE IDOFEV > 0 AND ESTADO <> 'PA' AND SERIE IS NULL AND TOTDOC > 0
    """)
    salida = []
    for f in filas:
        f['FECHA'] = _fecha(f['FECHA'])
        enriquecer_rep(f, 'CODREP')
        if f['Listado'] != 'LISTADO' and f['CODREP_NORM'] != '610':
            continue
        rep = representantes().get(f['CODREP_NORM'], {})
        f['Nombre - COD'] = f"{f['CODREP_NORM']} - {rep.get('Nombre') or ''}".strip(' -')
        f['TOTDOC'] = _num(f.get('TOTDOC'))
        salida.append(f)
    return salida


@dataset('ofertas_familia', descripcion='Líneas de oferta por familia desde el año pasado (VW_OFERTAS_FAMILIA)')
def ds_ofertas_familia(params):
    filas = fuentes.consultar('a3', """
        SELECT CODCLI, Nombre_Cliente, Comercial, Nombre_Comercial, CODART, Descripcion_Articulo, Familia,
               Familia_Descuento, Codigo_Proveedor, Fecha, Ejercicio, Mes, UNIDADES, Unidades_Servidas,
               Paquetes, Paquetes_Servidos, Importe, DIRCLI1, POBCLI, Num_Documento
        FROM dbo.VW_OFERTAS_FAMILIA
        WHERE Ejercicio >= YEAR(GETDATE()) - 1
    """)
    com = comerciales()['correctos']
    for f in filas:
        f['Fecha'] = _fecha(f.get('Fecha'))
        info = com.get(clave_rep(f.get('Comercial')), {})
        f['Tipo_Comercial'] = info.get('GRUPOS')
        f['Listado'] = info.get('ENTRA') or None
        f['Zona'] = info.get('ZIP')
        f['Importe'] = _num(f.get('Importe'))
    return filas


@dataset('historico_representantes', ttl=1800, descripcion='Importes facturados/pedidos/albaranes/ofertas por comercial y día')
def ds_historico_representantes(params):
    filas = fuentes.consultar('a3', f"""
        SELECT FECHA, COMERCIAL, [IMP.FAC], [IMP.PED], [IMP.ALB], [IMP.OFE], TOTAL
        FROM dbo.VW_RESUMEN_COMERCIAL_TOTDOC
        WHERE YEAR(FECHA) >= {_anio_desde()}
    """)
    cambios = comerciales()['cambios']
    agrupado = {}
    for f in filas:
        clave = clave_rep(f.get('COMERCIAL'))
        clave = cambios.get(clave, clave)
        k = (_fecha(f['FECHA']), clave)
        agg = agrupado.setdefault(k, {'IMP.FAC': 0.0, 'IMP.PED': 0.0, 'IMP.ALB': 0.0, 'IMP.OFE': 0.0, 'TOTAL': 0.0})
        for col in agg:
            agg[col] += _num(f.get(col))
    salida = []
    for (fecha, comercial), agg in agrupado.items():
        fila = {'FECHA': fecha, 'COMERCIAL': comercial, **{k: round(v, 2) for k, v in agg.items()}}
        enriquecer_rep(fila, 'COMERCIAL', normalizar=False)
        salida.append(fila)
    return salida


@dataset('ventas_web', descripcion='Ventas de la tienda web / marketplaces (hoja de Google)')
def ds_ventas_web(params):
    filas = fuentes.leer_gsheet('VENTAS_WEB')
    arts = articulos()
    salida = []
    for f in filas:
        fecha = _fecha(f.get('FECHA'))
        if not fecha or fecha < '2024-01-01':
            continue
        sku = (f.get('SKU') or '').strip()
        art = arts.get(sku.upper(), {})
        salida.append({
            'FECHA': fecha, 'Nº PEDIDO': f.get('Nº PEDIDO'), 'NOMBRE': f.get('NOMBRE'),
            'UNIDADES': _num(f.get('UNIDADES')), 'SKU': sku, 'PVP': _num(f.get('PVP')),
            'PVP Corregido': _num(f.get('PVP Corregido')), 'MARKETPLACE': f.get('MARKETPLACE'),
            'ENVIADO': f.get('ENVIADO'), 'OBSERVACIONES': f.get('OBSERVACIONES'),
            'Familia': art.get('Familia'), 'CODPRO': art.get('CODPRO'),
        })
    return salida


# =============================================================================
# PENDIENTES (ofertas, albaranes, zona)
# =============================================================================

@dataset('ofertas_pendientes', descripcion='Ofertas pendientes del año (Informe Susana)')
def ds_ofertas_pendientes(params):
    filas = fuentes.consultar('a3', """
        SELECT CAST(CABEOFEV.FECHA AS DATE) AS fecha, CABEOFEV.REFERENCIA, LEFT(LTRIM(RTRIM(CABEOFEV.CODREP)), 3) AS codrep,
               CABEOFEV.CODCLI AS [Codigo Cliente], CABEOFEV.TOTDOC AS Importe, PROVINCI.NOMPROVI,
               CLIENTES.NOMCLI AS [Nombre Cliente], CLIENTES.DIRFISCAL AS [Direccion Cliente],
               CLIENTES.POBFISCAL AS Poblacion
        FROM CABEOFEV
        LEFT JOIN CLIENTES ON CABEOFEV.CODCLI = CLIENTES.CODCLI
        LEFT JOIN PROVINCI ON CLIENTES.CODPROVI = PROVINCI.CODPROVI
        WHERE CABEOFEV.SITUACIONDETALLE LIKE 'PENDIENTE' AND CABEOFEV.SITUACION = 'A'
          AND CABEOFEV.SERIE IS NULL AND CABEOFEV.ESTADO = 'AC'
          AND YEAR(CABEOFEV.FECHA) >= YEAR(CAST(GETDATE() AS DATE)) AND CABEOFEV.TOTDOC > 0
          AND LTRIM(RTRIM(CABEOFEV.CODCLI)) NOT IN ('3', '4')
        ORDER BY CABEOFEV.FECHA, CABEOFEV.REFERENCIA
    """)
    hoy = datetime.date.today().isoformat()
    for f in filas:
        f['fecha'] = _fecha(f['fecha'])
        f['Importe'] = _num(f.get('Importe'))
        f['Estado'] = 'Atrasada' if f['fecha'] and f['fecha'] < hoy else 'En plazo'
        enriquecer_rep(f, 'codrep', normalizar=False)
    return filas


def _consulta_pendientes(tabla, extra_select, extra_where):
    return f"""
        SELECT CASE WHEN UPPER(LTRIM(RTRIM(A.SITUACIONDETALLE))) = 'PENDIENTE' THEN 'Pendiente'
                    ELSE LTRIM(RTRIM(A.SITUACIONDETALLE)) END AS [Situación],
               CAST(A.FECHA AS DATE) AS [Fecha], A.TOTDOC AS [Total documento moneda],
               LTRIM(RTRIM(A.CODCLI)) AS [Código cliente],
               COALESCE(NULLIF(LTRIM(RTRIM(A.NOMCLI)), ''), LTRIM(RTRIM(C.NOMCLI))) AS [Nombre cliente],
               LEFT(LTRIM(RTRIM(A.CODREP)), 3) AS [CODREP], LTRIM(RTRIM(R.NOMREP)) AS [Nombre representante],
               LTRIM(RTRIM(A.REFERENCIA)) AS [Referencia], LTRIM(RTRIM(P.NOMPROVI)) AS [Provincia],
               DATEDIFF(DAY, CAST(A.FECHA AS DATE), CAST(GETDATE() AS DATE)) AS [DAY],
               LTRIM(RTRIM(A.NUMDOC)) AS [Número documento] {extra_select}
        FROM {tabla} A
        LEFT JOIN CLIENTES C ON LTRIM(RTRIM(A.CODCLI)) = LTRIM(RTRIM(C.CODCLI))
        LEFT JOIN PROVINCI P ON LTRIM(RTRIM(C.CODPROVI)) = LTRIM(RTRIM(P.CODPROVI))
        LEFT JOIN REPRESEN R ON LEFT(LTRIM(RTRIM(A.CODREP)), 3) = LEFT(LTRIM(RTRIM(R.CODREP)), 3)
        WHERE UPPER(LTRIM(RTRIM(A.SITUACIONDETALLE))) = 'PENDIENTE' AND UPPER(LTRIM(RTRIM(A.SITUACION))) = 'A'
          AND A.FECHA IS NOT NULL AND A.TOTDOC > 0 AND LTRIM(RTRIM(A.CODCLI)) NOT IN ('3', '4')
          AND YEAR(A.FECHA) >= YEAR(GETDATE()) {extra_where}
        ORDER BY A.FECHA ASC, A.REFERENCIA ASC
    """


def _post_pendientes(filas):
    for f in filas:
        f['Fecha'] = _fecha(f.get('Fecha'))
        if 'Fecha entrega' in f:
            f['Fecha entrega'] = _fecha(f.get('Fecha entrega'))
        f['Total documento moneda'] = _num(f.get('Total documento moneda'))
        enriquecer_rep(f, 'CODREP', normalizar=False)
    return filas


@dataset('consulta_ofertas', descripcion='Ofertas de venta pendientes con días de retraso (Ofer_Pendin)')
def ds_consulta_ofertas(params):
    sql = _consulta_pendientes(
        'CABEOFEV',
        ", LTRIM(RTRIM(A.FORPAG)) AS [T], LTRIM(RTRIM(A.CODMON)) AS [Código moneda], "
        "CAST(A.FECENTREGA AS DATE) AS [Fecha entrega], LTRIM(RTRIM(A.SERIE)) AS [Serie]",
        "AND UPPER(LTRIM(RTRIM(A.ESTADO))) = 'AC' AND (A.SERIE IS NULL OR LTRIM(RTRIM(A.SERIE)) = '')",
    )
    return _post_pendientes(fuentes.consultar('a3', sql))


@dataset('consulta_albaranes', descripcion='Albaranes de venta pendientes con días de retraso (Alb_Pendin)')
def ds_consulta_albaranes(params):
    sql = _consulta_pendientes(
        'CABEALBV',
        ", LTRIM(RTRIM(C.DIRCLI1)) AS [Dirección], LTRIM(RTRIM(C.POBCLI)) AS [Pueblo], "
        "LTRIM(RTRIM(C.TELCLI)) AS [Teléfono]",
        '',
    )
    return _post_pendientes(fuentes.consultar('a3', sql))


def _rutas():
    rutas = {}
    with open(os.path.join(DATOS_DIR, 'poblaciones_rutas.csv'), encoding='utf-8') as fh:
        for fila in csv.DictReader(fh):
            rutas.setdefault((fila.get('Poblaciones') or '').strip().upper(), fila.get('Ruta'))
    return rutas


@dataset('pendientes_zona', descripcion='Ofertas, pedidos y albaranes pendientes de Alicante y Murcia con su ruta')
def ds_pendientes_zona(params):
    partes = []
    for tipo, tabla, extra in (
        ('Ofertas', 'CABEOFEV', "AND CABEOFEV.ESTADO = 'AC'"),
        ('Pedidos', 'CABEPEDV', ''),
        ('Albaranes', 'CABEALBV', ''),
    ):
        partes.append(f"""
            SELECT '{tipo}' AS Tipo, {tabla}.REFERENCIA, {tabla}.CODCLI, PROVINCI.NOMPROVI, CLIENTES.DTOCLI,
                   CLIENTES.DIRFISCAL AS [Direccion Cliente], CLIENTES.POBFISCAL AS Poblacion, {tabla}.FECHA
            FROM {tabla}
            LEFT JOIN CLIENTES ON {tabla}.CODCLI = CLIENTES.CODCLI
            LEFT JOIN PROVINCI ON CLIENTES.CODPROVI = PROVINCI.CODPROVI
            WHERE {tabla}.SITUACIONDETALLE = 'PENDIENTE' AND {tabla}.SITUACION = 'A'
              AND (CLIENTES.CODPROVI LIKE '%03%' OR CLIENTES.CODPROVI LIKE '%30%')
              AND {tabla}.SERIE IS NULL {extra}
              AND {tabla}.FECHA >= DATEFROMPARTS(YEAR(GETDATE()), 1, 1) AND {tabla}.TOTDOC > 0
              AND LTRIM(RTRIM({tabla}.CODCLI)) NOT IN ('3', '4')
        """)
    filas = fuentes.consultar('a3', f"""
        WITH CTE AS ({' UNION '.join(partes)})
        SELECT Tipo, REFERENCIA, CODCLI AS [Cliente], NOMPROVI AS [Provincia], DTOCLI AS [Codigo Postal],
               [Direccion Cliente], Poblacion, CAST(FECHA AS date) AS fecha
        FROM CTE ORDER BY Tipo, FECHA DESC, REFERENCIA
    """)
    rutas = _rutas()
    vistos = set()
    salida = []
    for f in filas:
        f['fecha'] = _fecha(f.get('fecha'))
        clave = (f['fecha'], f.get('Direccion Cliente'), f.get('Codigo Postal'), f.get('Provincia'))
        if clave in vistos:
            continue
        vistos.add(clave)
        f['Ruta'] = rutas.get((f.get('Poblacion') or '').strip().upper())
        salida.append(f)
    return salida


@dataset('analisis_albaran', descripcion='Líneas de pedido pendientes contra stock de Innertia y ubicaciones')
def ds_analisis_albaran(params):
    filas = fuentes.consultar('a3', """
        SELECT IDPEDV, NUMDOC_PEDIDO, [ARTICULO PEDIDO], ESTADO_PEDIDO, UNIDADES_PEDIDO, IDALBV, NUMDOC_ALBARAN,
               CODCLI, [NOMBRE CLIENTE], FECHA_PEDIDO, FECHA_ALBARAN, UNIDADES_SERVIDAS, ESTADO_ALBARAN
        FROM dbo.VW_ANALSIS_ALBARANES
        WHERE ESTADO_PEDIDO = 'PENDIENTE'
    """)
    ubic = _ubicaciones(params)
    disponible = stock_disponible_innertia(ubic)
    hue = huecos(params)
    for f in filas:
        art = (f.get('ARTICULO PEDIDO') or '').strip().upper()
        f['ARTICULO PEDIDO'] = art
        h = hue.get(art, {})
        f['NOMCODCLI'] = f"{f.get('CODCLI') or ''} - {f.get('NOMBRE CLIENTE') or ''}"
        f['FECHA_PEDIDO'] = _fecha(f.get('FECHA_PEDIDO'))
        f['FECHA_ALBARAN'] = _fecha(f.get('FECHA_ALBARAN'))
        f['Disponible'] = disponible.get(art, 0.0)
        f['Picking_Stock'] = h.get('Picking', 0.0)
        f['Packing'] = h.get('Almacenamiento', 0.0)
        f['PICKING 2'] = h.get('Etiquetas_Picking')
        f['ALMACENAMIENTO'] = h.get('Etiquetas_Almacenamiento')
        f['UNIDADES_PEDIDO'] = _num(f.get('UNIDADES_PEDIDO'))
        f['UNIDADES_SERVIDAS'] = _num(f.get('UNIDADES_SERVIDAS'))
    return filas


# =============================================================================
# COMPRAS
# =============================================================================

_REF_VALIDA = "[A-Za-z][A-Za-z][A-Za-z][A-Za-z][0-9][0-9][0-9][0-9][0-9][0-9][0-9]"


@dataset('compras', descripcion='Unidades pendientes de recibir por artículo y proveedor')
def ds_compras(params):
    filas = fuentes.consultar('a3', f"""
        SELECT TRIM(CODART) AS [Codigo Articulo], CODPRO,
               MAX(CASE WHEN TipoReferencia = 'NO_VALIDA' THEN REFERENCIA END) AS Referencia_No_Numerada,
               SUM(CASE WHEN TipoReferencia = 'NO_VALIDA' THEN UNIDADES ELSE 0 END) AS Unidades_No_Numeradas,
               MAX(CASE WHEN TipoReferencia = 'VALIDA' THEN REFERENCIA END) AS Referencia_Numerada,
               SUM(CASE WHEN TipoReferencia = 'VALIDA' THEN UNIDADES ELSE 0 END) AS Unidades_Numeradas,
               MAX(FECHA) AS Fecha, DATEDIFF(DAY, MAX(FECHA), GETDATE()) AS DiasDesdePedido
        FROM (
            SELECT LINEPEDI.CODART, TRIM(CABEPEDC.CODPRO) AS CODPRO,
                   CASE WHEN CABEPEDC.REFERENCIA LIKE '{_REF_VALIDA}' AND LEN(CABEPEDC.REFERENCIA) = 11
                        THEN 'VALIDA' ELSE 'NO_VALIDA' END AS TipoReferencia,
                   CABEPEDC.REFERENCIA, LINEPEDI.UNIDADES, CAST(CABEPEDC.FECHA AS DATE) AS FECHA
            FROM CABEPEDC INNER JOIN LINEPEDI ON CABEPEDC.IDPEDC = LINEPEDI.IDPEDC
            WHERE SITUACIONDETALLE LIKE '%PENDIENTE'
        ) AS Datos
        GROUP BY CODART, CODPRO
        ORDER BY Fecha DESC
    """)
    cats = categorias_proveedor(params)
    for f in filas:
        f['Fecha'] = _fecha(f.get('Fecha'))
        f['Unidades_No_Numeradas'] = _num(f.get('Unidades_No_Numeradas'))
        f['Unidades_Numeradas'] = _num(f.get('Unidades_Numeradas'))
        f['Total Unidades Compra'] = f['Unidades_No_Numeradas'] + f['Unidades_Numeradas']
        _poner_categoria(f, 'CODPRO', cats)
    return filas


@dataset('situacion_compras', descripcion='Pedidos de compra con referencia numerada: recibido / ubicado')
def ds_situacion_compras(params):
    filas = fuentes.consultar('a3', """
        WITH CABEPEDC_FILTRADA AS (
            SELECT * FROM CABEPEDC
            WHERE Referencia IS NOT NULL AND LEN(Referencia) = 11
              AND ISNUMERIC(SUBSTRING(Referencia, 5, 7)) = 1 AND UPPER(LEFT(Referencia, 4)) = LEFT(Referencia, 4)
        ),
        CABEALBC_FILTRADA AS (
            SELECT * FROM CABEALBC
            WHERE Referencia IS NOT NULL AND LEN(Referencia) = 11
              AND ISNUMERIC(SUBSTRING(Referencia, 5, 7)) = 1 AND UPPER(LEFT(Referencia, 4)) = LEFT(Referencia, 4)
        )
        SELECT a.CODART, ar.DESCART AS [Descripción], cp.IDPEDC AS Pedido, TRIM(cp.CODPRO) AS [Código Proveedor],
               cp.Referencia, ca.IDALBC AS Albaran, cp.FECHA AS FechaPedido, ca.FECHA AS FechaRecepcion,
               DATEDIFF(DAY, cp.FECHA, ISNULL(ca.FECHA, GETDATE())) AS DiasDesdePedido,
               cp.Situacion AS SituacionPedido, cp.SituacionDetalle AS SituacionDetallePedido,
               ar.PARAM6 AS Ubicacion,
               CASE WHEN ca.FECHA IS NULL THEN 'No recibido'
                    WHEN ca.FECHA IS NOT NULL AND (ar.PARAM6 IS NULL OR LTRIM(RTRIM(ar.PARAM6)) = '') THEN 'Recibido sin ubicar'
                    WHEN ca.FECHA IS NOT NULL AND LTRIM(RTRIM(ar.PARAM6)) <> '' THEN 'Recibido y ubicado'
                    ELSE 'Revisar estado' END AS EstadoLogico
        FROM LINEPEDI a
        JOIN CABEPEDC_FILTRADA cp ON a.IDPEDC = cp.IDPEDC
        LEFT JOIN CABEALBC_FILTRADA ca ON cp.Referencia = ca.Referencia
        LEFT JOIN ARTICULO ar ON a.CODART = ar.CODART
        ORDER BY cp.FECHA, EstadoLogico DESC
    """)
    cats = categorias_proveedor(params)
    for f in filas:
        f['FechaPedido'] = _fecha(f.get('FechaPedido'))
        f['FechaRecepcion'] = _fecha(f.get('FechaRecepcion'))
        situacion = (f.get('SituacionPedido') or '').strip()
        f['SituacionPedido'] = {'S': 'Servido', 'A': 'Pendiente'}.get(situacion, situacion)
        _poner_categoria(f, 'Código Proveedor', cats)
    return filas


@dataset('compras_pendientes', descripcion='Pedidos de compra pendientes de los últimos 6 meses con fecha prevista')
def ds_compras_pendientes(params):
    filas = fuentes.consultar('a3', f"""
        WITH Cabecera AS (
            SELECT C.IDPEDC, C.NUMDOC, LTRIM(RTRIM(C.REFERENCIA)) AS REFERENCIA, LTRIM(RTRIM(C.CODPRO)) AS CODPRO,
                   C.FECHA, C.FECENTREGA, C.TOTDOC,
                   CASE WHEN C.REFERENCIA LIKE '{_REF_VALIDA}' AND LEN(LTRIM(RTRIM(C.REFERENCIA))) = 11
                        THEN 'VALIDA' ELSE 'NO_VALIDA' END AS TIPO_REFERENCIA
            FROM CABEPEDC AS C
            WHERE C.SITUACIONDETALLE LIKE '%PENDIENTE%' AND C.FECHA >= DATEADD(MONTH, -6, GETDATE())
        ),
        Lineas AS (
            SELECT L.IDPEDC, TRIM(L.CODART) AS CODART, SUM(L.BASE) AS TOTAL_LINEA, SUM(L.UNIDADES) AS TOTAL_UNIDADES
            FROM LINEPEDI AS L GROUP BY L.IDPEDC, TRIM(L.CODART)
        )
        SELECT C.NUMDOC, C.REFERENCIA,
               CASE WHEN C.TIPO_REFERENCIA = 'VALIDA' THEN SUBSTRING(C.REFERENCIA, 5, 7) ELSE NULL END AS REFERENCIA_NUM,
               C.CODPRO, C.TIPO_REFERENCIA, MIN(C.FECHA) AS FECHA_MIN,
               DATEADD(DAY, 4, CASE WHEN C.REFERENCIA IS NULL OR LTRIM(RTRIM(C.REFERENCIA)) = '' THEN DATEADD(DAY, 56, MIN(C.FECHA))
                                    WHEN MAX(C.FECENTREGA) IS NULL THEN DATEADD(DAY, 56, MIN(C.FECHA))
                                    ELSE MAX(C.FECENTREGA) END) AS FECENTREGA_MAX,
               DATEDIFF(DAY, MIN(C.FECHA), GETDATE()) AS DIAS_DESDE_PEDIDO,
               DATEDIFF(DAY, GETDATE(), DATEADD(DAY, 4, CASE WHEN C.REFERENCIA IS NULL OR LTRIM(RTRIM(C.REFERENCIA)) = '' THEN DATEADD(DAY, 56, MIN(C.FECHA))
                                    WHEN MAX(C.FECENTREGA) IS NULL THEN DATEADD(DAY, 56, MIN(C.FECHA))
                                    ELSE MAX(C.FECENTREGA) END)) AS DIAS_HASTA_ENTREGA,
               MAX(C.TOTDOC) AS TOTAL_PEDIDO, L.CODART, L.TOTAL_UNIDADES, L.TOTAL_LINEA
        FROM Cabecera AS C LEFT JOIN Lineas AS L ON C.IDPEDC = L.IDPEDC
        GROUP BY C.NUMDOC, C.REFERENCIA, C.CODPRO, C.TIPO_REFERENCIA, L.CODART, L.TOTAL_UNIDADES, L.TOTAL_LINEA
        ORDER BY FECHA_MIN DESC, C.NUMDOC, L.CODART
    """)
    for f in filas:
        f['FECHA_MIN'] = _fecha(f.get('FECHA_MIN'))
        f['FECENTREGA_MAX'] = _fecha(f.get('FECENTREGA_MAX'))
        f['TOTAL_UNIDADES'] = _num(f.get('TOTAL_UNIDADES'))
        f['TOTAL_LINEA'] = _num(f.get('TOTAL_LINEA'))
        f['Estado entrega'] = 'Retrasado' if (f.get('DIAS_HASTA_ENTREGA') or 0) < 0 else 'En plazo'
    return filas


# =============================================================================
# ALMACÉN
# =============================================================================

# Tabla CLASIFICACION del modelo (embebida en el .pbix): medidas de los
# huecos A/B/C en cm; el volumen (m³) es el umbral de cada grupo.
CLASIFICACION = {'A': (79, 120, 190), 'B': (79, 120, 84), 'C': (40, 120, 84)}
FAMILIAS_EXCLUIDAS_CONTEO = {'001', '1', 'MULTIPRE'}


def _volumen_grupo(grupo):
    largo, ancho, alto = CLASIFICACION[grupo]
    return largo * ancho * alto / 1_000_000


@dataset('conteo_paquetes', ttl=1800, descripcion='Paquetes vendidos por artículo en el año y volumen para clasificar huecos A/B/C')
def ds_conteo_paquetes(params):
    filas = fuentes.consultar('a3', """
        SELECT TRIM(A.CODPRO) AS CODPRO, TRIM(A.CODART) AS CODART, A.DESCART, A.CAR1 AS FAMILIA,
               A.UNIPAQV AS [UNIDADES/PAQUETES],
               CASE WHEN UPPER(A.CAR1) IN ('SPRAY200', 'SPARY200') THEN 'SPRAY200'
                    WHEN UPPER(A.CAR1) IN ('SPRAY400', 'SPARY400') THEN 'SPRAY400'
                    WHEN UPPER(A.CAR1) = 'TIZASPRY' THEN 'TIZA' ELSE 'RESTO' END AS AGRUPACION,
               CASE WHEN UPPER(A.CAR1) IN ('ACEITES','GRAFFITI','SPRA MAD','SPRAY AG','SPRAY200','SPRAY400','SPRESPEC','SPRHOGAR','TIZASPRY','TRANSLU') THEN 'SPRAY'
                    WHEN UPPER(A.CAR1) IN ('BOT MAD','BOT TIZA','DISOLVEN','ESM.AGUA') THEN 'LATA'
                    ELSE 'RESTO' END AS MEGA_AGRUPACION,
               SUM(CEILING(L.UNIDADES * 1.0 / NULLIF(A.UNIPAQV, 0))) AS TOTAL_PAQUETES,
               CASE WHEN MONTH(GETDATE()) - 1 > 0
                    THEN CEILING(SUM(CEILING(L.UNIDADES * 1.0 / NULLIF(A.UNIPAQV, 0))) * 1.0 / (MONTH(GETDATE()) - 1))
                    ELSE 0 END AS MEDIA_MENSUAL_PAQUETES
        FROM LINEPEDI L
        JOIN CABEPEDV C ON L.IDPEDV = C.IDPEDV
        JOIN ARTICULO A ON L.CODART = A.CODART
        WHERE YEAR(C.FECHA) = YEAR(GETDATE()) AND MONTH(C.FECHA) <= MONTH(GETDATE()) - 1
          AND (C.SERIE IS NULL OR C.SERIE <> 'R')
        GROUP BY A.CODPRO, A.CODART, A.DESCART, A.CAR1, A.UNIPAQV
        ORDER BY MEDIA_MENSUAL_PAQUETES DESC
    """)
    try:
        volumen = {(f.get('CODART') or '').strip().upper(): f for f in fuentes.leer_gsheet('VOLUMEN_PACKAGING')}
    except Exception:
        log.exception('Sin hoja de volumen de packaging')
        volumen = {}
    try:
        pasillos = {(f.get('CODART') or '').strip().upper(): f.get('FAMILIA DE PASILLO') for f in fuentes.leer_gsheet('PASILLOS')}
    except Exception:
        log.exception('Sin hoja de clasificación de pasillos')
        pasillos = {}
    hue = huecos(params)
    cats = categorias_proveedor(params)
    umbral = {g: _volumen_grupo(g) for g in CLASIFICACION}

    def grupo(vol):
        if vol is None:
            return None
        if vol > umbral['A']:
            return 'A'
        if vol > umbral['B']:
            return 'B'
        return 'C'

    def sobrantes(g, vol, caja):
        if g == 'A' and vol is not None and caja and vol > umbral['A']:
            return math.floor((vol - umbral['A']) / caja)
        return 0

    salida = []
    for f in filas:
        if (f.get('FAMILIA') or '').strip().upper() in FAMILIAS_EXCLUIDAS_CONTEO:
            continue
        cod = (f.get('CODART') or '').strip().upper()
        media_mensual = _num(f.get('MEDIA_MENSUAL_PAQUETES'))
        media_semanal = math.ceil(media_mensual / 30 * 7)
        v = volumen.get(cod, {})
        caja = _num(v.get('VOLUMEN CAJA'), None)
        vol_sem = media_semanal * caja if caja is not None else None
        vol_bis = media_semanal * 2 * caja if caja is not None else None
        vol_men = media_semanal * 4 * caja if caja is not None else None
        g_sem, g_bis, g_men = grupo(vol_sem), grupo(vol_bis), grupo(vol_men)
        h = hue.get(cod, {})
        f.update({
            'MEDIA_SEMANAL_PAQUETE': media_semanal,
            'LARGO': _num(v.get('LARGO'), None), 'ANCHO': _num(v.get('ANCHO'), None), 'ALTO': _num(v.get('ALTO'), None),
            'VOLUMEN CAJA': caja,
            'Volumen Total Semanal': round(vol_sem, 4) if vol_sem is not None else None,
            'Volumen Total Bisemanal': round(vol_bis, 4) if vol_bis is not None else None,
            'Volumen Total Mensual': round(vol_men, 4) if vol_men is not None else None,
            'GRUPO Semanal': g_sem, 'GRUPO Bisemanal': g_bis, 'GRUPO Mensual': g_men,
            'Cajas Sobrantes A Semanal': sobrantes(g_sem, vol_sem, caja),
            'Cajas Sobrantes A Bisemanal': sobrantes(g_bis, vol_bis, caja),
            'Cajas Sobrantes A Mensual': sobrantes(g_men, vol_men, caja),
            'Familia de pasillo': pasillos.get(cod),
            'Etiquetas_Picking': h.get('Etiquetas_Picking'),
            'Etiquetas_Almacenamiento': h.get('Etiquetas_Almacenamiento'),
            'TOTAL_PAQUETES': _num(f.get('TOTAL_PAQUETES')),
            'MEDIA_MENSUAL_PAQUETES': media_mensual,
        })
        _poner_categoria(f, 'CODPRO', cats)
        salida.append(f)
    return salida


@dataset('stock_almacen', descripcion='Stock por artículo en Innertia (Informe Almacén) con picking y almacenamiento')
def ds_stock_almacen(params):
    ubic = _ubicaciones(params)
    disponible = stock_disponible_innertia(ubic)
    hue = huecos(params)
    salida = []
    for art in sorted(set(disponible) | set(hue)):
        h = hue.get(art, {})
        salida.append({
            'idArticulo': art,
            'Stock Total': h.get('Total', 0.0),
            'Stock Disponible': disponible.get(art, 0.0),
            'Picking': h.get('Picking', 0.0),
            'Almacenamiento': h.get('Almacenamiento', 0.0),
            'Etiquetas_Picking': h.get('Etiquetas_Picking'),
            'Etiquetas_Almacenamiento': h.get('Etiquetas_Almacenamiento'),
        })
    return salida


# =============================================================================
# LOGÍSTICA (coste de transporte)
# =============================================================================

def _codprovi_cp(cp):
    digitos = re.sub(r'\D', '', str(cp or ''))
    if not digitos:
        return None
    valor = int(digitos)
    if 1 <= valor <= 9999:
        return str(max(1, valor // 1000)).zfill(2)
    if 10000 <= valor <= 99999:
        return digitos[:2]
    return '00'


def _rango_peso(peso):
    if peso is None or peso <= 100:
        return '0-100'
    for limite, rango in ((200, '101-200'), (400, '201-400'), (500, '401-500'), (700, '501-700'), (900, '701-900')):
        if peso <= limite:
            return rango
    return '900+'


def _escalado(rango, contenedores):
    palets = contenedores if contenedores else None
    if palets is None:
        return None
    p = int(palets)
    tablas = {
        '0-100': lambda: '1-7',
        '101-200': lambda: '1' if p == 1 else '2-7',
        '201-400': lambda: {1: '1', 2: '2'}.get(p, '3-7'),
        '401-500': lambda: {1: '1', 2: '2', 3: '3'}.get(p, '4-7'),
        '501-700': lambda: {1: '1', 2: '2', 3: '3', 4: '4'}.get(p, '4-7'),
        '701-900': lambda: {1: '1', 2: '2', 3: '3', 4: '4'}.get(p, '5-7'),
    }
    return tablas.get(rango, lambda: str(p) if p <= 6 else '7')()


def precios_transporte():
    """Tarifa del transportista: (provincia, rango de peso, escalado) → precio €.
    La hoja tiene tres filas de cabecera (rango, tamaño, escalado)."""
    def calcular():
        filas = fuentes.leer_gsheet_filas('PRECIOS_TRANSPORTE')
        if len(filas) < 4:
            return {}
        cab_rango, cab_escalado = filas[0], filas[2]
        tarifa = {}
        for fila in filas[3:]:
            provincia = (fila[0] or '').strip().upper()
            for i in range(1, len(fila)):
                rango = (cab_rango[i] if i < len(cab_rango) else '').split(' ')[0]
                escalado = (cab_escalado[i] if i < len(cab_escalado) else '').strip()
                precio = _num(fila[i], None)
                if provincia and precio is not None:
                    tarifa[(provincia, rango, escalado)] = precio / 100
        return tarifa
    return _aux('precios_transporte', calcular)


@dataset('expediciones_transporte', descripcion='Expediciones de ONTIME con el precio teórico de la tarifa')
def ds_expediciones(params):
    filas = fuentes.leer_gsheet_filas('EXPEDICIONES')
    if len(filas) < 2:
        return []
    cabecera = [c.strip() for c in filas[0]]
    provs = provincias()
    tarifa = precios_transporte()
    vistos = set()
    salida = []
    for cruda in filas[1:]:
        f = {cabecera[i]: (v or '').strip() for i, v in enumerate(cruda) if i < len(cabecera) and cabecera[i]}
        ident = f.get('Id Expedición')
        if not ident or 'Id Expedición' in ident or ident in vistos:
            continue
        if 'ONTIME' not in (f.get('Agencia de Transporte') or '').upper():
            continue
        vistos.add(ident)
        peso = _num(f.get('Peso'), None)
        contenedores = _num(f.get('Contenedores Logísticos'), None)
        codprovi = _codprovi_cp(f.get('C.P. Envío'))
        provincia = provs.get(codprovi, {}).get('Provincia Limpia')
        rango = _rango_peso(peso)
        escalado = _escalado(rango, contenedores)
        precio = tarifa.get(((provincia or '').upper(), rango, escalado))
        salida.append({
            'Id Expedición': ident, 'Estado': f.get('Estado'), 'Fecha pedido': _fecha(f.get('Fecha pedido')),
            'Fecha envío': _fecha(f.get('Fecha envío')), 'Cód. Cliente': f.get('Cód. Cliente'),
            'Cliente': f.get('Cliente'), 'Agencia de Transporte': f.get('Agencia de Transporte'),
            'Vendedor': f.get('Vendedor'), 'Usuario Verif.': f.get('Usuario Verif.'),
            'Contenedores Logísticos': contenedores, 'Peso': peso, 'C.P. Envío': f.get('C.P. Envío'),
            'Provincia Limpia': provincia, 'Rango Peso': rango, 'Escalado Asignado': escalado,
            'Precio Teórico': precio,
            'Precio Teorico Total': round(precio * contenedores, 2) if precio is not None and contenedores else None,
        })
    return salida


def _codcli_desde_texto(*textos):
    for texto in textos:
        texto = texto or ''
        m = re.search(r'\*([^*]+)\*', texto) or re.search(r'\(([^)]+)\)', texto)
        if m:
            return m.group(1).strip().split(' ')[0]
    return None


@dataset('cobro_transporte', descripcion='Portes facturados por el transportista contra la tarifa teórica')
def ds_cobro_transporte(params):
    filas = fuentes.leer_gsheet('COBRO_TRANSPORTE')
    provs = provincias()
    tarifa = precios_transporte()
    salida = []
    for f in filas:
        ref = (f.get('Ref. Cliente') or '').strip()
        if not ref:
            continue
        kilos = _num(f.get('Kilos'), None)
        bultos = _num(f.get('Bultos/Palets'), None)
        total = _num(f.get('Total'), None)
        unidad = (kilos / bultos) if kilos is not None and bultos else 0
        codcli = _codcli_desde_texto(f.get('Consignatario'), f.get('Remitente')) or (ref.rsplit('-', 1)[-1] if '-' in ref else None)
        codprovi = _codprovi_cp(f.get('CP Consignatario'))
        provincia = provs.get(codprovi, {}).get('Provincia Limpia')
        rango = _rango_peso(kilos)
        escalado = _escalado(rango, bultos)
        precio = tarifa.get(((provincia or '').upper(), rango, escalado))
        precio_total = precio * bultos if precio is not None and bultos else None
        salida.append({
            'Ref. Cliente': ref, 'Fecha': _fecha(f.get('Fecha')), 'CODCLI': codcli,
            'Consignatario': f.get('Consignatario'), 'CP Consignatario': f.get('CP Consignatario'),
            'Provincia Limpia': provincia, 'Bultos/Palets': bultos, 'Kilos': kilos, 'Total': total,
            'TIPOLOGÍA': 'BULTO' if unidad < 50 else 'PALET', 'Rango Peso': rango, 'Escalado Asignado': escalado,
            'Precio Teórico': precio, 'Precio Teórico Total': round(precio_total, 2) if precio_total is not None else None,
            'Total Unitario': round(total / bultos, 2) if total is not None and bultos else None,
            'Diferencia Precio Facturado / Teorico': round(total - precio_total, 2) if total is not None and precio_total is not None else None,
            'Diferencia Precio Facturado / Teorico Unitario': round(total / bultos - precio, 2) if total is not None and bultos and precio is not None else None,
        })
    return salida


# =============================================================================
# Entrada desde el túnel
# =============================================================================

def _columnar(filas):
    columnas = []
    vistas = set()
    for fila in filas:
        for col in fila:
            if col not in vistas:
                vistas.add(col)
                columnas.append(col)
    return columnas, [[fila.get(col) for col in columnas] for fila in filas]


def _codificar_diccionario(columnas, filas):
    """Codificación por diccionario de las columnas de texto repetitivas
    (cliente, familia, representante...): en vez del texto, cada celda lleva
    su índice en `dicts[i]`. Con decenas de miles de filas el JSON baja a
    una fracción; el navegador lo deshace al recibirlo (informes.js)."""
    if len(filas) < 200:
        return filas, {}
    dicts = {}
    for i in range(len(columnas)):
        valores = [fila[i] for fila in filas]
        textos = [v for v in valores if isinstance(v, str)]
        if len(textos) < len(valores) * 0.5:
            continue
        distintos = {}
        for v in valores:
            if v not in distintos:
                distintos[v] = len(distintos)
        if len(distintos) > len(valores) * 0.5:
            continue
        dicts[str(i)] = list(distintos)
        for fila in filas:
            fila[i] = distintos[fila[i]]
    return filas, dicts


def get_dataset(name=None, refrescar=False, **params):
    """Handler de la query 'dataset': devuelve {'columns', 'rows', 'updated_at'}.
    Formato columnar (como Stock Tabla) para no repetir el nombre de cada
    columna en cada fila del JSON que cruza el túnel."""
    info = DATASETS.get(name)
    if info is None:
        raise ValueError(f'dataset desconocido: {name}')
    clave = _clave_cache(name, params)
    if refrescar:
        _CACHE.pop(clave, None)
    entrada = _memo(clave, info['ttl'], lambda: info['func'](params))
    columnas, filas = _columnar(entrada['valor'])
    filas, dicts = _codificar_diccionario(columnas, filas)
    return {
        'rows': filas, 'columns': columnas, 'dicts': dicts, 'updated_at': entrada['actualizado'],
        'query_seconds': entrada['segundos'],
    }


def get_datasets_list(**params):
    return {'rows': [
        {'name': nombre, 'descripcion': info['descripcion'], 'ttl': info['ttl']}
        for nombre, info in sorted(DATASETS.items())
    ]}


def get_sources_status(comprobar=True, **params):
    return {
        'rows': [],
        'config': fuentes.describir(),
        'status': fuentes.comprobar() if comprobar else {},
        'datasets': sorted(DATASETS),
    }
