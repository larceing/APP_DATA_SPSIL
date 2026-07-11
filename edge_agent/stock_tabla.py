"""Réplica del informe "Control_Stock" de Power BI (sector Compras).

Traduce a SQL/Python el pipeline de Power Query que dio el usuario: stock
por almacén (SQL Server), categoría de proveedor (importada una vez en
servidor Y y recibida aquí por el túnel, ya no se lee de Google Sheets),
histórico de ventas (SQL Server, RANK() sobre LINEOFER), tamaño de envase
(umbrales fijos) y el desglose Picking/Almacenamiento + etiquetas de
ubicación física (MariaDB).

No usa pandas a propósito: el volumen de artículos es modesto (cientos, no
millones) y las combinaciones se hacen con diccionarios normales, sin
añadir una dependencia pesada solo por comodidad.
"""

import datetime
import logging
import time

import pymysql
import pytds

import cache
from db import ID_ALMACEN, ID_CENTRO, MARIADB_DATABASE, MARIADB_HOST, MARIADB_PASSWORD, MARIADB_PORT, MARIADB_USER
from db import MSSQL_DATABASE, MSSQL_HOST, MSSQL_PASSWORD, MSSQL_USER
from db import _normalize
from db import _query_stock as _query_stock_innertia

log = logging.getLogger('edge_agent')

# Umbrales de tamaño (Volumetría), fijos — no vienen de ninguna BD.
VOLUMETRIA = {
    'GRANDE': {'400ML': 1632, '200ML': 2640},
    'MEDIO': {'400ML': 816, '200ML': 1344},
    'PEQUEÑO': {'400ML': 408, '200ML': 768},
}

# Multiplicadores de Stock Mín/Máx/Punto de Pedido según categoría de proveedor.
MULTIPLICADORES = {
    1: {'min': 1.0, 'max': 2.0, 'punto': 1.5},
    2: {'min': 3.0, 'max': 6.0, 'punto': 4.0},
    3: {'min': 1.0, 'max': 3.0, 'punto': 2.0},
    4: {'min': 0.5, 'max': 1.5, 'punto': 1.0},
}
MULTIPLICADOR_DEFECTO = {'min': 1.0, 'max': 1.0, 'punto': 1.0}


def _mssql_connect():
    return pytds.connect(server=MSSQL_HOST, database=MSSQL_DATABASE, user=MSSQL_USER, password=MSSQL_PASSWORD)


def _mariadb_connect():
    return pymysql.connect(
        host=MARIADB_HOST, port=MARIADB_PORT, user=MARIADB_USER,
        password=MARIADB_PASSWORD, database=MARIADB_DATABASE,
    )


def _query_stock_raw():
    """dbo.VW_OFERTAS_STOCK_RAW: una fila por artículo con sus stocks por
    almacén, ventas de los últimos 30 días y la reserva pendiente de compra.
    Devuelve dict keyed por CODART normalizado."""
    conn = _mssql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM dbo.VW_OFERTAS_STOCK_RAW')
            columns = [d[0] for d in cur.description]
            filas = {}
            for row_tuple in cur.fetchall():
                row = dict(zip(columns, row_tuple))
                codart = _normalize(row.get('CODART'))
                if not codart:
                    continue

                # La columna de reserva pendiente ha tenido varios nombres
                # a lo largo del tiempo (igual que el M original).
                reserva_b = (
                    row.get('Reserva B')
                    or row.get('Unidad Pendiente de Compra Refer.')
                    or row.get('Unidad Pendiente de Compra Refer_')
                    or 0
                )

                stock_1 = float(row.get('Stock Almacen 1') or 0)
                stock_aspe = float(row.get('Stock Almacen 2') or 0)
                stock_toledo = float(row.get('Stock Almacen Toledo') or 0)

                filas[codart] = {
                    'CODPRO': row.get('CODPRO'),
                    'CODART': row.get('CODART'),
                    'Cod. Articulo': _normalize(row.get('Cod. Articulo')),
                    'Descripcion': row.get('Descripcion'),
                    'UndPtos Ultimo 30 dias': float(row.get('UndPtos Ultimo 30 dias') or 0),
                    'Reserva B': float(reserva_b or 0),
                    'Stock Almacen 1': stock_1,
                    'Stock Almacen ASPE': stock_aspe,
                    'Stock Almacen Toledo': stock_toledo,
                    'Stock Total': stock_1 + stock_aspe + stock_toledo,
                    'Reservas': float(row.get('Reservas') or 0),
                    'Familia': row.get('Familia') or '',
                }
            return filas
    finally:
        conn.close()


