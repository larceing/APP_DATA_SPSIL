import os

import pymysql
import pytds

MARIADB_HOST = os.environ.get('MARIADB_HOST')
MARIADB_PORT = int(os.environ.get('MARIADB_PORT', '3306'))
MARIADB_DATABASE = os.environ.get('MARIADB_DATABASE')
MARIADB_USER = os.environ.get('MARIADB_USER')
MARIADB_PASSWORD = os.environ.get('MARIADB_PASSWORD')

MSSQL_HOST = os.environ.get('MSSQL_HOST')
MSSQL_DATABASE = os.environ.get('MSSQL_DATABASE')
MSSQL_USER = os.environ.get('MSSQL_USER')
MSSQL_PASSWORD = os.environ.get('MSSQL_PASSWORD')


def _normalize(value):
    return (value or '').strip().upper()


def _mariadb_connect():
    return pymysql.connect(
        host=MARIADB_HOST, port=MARIADB_PORT, user=MARIADB_USER,
        password=MARIADB_PASSWORD, database=MARIADB_DATABASE,
    )


def _query_stock(ubicaciones):
    """Stock total por artículo: MariaDB, vista StockDisponibleCentroAlmacen,
    agrupada, negativos a 0. Esta vista no distingue por zona (igual que
    en el Power Query original), así que se filtra por los pares
    (idCentro, idAlmacen) distintos de `ubicaciones` — varias filas con
    el mismo par y distinta zona no deben filtrar de más."""
    if not ubicaciones:
        return {}
    pares = sorted({(u['id_centro'], u['id_almacen']) for u in ubicaciones})
    condiciones = ' OR '.join('(idCentro = %s AND idAlmacen = %s)' for _ in pares)
    parametros = [valor for par in pares for valor in par]

    conn = _mariadb_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                # Se agrupa por UPPER(TRIM(idArticulo)), no por idArticulo
                # tal cual: si la misma referencia tiene variantes con
                # espacios/mayúsculas distintas en la BD real, agrupar en
                # crudo las deja como filas separadas — y como luego se
                # normalizaba solo en Python con un diccionario armado de
                # golpe, se perdía todo menos la última fila en vez de
                # sumarlas. Agrupando ya por la clave normalizada, MariaDB
                # hace la suma completa y sigue siendo una sola consulta
                # eficiente (no hace falta traer cada fila suelta).
                f'SELECT UPPER(TRIM(idArticulo)) AS clave, GREATEST(SUM(stock), 0) AS Suma_Stock '
                f'FROM StockDisponibleCentroAlmacen WHERE {condiciones} '
                f'GROUP BY UPPER(TRIM(idArticulo))',
                parametros,
            )
            return {clave: float(suma_stock or 0) for clave, suma_stock in cur.fetchall() if clave}
    finally:
        conn.close()


def _query_familias():
    """Familia de cada artículo: SQL Server dbo.ARTICULO (CODART/CAR1),
    usada para las reglas de exclusión por familia y para mostrarla en
    Stock (columna FAMILIA)."""
    conn = pytds.connect(
        server=MSSQL_HOST, database=MSSQL_DATABASE,
        user=MSSQL_USER, password=MSSQL_PASSWORD,
    )
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT CODART, CAR1 FROM dbo.ARTICULO')
            return {_normalize(codart): _normalize(car1) for codart, car1 in cur.fetchall()}
    finally:
        conn.close()


def _query_todos_tipos_hueco():
    """Lista completa de TipoHueco (~10 filas fijas), sin filtrar por
    ubicación ni por si tienen stock ahora mismo — para que la
    configuración de /gateway/config/tipos-hueco/ muestre todos los
    tipos posibles desde el principio, no solo los que casualmente
    tengan unidades en un hueco en este momento."""
    conn = _mariadb_connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT idTipoHueco, descripcion FROM TipoHueco')
            return [
                {'id_tipo_hueco': id_tipo, 'descripcion': (descripcion or '').strip()}
                for id_tipo, descripcion in cur.fetchall()
            ]
    finally:
        conn.close()


