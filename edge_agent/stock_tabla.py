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

import pymysql
import pytds

from db import ID_CENTRO, MARIADB_DATABASE, MARIADB_HOST, MARIADB_PASSWORD, MARIADB_PORT, MARIADB_USER
from db import MSSQL_DATABASE, MSSQL_HOST, MSSQL_PASSWORD, MSSQL_USER
from db import _normalize

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


_VENTAS_SQL = """
SELECT distinct
    codArt,
    YEAR(LINEOFER.FECHA) AS Anio,
    MONTH(LINEOFER.FECHA) AS Mes,
    SUM(unidades) AS TotalUnidades,
    RANK() over (PARTITION by codArt ORDER BY SUM(UNIDADES) DESC, YEAR(LINEOFER.FECHA) DESC, MONTH(LINEOFER.FECHA) DESC) AS Rango
FROM lineofer
WHERE
    idofev IS NOT NULL
    AND unidades > 0 AND YEAR(LINEOFER.FECHA) = %s and COMVEN = 'V'
GROUP BY codArt, YEAR(LINEOFER.FECHA), MONTH(LINEOFER.FECHA)
"""


def _query_mejores_ventas(anio):
    """Media de los 3 mejores meses de venta de ese año, por artículo
    (mismo SQL que el Power BI original, con RANK() ya en el propio SQL
    Server; aquí solo se filtra Rango<=3 y se agrupa, igual que el M)."""
    conn = _mssql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_VENTAS_SQL, (anio,))
            filas = cur.fetchall()
    finally:
        conn.close()

    por_articulo = {}
    for cod_art, anio_fila, mes, total_unidades, rango in filas:
        if rango > 3:
            continue
        clave = _normalize(cod_art)
        por_articulo.setdefault(clave, []).append({
            'anio': anio_fila, 'mes': mes, 'unidades': total_unidades, 'rango': rango,
        })

    resultado = {}
    for clave, meses in por_articulo.items():
        media = -(-sum(m['unidades'] for m in meses) // 3)  # RoundUp(suma/3)
        mejor = next(m for m in meses if m['rango'] == 1)
        resultado[clave] = {
            'ventas': media,
            'mejor_mes': mejor['mes'],
            'mejor_anio': mejor['anio'],
            'mejor_venta': mejor['unidades'],
        }
    return resultado


def _query_agrupacion_y_etiquetado():
    """Hueco (idCentro=6) + TipoHueco + ArticuloEstipulado: desglose de
    stock por artículo en Picking/Almacenamiento, y las etiquetas físicas
    de cada zona (columna Hueco.etiqueta). Devuelve dos dicts keyed por
    idArticulo normalizado."""
    conn = _mariadb_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT ae.idArticulo, ae.unidad1, h.etiqueta, th.descripcion '
                'FROM ArticuloEstipulado ae '
                'JOIN Hueco h '
                '  ON h.idCentro = ae.idCentro AND h.idAlmacen = ae.idAlmacen AND h.idZona = ae.idZona '
                '  AND h.idCalle = ae.idCalle AND h.idSeccion = ae.idSeccion AND h.idNivel = ae.idNivel '
                '  AND h.idHueco = ae.idHueco AND h.idSubhueco = ae.idSubHueco '
                'JOIN TipoHueco th ON th.idTipoHueco = h.tipoHueco '
                'WHERE h.idCentro = %s',
                (ID_CENTRO,),
            )
            filas = cur.fetchall()
    finally:
        conn.close()

    agrupacion = {}
    etiquetado = {}
    for id_articulo, unidad1, etiqueta, descripcion in filas:
        clave = _normalize(id_articulo)
        descripcion_norm = (descripcion or '').strip().upper()
        unidad1 = float(unidad1 or 0)

        grupo = agrupacion.setdefault(clave, {'Picking': 0.0, 'Almacenamiento': 0.0})
        if 'PICKING' in descripcion_norm:
            grupo['Picking'] += unidad1
        elif 'ALMACEN' in descripcion_norm:
            grupo['Almacenamiento'] += unidad1

        if etiqueta:
            etiquetas = etiquetado.setdefault(clave, {'Picking': set(), 'Almacenamiento': set()})
            if 'PICKING' in descripcion_norm:
                etiquetas['Picking'].add(etiqueta.strip())
            elif 'ALMACEN' in descripcion_norm:
                etiquetas['Almacenamiento'].add(etiqueta.strip())

    etiquetado_final = {
        clave: {
            'Etiquetas_Picking': ', '.join(sorted(v['Picking'])) or None,
            'Etiquetas_Almacenamiento': ', '.join(sorted(v['Almacenamiento'])) or None,
        }
        for clave, v in etiquetado.items()
    }
    return agrupacion, etiquetado_final


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