_VENTAS_MES_SQL = """
SELECT codArt, SUM(unidades) AS TotalUnidades
FROM lineofer
WHERE idofev IS NOT NULL AND unidades > 0 AND COMVEN = 'V'
  AND FECHA >= %s AND FECHA < %s
GROUP BY codArt
"""

# Estado incremental de ventas: (codart, año, mes) -> unidades vendidas.
# Se carga entero una sola vez (_cargar_ventas_base, al arrancar el
# agente) y luego cada ciclo de refresco solo sustituye el mes en curso
# (_refrescar_ventas_mes_actual) — nunca se vuelve a escanear el año
# completo. Los meses ya cerrados no cambian, así que no hace falta
# tocarlos de nuevo.
_VENTAS_ESTADO = {'por_mes': {}, 'cargado': False}


def _rango_mes(anio, mes):
    desde = datetime.date(anio, mes, 1)
    hasta = datetime.date(anio + 1, 1, 1) if mes == 12 else datetime.date(anio, mes + 1, 1)
    return desde, hasta


def _query_ventas_mes(anio, mes):
    """Unidades vendidas por artículo en un único mes (consulta barata:
    rango de fechas sargable, agrupado por artículo, sin RANK())."""
    desde, hasta = _rango_mes(anio, mes)
    conn = _mssql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_VENTAS_MES_SQL, (desde, hasta))
            return {_normalize(codart): float(total or 0) for codart, total in cur.fetchall() if codart}
    finally:
        conn.close()


def _meses_a_cargar():
    """Todo el año anterior (cerrado) + el año actual hasta el mes de
    hoy — el mismo rango que antes cubría la consulta de RANK() sobre
    los dos años, pero mes a mes."""
    hoy = datetime.date.today()
    meses = [(hoy.year - 1, mes) for mes in range(1, 13)]
    meses += [(hoy.year, mes) for mes in range(1, hoy.month + 1)]
    return meses


def _cargar_ventas_base():
    """Carga completa mes a mes. Solo se ejecuta una vez (primer ciclo
    tras arrancar el agente); puede tardar, no hay problema porque no
    bloquea ninguna petición — corre en segundo plano."""
    por_mes = {}
    for anio, mes in _meses_a_cargar():
        for codart, total in _query_ventas_mes(anio, mes).items():
            por_mes[(codart, anio, mes)] = total
    _VENTAS_ESTADO['por_mes'] = por_mes
    _VENTAS_ESTADO['cargado'] = True


def _refrescar_ventas_mes_actual():
    """Sustituye (no suma) el mes en curso por su valor real más
    reciente. Al reemplazar en vez de sumar, un artículo que ya no vende
    no se queda con un número inflado, y no hay riesgo de contar dos
    veces la misma venta entre un ciclo y el siguiente."""
    hoy = datetime.date.today()
    frescos = _query_ventas_mes(hoy.year, hoy.month)
    por_mes = _VENTAS_ESTADO['por_mes']
    for clave in [k for k in por_mes if k[1] == hoy.year and k[2] == hoy.month]:
        del por_mes[clave]
    for codart, total in frescos.items():
        por_mes[(codart, hoy.year, hoy.month)] = total


def _actualizar_ventas():
    if not _VENTAS_ESTADO['cargado']:
        _cargar_ventas_base()
    else:
        _refrescar_ventas_mes_actual()