def query_hueco_breakdown(ubicaciones, tipos_excluidos=None):
    """Cruce ArticuloHuecoStock + Hueco + TipoHueco, compartido por Stock
    y Stock Tabla: desglose de stock por artículo en Picking (tipoHueco=1)
    y Almacenamiento (tipoHueco=2) — así los calcula el Power BI original
    (FxSumaPorTipo con esos dos ids fijos, no una categorización nuestra).

    `ubicaciones`: [{'id_centro':6,'id_almacen':1,'id_zona':1}, ...] — se
    filtra por cualquiera de las combinaciones dadas (antes fijo por
    variable de entorno + idZona=1 hardcodeado).
    `tipos_excluidos`: ids de TipoHueco a excluir del todo (p.ej. 9 =
    Salida, excluido por defecto) — configurable en
    /gateway/config/tipos-hueco/, antes hardcodeado en el propio SQL.
    `idCalle <> 0` se mantiene fijo: 0 significa "sin calle asignada", es
    un filtro de calidad de datos, no una decisión de negocio.

    Devuelve (breakdown, tipos_vistos):
    - breakdown: {idArticulo: {'Picking':, 'Almacenamiento':,
      'Etiquetas_Picking':, 'Etiquetas_Almacenamiento':}}
    - tipos_vistos: [{'id_tipo_hueco':, 'descripcion':}, ...] — la tabla
      TipoHueco completa (~10 filas fijas), no solo los tipos que tengan
      stock ahora mismo, para que servidor Y registre desde el principio
      todos los posibles en /gateway/config/tipos-hueco/ (ver
      gateway/views.py::_registrar_tipos_hueco_nuevos).
    """
    tipos_vistos_lista = _query_todos_tipos_hueco()
    if not ubicaciones:
        return {}, tipos_vistos_lista

    condiciones = ' OR '.join(
        '(ae.idCentro = %s AND ae.idAlmacen = %s AND ae.idZona = %s)' for _ in ubicaciones
    )
    parametros = []
    for u in ubicaciones:
        parametros += [u['id_centro'], u['id_almacen'], u['id_zona']]

    sql = (
        'SELECT ae.idArticulo, ae.unidad1, h.tipoHueco, h.etiqueta '
        'FROM ArticuloHuecoStock ae '
        'JOIN Hueco h '
        '  ON h.idCentro = ae.idCentro AND h.idAlmacen = ae.idAlmacen AND h.idZona = ae.idZona '
        '  AND h.idCalle = ae.idCalle AND h.idSeccion = ae.idSeccion AND h.idNivel = ae.idNivel '
        '  AND h.idHueco = ae.idHueco AND h.idSubhueco = ae.idSubHueco '
        f'WHERE ({condiciones}) AND h.idCalle <> 0'
    )
    tipos_excluidos = list(tipos_excluidos or [])
    if tipos_excluidos:
        placeholders = ', '.join(['%s'] * len(tipos_excluidos))
        sql += f' AND h.tipoHueco NOT IN ({placeholders})'
        parametros += tipos_excluidos

    conn = _mariadb_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, parametros)
            filas = cur.fetchall()
    finally:
        conn.close()

    breakdown = {}
    for id_articulo, unidad1, id_tipo_hueco, etiqueta in filas:
        clave = _normalize(id_articulo)
        unidad1 = float(unidad1 or 0)

        fila = breakdown.setdefault(clave, {
            'Picking': 0.0, 'Almacenamiento': 0.0,
            'Etiquetas_Picking': set(), 'Etiquetas_Almacenamiento': set(),
        })
        if id_tipo_hueco == 1:
            fila['Picking'] += unidad1
            if etiqueta:
                fila['Etiquetas_Picking'].add(etiqueta.strip())
        elif id_tipo_hueco == 2:
            fila['Almacenamiento'] += unidad1
            if etiqueta:
                fila['Etiquetas_Almacenamiento'].add(etiqueta.strip())

    for fila in breakdown.values():
        fila['Etiquetas_Picking'] = ', '.join(sorted(fila['Etiquetas_Picking'])) or None
        fila['Etiquetas_Almacenamiento'] = ', '.join(sorted(fila['Etiquetas_Almacenamiento'])) or None

    return breakdown, tipos_vistos_lista


def get_stock_actual(exclusion_rules=None, ubicaciones=None, tipos_excluidos=None, **params):
    """Stock actual por artículo, igual que el M de "Almacen": el conjunto
    que manda es el cruce de huecos (query_hueco_breakdown — INNER JOIN
    ArticuloEstipulado x Hueco, JoinKind.Inner en el M), y Stock_Disponible
    (StockDisponibleCentroAlmacen) se añade por encima como LEFT JOIN
    (MergeStock, JoinKind.LeftOuter en el M) — no al revés. Un artículo con
    saldo en StockDisponibleCentroAlmacen pero sin ningún hueco físico
    asignado en las ubicaciones dadas no debe aparecer (así lo descarta el
    INNER JOIN del M); de ahí salían códigos como "0"/"1"/"156" con stock
    negativo redondeado a 0 que nunca están en el informe real.

    `ubicaciones`/`exclusion_rules`/`tipos_excluidos` llegan ya calculados
    desde servidor Y en cada petición — este agente no guarda nada en
    disco ni habla con Google Sheets, solo los usa en memoria para esta
    petición.
    """
    codigos_excluidos = set()
    familias_excluidas = set()
    for rule in exclusion_rules or []:
        valor = _normalize(rule.get('valor'))
        if not valor:
            continue
        if rule.get('tipo') == 'articulo':
            codigos_excluidos.add(valor)
        elif rule.get('tipo') == 'familia':
            familias_excluidas.add(valor)

    ubicaciones = ubicaciones or []
    stock = _query_stock(ubicaciones)
    familias = _query_familias()
    huecos, tipos_vistos = query_hueco_breakdown(ubicaciones, tipos_excluidos)

    rows = []
    for id_articulo, hueco in huecos.items():
        familia = familias.get(id_articulo, '')
        if id_articulo in codigos_excluidos or familia in familias_excluidas:
            continue
        rows.append({
            'idArticulo': id_articulo,
            'FAMILIA': familia,
            'Stock_Disponible': stock.get(id_articulo, 0.0),
            'Stock_Picking': hueco.get('Picking', 0.0),
            'Stock_Almacenamiento': hueco.get('Almacenamiento', 0.0),
            'Etiquetas_Picking': hueco.get('Etiquetas_Picking'),
            'Etiquetas_Almacenamiento': hueco.get('Etiquetas_Almacenamiento'),
        })

    rows.sort(key=lambda row: row['idArticulo'])
    return {'rows': rows, 'tipos_hueco_descubiertos': tipos_vistos}