def get_stock_tabla(supplier_categories=None, **params):
    """Combina todas las fuentes por artículo y calcula las columnas
    derivadas (stock+reserva, ratios, punto de pedido, tamaño...). Réplica
    de la consulta final del Power Query (paso "Tipos finales corregidos").
    """
    categorias = {
        _normalize(row.get('codpro')): {
            'categoria': int(row.get('categoria') or 0),
            'organizacion': row.get('organizacion') or '',
        }
        for row in (supplier_categories or [])
    }

    stock = _query_stock_raw()
    anio_actual = datetime.date.today().year
    ventas_actual = _query_mejores_ventas(anio_actual)
    ventas_anterior = _query_mejores_ventas(anio_actual - 1)
    agrupacion, etiquetado = _query_agrupacion_y_etiquetado()

    rows = []
    for codart, base in stock.items():
        cat_info = categorias.get(_normalize(base['CODPRO']), {})
        categoria = cat_info.get('categoria', 0)
        organizacion = cat_info.get('organizacion', '')
        mult = MULTIPLICADORES.get(categoria, MULTIPLICADOR_DEFECTO)

        clave_ventas = base['Cod. Articulo'] or codart
        v_actual = ventas_actual.get(clave_ventas, {})
        v_anterior = ventas_anterior.get(clave_ventas, {})

        media_ventas_anio_anterior = v_anterior.get('ventas', 0)
        media_base_stock = max(base['UndPtos Ultimo 30 dias'], media_ventas_anio_anterior)
        origen_media_base_stock = (
            'Últimos 30 días' if base['UndPtos Ultimo 30 dias'] >= media_ventas_anio_anterior else 'Año anterior'
        )

        stock_min = round(media_base_stock * mult['min'])
        stock_max = round(media_base_stock * mult['max'])
        punto_pedido = round(media_base_stock * mult['punto'])

        stock_reserva_a = base['Stock Total'] + base['Reservas']
        stock_reserva_b = base['Stock Total'] + base['Reserva B']
        stock_reserva_a_b = stock_reserva_a + base['Reserva B']

        ratio_stock_min = round(stock_reserva_b / stock_min, 2) if stock_min else 0
        diferencial_cantidad_pedido = 0
        if stock_reserva_a_b < punto_pedido:
            diferencial_cantidad_pedido = (
                (stock_max - stock_reserva_a_b) if categoria == 2 else (punto_pedido - stock_reserva_a_b)
            )

        dias_periodo = mult['min'] * 30
        stock_min_semanal = round((stock_min / dias_periodo if dias_periodo else 0) * 7)

        grupo_agr = agrupacion.get(codart, {'Picking': 0.0, 'Almacenamiento': 0.0})
        total_stock_ita = grupo_agr['Picking'] + grupo_agr['Almacenamiento']
        stock_inn_reserva_a = total_stock_ita + base['Reservas']
        stock_inn_reserva_b = total_stock_ita + base['Reserva B']
        stock_inn_reserva_a_b = stock_inn_reserva_a + base['Reserva B']
        ratio_stock_min_inn = round(stock_inn_reserva_b / stock_min, 2) if stock_min else 0
        diferencial_cantidad_pedido_inn = 0
        if stock_inn_reserva_a_b < punto_pedido:
            diferencial_cantidad_pedido_inn = (
                (stock_max - stock_inn_reserva_a_b) if categoria == 2 else (punto_pedido - stock_inn_reserva_a_b)
            )

        etiquetas = etiquetado.get(codart, {})

        rows.append({
            'CODPRO': base['CODPRO'],
            'CODART': base['CODART'],
            'CODDESCART': f'{base["CODART"]} - {base["Descripcion"]}',
            'Descripcion': base['Descripcion'],
            'Familia': base['Familia'],
            'Categoria_Organizacion': organizacion,
            'Categoria_Proveedor': categoria,
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
            'StockMin': stock_min,
            'StockMax': stock_max,
            'PuntoPedido': punto_pedido,
            'Stock_mas_Reserva_A': stock_reserva_a,
            'Stock_mas_Reserva_B': stock_reserva_b,
            'Stock_mas_Reserva_A_mas_B': stock_reserva_a_b,
            'Ratio_Stock_Min': ratio_stock_min,
            'Diferencial_Cantidad_Pedido_A3': diferencial_cantidad_pedido,
            'Stock_Total_dividido_StockMin': round(base['Stock Total'] / stock_min, 2) if stock_min else 0,
            'StockMin_Semanal': stock_min_semanal,
            'Picking': grupo_agr['Picking'],
            'Almacenamiento': grupo_agr['Almacenamiento'],
            'Stock_Total_Innertia': total_stock_ita,
            'Dif_A3_menos_Inn': base['Stock Total'] - total_stock_ita,
            'Stock_Inn_mas_Reserva_A': stock_inn_reserva_a,
            'Stock_Inn_mas_Reserva_B': stock_inn_reserva_b,
            'Stock_Inn_mas_Reserva_A_mas_B': stock_inn_reserva_a_b,
            'Ratio_Stock_Min_Innertia': ratio_stock_min_inn,
            'Diferencial_Cantidad_Pedido_Innertia': diferencial_cantidad_pedido_inn,
            'Stock_Innertia_dividido_StockMin': round(total_stock_ita / stock_min, 2) if stock_min else 0,
            'SIZE': _calcular_size(codart, base['Descripcion'], base['Familia'], stock_min_semanal),
            'Etiquetas_Picking': etiquetas.get('Etiquetas_Picking'),
            'Etiquetas_Almacenamiento': etiquetas.get('Etiquetas_Almacenamiento'),
        })

    rows.sort(key=lambda r: r['CODART'] or '')
    return rows