def _mejores_ventas_por_articulo(anio):
    """Media de los 3 mejores meses de venta de `anio`, por artículo —
    mismo cálculo que el Power BI original (RoundUp(suma top-3 / 3)),
    pero calculado en Python sobre el estado ya cargado en memoria, sin
    ninguna consulta a BD."""
    por_articulo = {}
    for (codart, anio_fila, mes), total in _VENTAS_ESTADO['por_mes'].items():
        if anio_fila != anio:
            continue
        por_articulo.setdefault(codart, []).append((mes, total))

    resultado = {}
    for codart, meses in por_articulo.items():
        top3 = sorted(meses, key=lambda par: (-par[1], -par[0]))[:3]
        mejor_mes, mejor_venta = top3[0]
        resultado[codart] = {
            'ventas': -(-sum(total for _, total in top3) // 3),  # RoundUp(suma/3)
            'mejor_mes': mejor_mes,
            'mejor_anio': anio,
            'mejor_venta': mejor_venta,
        }
    return resultado


def _query_agrupacion_y_etiquetado():
    """Vista ArticuloHuecoStock (idCentro=6, idAlmacen=1, idZona=1) +
    Hueco + TipoHueco: desglose de stock por artículo por cada tipo de
    hueco físico real (TipoHueco.descripcion tal cual viene de la BD, sin
    adivinar aquí si es Picking/Almacenamiento — eso lo decide la
    configuración de servidor Y en build_rows). Devuelve:
    - tipos_hueco_raw: {idArticulo: {descripcion: unidades}}
    - etiquetas_raw: {idArticulo: {descripcion: set(etiquetas)}}
    """
    conn = _mariadb_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT ae.idArticulo, ae.unidad1, h.etiqueta, th.descripcion '
                'FROM ArticuloHuecoStock ae '
                'JOIN Hueco h '
                '  ON h.idCentro = ae.idCentro AND h.idAlmacen = ae.idAlmacen AND h.idZona = ae.idZona '
                '  AND h.idCalle = ae.idCalle AND h.idSeccion = ae.idSeccion AND h.idNivel = ae.idNivel '
                '  AND h.idHueco = ae.idHueco AND h.idSubhueco = ae.idSubHueco '
                'JOIN TipoHueco th ON th.idTipoHueco = h.tipoHueco '
                'WHERE ae.idCentro = %s AND ae.idAlmacen = %s AND ae.idZona = 1',
                (ID_CENTRO, ID_ALMACEN),
            )
            filas = cur.fetchall()
    finally:
        conn.close()

    tipos_hueco_raw = {}
    etiquetas_raw = {}
    for id_articulo, unidad1, etiqueta, descripcion in filas:
        clave = _normalize(id_articulo)
        descripcion_norm = (descripcion or '').strip()
        if not descripcion_norm:
            continue
        unidad1 = float(unidad1 or 0)

        por_tipo = tipos_hueco_raw.setdefault(clave, {})
        por_tipo[descripcion_norm] = por_tipo.get(descripcion_norm, 0.0) + unidad1

        if etiqueta:
            por_tipo_etq = etiquetas_raw.setdefault(clave, {})
            por_tipo_etq.setdefault(descripcion_norm, set()).add(etiqueta.strip())

    return tipos_hueco_raw, etiquetas_raw


def _calcular_size(id_articulo, descripcion, familia, stock_min_semanal):
    texto = f'{descripcion or ""} {familia or ""}'.upper()
    if '400' in texto:
        capacidad = '400ML'
    elif '200' in texto:
        capacidad = '200ML'
    else:
        return 'DESCONOCIDO'

    umbral_grande = VOLUMETRIA['GRANDE'][capacidad]
    umbral_medio = VOLUMETRIA['MEDIO'][capacidad]
    umbral_pequeno = VOLUMETRIA['PEQUEÑO'][capacidad]

    if stock_min_semanal <= umbral_pequeno:
        return 'PEQUEÑO'
    if stock_min_semanal <= umbral_medio:
        return 'MEDIO'
    if stock_min_semanal <= umbral_grande:
        return 'GRANDE'
    return 'EXTRA'


def _refrescar_stock_raw():
    """compute_fn de la caché 'stock_raw' (ver agent.py): VW_OFERTAS_STOCK_RAW
    se llama tal cual, sin filtro, y tarda ~26s en escanearse entera. No es
    un histórico (no admite "mini updates del mes en curso" como ventas),
    así que va en su propia caché con un ciclo más espaciado (30s por
    defecto), independiente del de ventas/huecos (que ya es barato y
    puede ir cada 15s) — así lo lento no frena lo rápido."""
    t0 = time.monotonic()
    stock = _query_stock_raw()
    log.info('stock_raw=%.1fs', time.monotonic() - t0)
    return stock


def _refrescar_ventas_y_huecos():
    """compute_fn de la caché 'stock_tabla_ventas_huecos': todo lo que ya
    es barato de refrescar a menudo — ventas (incremental, ver
    _actualizar_ventas), stock del WMS (Innertia) y el desglose por tipo
    de hueco. Devuelve también tipos_hueco_descubiertos para que servidor
    Y registre los tipos nuevos en /gateway/config/tipos-hueco/."""
    t0 = time.monotonic()
    _actualizar_ventas()
    anio_actual = datetime.date.today().year
    ventas_actual = _mejores_ventas_por_articulo(anio_actual)
    ventas_anterior = _mejores_ventas_por_articulo(anio_actual - 1)
    t1 = time.monotonic()
    stock_innertia = _query_stock_innertia()
    t2 = time.monotonic()
    tipos_hueco_raw, etiquetas_raw = _query_agrupacion_y_etiquetado()
    t3 = time.monotonic()
    log.info(
        'ventas=%.1fs stock_innertia=%.1fs tipos_hueco=%.1fs',
        t1 - t0, t2 - t1, t3 - t2,
    )
    tipos_descubiertos = set()
    for tipos in tipos_hueco_raw.values():
        tipos_descubiertos.update(tipos.keys())
    return {
        'ventas_actual': ventas_actual,
        'ventas_anterior': ventas_anterior,
        'stock_innertia': stock_innertia,
        'tipos_hueco_raw': tipos_hueco_raw,
        'etiquetas_raw': etiquetas_raw,
        'tipos_hueco_descubiertos': sorted(tipos_descubiertos),
    }


def _merge_base_data():
    """Combina las dos cachés (stock_raw + ventas/huecos) en la lista de
    filas base que usa build_rows. Cálculo puro en memoria — se llama en
    el camino de la petición (get_stock_tabla), no en segundo plano;
    fusionar ~2500 artículos es barato, lo caro ya está cacheado aparte.
    Devuelve None si alguna de las dos cachés todavía no tiene datos.
    """
    entry_stock = cache.get('stock_raw')
    entry_resto = cache.get('stock_tabla_ventas_huecos')
    if entry_stock is None or entry_resto is None:
        return None

    stock = entry_stock['data']
    resto = entry_resto['data']
    ventas_actual = resto['ventas_actual']
    ventas_anterior = resto['ventas_anterior']
    stock_innertia = resto['stock_innertia']
    tipos_hueco_raw = resto['tipos_hueco_raw']
    etiquetas_raw = resto['etiquetas_raw']

    base_rows = []
    for codart, base in stock.items():
        clave_ventas = base['Cod. Articulo'] or codart
        v_actual = ventas_actual.get(clave_ventas, {})
        v_anterior = ventas_anterior.get(clave_ventas, {})

        media_ventas_anio_anterior = v_anterior.get('ventas', 0)
        media_base_stock = max(base['UndPtos Ultimo 30 dias'], media_ventas_anio_anterior)
        origen_media_base_stock = (
            'Últimos 30 días' if base['UndPtos Ultimo 30 dias'] >= media_ventas_anio_anterior else 'Año anterior'
        )

        stock_reserva_a = base['Stock Total'] + base['Reservas']
        stock_reserva_b = base['Stock Total'] + base['Reserva B']
        stock_reserva_a_b = stock_reserva_a + base['Reserva B']

        # Stock_Total_Innertia es el stock según el WMS (MariaDB,
        # StockDisponibleCentroAlmacen — misma fuente que la página
        # Stock normal), no una suma del desglose por tipo de hueco:
        # "Dif_A3_menos_Inn" compara dos sistemas distintos (ERP vs WMS).
        total_stock_ita = stock_innertia.get(codart, 0.0)
        stock_inn_reserva_a = total_stock_ita + base['Reservas']
        stock_inn_reserva_b = total_stock_ita + base['Reserva B']
        stock_inn_reserva_a_b = stock_inn_reserva_a + base['Reserva B']

        tipos_articulo = tipos_hueco_raw.get(codart, {})
        etiquetas_articulo = etiquetas_raw.get(codart, {})

        base_rows.append({
            # CODART va primero a propósito: el frontend fija (sticky) la
            # primera columna al hacer scroll horizontal, para que se
            # sepa siempre en qué artículo se está aunque la tabla tenga
            # muchas columnas (ver gateway/templates/gateway/stock_tabla.html).
            'CODART': base['CODART'],
            'CODPRO': base['CODPRO'],
            'CODDESCART': f'{base["CODART"]} - {base["Descripcion"]}',
            'Descripcion': base['Descripcion'],
            'Familia': base['Familia'],
            'Stock_Almacen_1': base['Stock Almacen 1'],
            'Stock_Almacen_ASPE': base['Stock Almacen ASPE'],
            'Stock_Almacen_Toledo': base['Stock Almacen Toledo'],
            'Stock_Total': base['Stock Total'],
            'Reservas': base['Reservas'],
            'Reserva_B': base['Reserva B'],
            'Reserva_A_mas_B': base['Reservas'] + base['Reserva B'],
            'Media_Ventas_Mes': v_actual.get('ventas', 0),
            'MejorMes': v_actual.get('mejor_mes'),
            'MejorAnio': v_actual.get('mejor_anio'),
            'MejorVenta': v_actual.get('mejor_venta', 0),
            'Media_Ventas_Anio_Anterior': media_ventas_anio_anterior,
            'Media_Base_Stock': media_base_stock,
            'Origen_Media_Base_Stock': origen_media_base_stock,
            'Stock_mas_Reserva_A': stock_reserva_a,
            'Stock_mas_Reserva_B': stock_reserva_b,
            'Stock_mas_Reserva_A_mas_B': stock_reserva_a_b,
            'Stock_Total_Innertia': total_stock_ita,
            'Dif_A3_menos_Inn': base['Stock Total'] - total_stock_ita,
            'Stock_Inn_mas_Reserva_A': stock_inn_reserva_a,
            'Stock_Inn_mas_Reserva_B': stock_inn_reserva_b,
            'Stock_Inn_mas_Reserva_A_mas_B': stock_inn_reserva_a_b,
            '_tipos_hueco_raw': tipos_articulo,
            '_etiquetas_raw': etiquetas_articulo,
        })
    return {'rows': base_rows, 'tipos_hueco_descubiertos': resto['tipos_hueco_descubiertos']}


def _bucket_tipos_hueco(tipos_raw, mapeo_categoria):
    """Reparte {descripcion: unidades} en Picking/Almacenamiento/
    Sin_Clasificar según la configuración que llega de servidor Y
    (mapeo_categoria: descripcion -> 'picking'/'almacenamiento'/'ignorar').
    Cualquier descripción que todavía no esté configurada cae en
    Sin_Clasificar — nunca desaparece stock en silencio."""
    totales = {'picking': 0.0, 'almacenamiento': 0.0, 'ignorar': 0.0}
    for descripcion, unidades in tipos_raw.items():
        categoria = mapeo_categoria.get(descripcion, 'ignorar')
        totales[categoria if categoria in totales else 'ignorar'] += unidades
    return totales


def _bucket_etiquetas_hueco(etiquetas_raw, mapeo_categoria):
    grupos = {'picking': set(), 'almacenamiento': set(), 'ignorar': set()}
    for descripcion, etiquetas in etiquetas_raw.items():
        categoria = mapeo_categoria.get(descripcion, 'ignorar')
        grupos[categoria if categoria in grupos else 'ignorar'].update(etiquetas)
    return {
        clave: ', '.join(sorted(valores)) or None
        for clave, valores in grupos.items()
    }


def build_rows(base_data, supplier_categories=None, hueco_tipos=None):
    """Aplica configuración que solo llega por petición desde servidor Y
    (categoría de proveedor, clasificación de tipos de hueco) sobre la
    base ya precalculada por _compute_base_data(). Cálculo puro en
    memoria, sin ninguna consulta a BD — esta es la parte que sí corre en
    el camino crítico de cada petición, y por eso tiene que ser barata.
    """
    categorias = {
        _normalize(row.get('codpro')): {
            'categoria': int(row.get('categoria') or 0),
            'organizacion': row.get('organizacion') or '',
        }
        for row in (supplier_categories or [])
    }
    mapeo_hueco = {row['descripcion']: row['categoria'] for row in (hueco_tipos or [])}

    rows = []
    for base in base_data:
        cat_info = categorias.get(_normalize(base['CODPRO']), {})
        categoria = cat_info.get('categoria', 0)
        organizacion = cat_info.get('organizacion', '')
        mult = MULTIPLICADORES.get(categoria, MULTIPLICADOR_DEFECTO)

        media_base_stock = base['Media_Base_Stock']
        stock_min = round(media_base_stock * mult['min'])
        stock_max = round(media_base_stock * mult['max'])
        punto_pedido = round(media_base_stock * mult['punto'])

        ratio_stock_min = round(base['Stock_mas_Reserva_B'] / stock_min, 2) if stock_min else 0
        diferencial_cantidad_pedido = 0
        if base['Stock_mas_Reserva_A_mas_B'] < punto_pedido:
            diferencial_cantidad_pedido = (
                (stock_max - base['Stock_mas_Reserva_A_mas_B']) if categoria == 2
                else (punto_pedido - base['Stock_mas_Reserva_A_mas_B'])
            )

        dias_periodo = mult['min'] * 30
        stock_min_semanal = round((stock_min / dias_periodo if dias_periodo else 0) * 7)

        ratio_stock_min_inn = round(base['Stock_Inn_mas_Reserva_B'] / stock_min, 2) if stock_min else 0
        diferencial_cantidad_pedido_inn = 0
        if base['Stock_Inn_mas_Reserva_A_mas_B'] < punto_pedido:
            diferencial_cantidad_pedido_inn = (
                (stock_max - base['Stock_Inn_mas_Reserva_A_mas_B']) if categoria == 2
                else (punto_pedido - base['Stock_Inn_mas_Reserva_A_mas_B'])
            )

        tipos = _bucket_tipos_hueco(base['_tipos_hueco_raw'], mapeo_hueco)
        etiquetas = _bucket_etiquetas_hueco(base['_etiquetas_raw'], mapeo_hueco)
        base_sin_internos = {k: v for k, v in base.items() if not k.startswith('_')}

        rows.append({
            **base_sin_internos,
            'Categoria_Organizacion': organizacion,
            'Categoria_Proveedor': categoria,
            'StockMin': stock_min,
            'StockMax': stock_max,
            'PuntoPedido': punto_pedido,
            'Ratio_Stock_Min': ratio_stock_min,
            'Diferencial_Cantidad_Pedido_A3': diferencial_cantidad_pedido,
            'Stock_Total_dividido_StockMin': round(base['Stock_Total'] / stock_min, 2) if stock_min else 0,
            'StockMin_Semanal': stock_min_semanal,
            'Ratio_Stock_Min_Innertia': ratio_stock_min_inn,
            'Diferencial_Cantidad_Pedido_Innertia': diferencial_cantidad_pedido_inn,
            'Stock_Innertia_dividido_StockMin': round(base['Stock_Total_Innertia'] / stock_min, 2) if stock_min else 0,
            'SIZE': _calcular_size(base['CODART'], base['Descripcion'], base['Familia'], stock_min_semanal),
            'Picking': tipos['picking'],
            'Almacenamiento': tipos['almacenamiento'],
            'Sin_Clasificar': tipos['ignorar'],
            'Etiquetas_Picking': etiquetas['picking'],
            'Etiquetas_Almacenamiento': etiquetas['almacenamiento'],
            'Etiquetas_Sin_Clasificar': etiquetas['ignorar'],
        })

    rows.sort(key=lambda r: r['CODART'] or '')
    return rows


def get_stock_tabla(supplier_categories=None, hueco_tipos=None, **params):
    """Handler registrado en agent.py para la query 'stock_tabla': fusiona
    las dos cachés ya precalculadas en segundo plano (stock_raw cada 30s,
    ventas/huecos cada 15s — ver agent.py) y les aplica la configuración
    que llega por petición (categoría de proveedor, clasificación de
    tipos de hueco). Nunca toca la BD aquí — si el agente acaba de
    arrancar y todavía no hay ni un ciclo de cada caché completo, informa
    de ello en vez de bloquear la petición esperando una consulta pesada.
    """
    data = _merge_base_data()
    if data is None:
        raise RuntimeError('cache_warming')
    return {
        'rows': build_rows(data['rows'], supplier_categories, hueco_tipos),
        'tipos_hueco_descubiertos': data['tipos_hueco_descubiertos'],
    }
