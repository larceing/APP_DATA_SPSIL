import os

import pymysql
import pytds

MARIADB_HOST = os.environ.get('MARIADB_HOST')
MARIADB_PORT = int(os.environ.get('MARIADB_PORT', '3306'))
MARIADB_DATABASE = os.environ.get('MARIADB_DATABASE')
MARIADB_USER = os.environ.get('MARIADB_USER')
MARIADB_PASSWORD = os.environ.get('MARIADB_PASSWORD')
ID_CENTRO = int(os.environ.get('ID_CENTRO', '0'))
ID_ALMACEN = int(os.environ.get('ID_ALMACEN', '0'))

MSSQL_HOST = os.environ.get('MSSQL_HOST')
MSSQL_DATABASE = os.environ.get('MSSQL_DATABASE')
MSSQL_USER = os.environ.get('MSSQL_USER')
MSSQL_PASSWORD = os.environ.get('MSSQL_PASSWORD')


def _normalize(value):
    return (value or '').strip().upper()


def _query_stock():
    """Stock total por artículo: MariaDB, vista StockDisponibleCentroAlmacen,
    filtrada por idCentro/idAlmacen, agrupada, negativos a 0. Replica la
    consulta 1 del Power BI original (Table.Group + negativos a cero)."""
    conn = pymysql.connect(
        host=MARIADB_HOST, port=MARIADB_PORT, user=MARIADB_USER,
        password=MARIADB_PASSWORD, database=MARIADB_DATABASE,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT idArticulo, GREATEST(SUM(stock), 0) AS Suma_Stock '
                'FROM StockDisponibleCentroAlmacen '
                'WHERE idCentro = %s AND idAlmacen = %s '
                'GROUP BY idArticulo',
                (ID_CENTRO, ID_ALMACEN),
            )
            return {_normalize(id_articulo): float(suma_stock) for id_articulo, suma_stock in cur.fetchall()}
    finally:
        conn.close()


def _query_familias():
    """Familia de cada artículo: SQL Server dbo.ARTICULO (CODART/CAR1),
    usada solo para poder aplicar las reglas de exclusión por familia."""
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


def get_stock_actual(exclusion_rules=None, **params):
    """Stock actual por artículo, excluyendo los códigos/familias marcados
    como regla de exclusión. Las reglas llegan ya calculadas desde servidor Y
    (tabla ExclusionRule, editada desde /gateway/config/) dentro del propio
    mensaje de la consulta — este agente no guarda nada en disco ni habla
    con Google Sheets, solo las usa en memoria para esta petición.
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

    stock = _query_stock()
    familias = _query_familias()

    rows = []
    for id_articulo, suma_stock in stock.items():
        familia = familias.get(id_articulo, '')
        if id_articulo in codigos_excluidos or familia in familias_excluidas:
            continue
        rows.append({'idArticulo': id_articulo, 'Suma_Stock': suma_stock})

    rows.sort(key=lambda row: row['idArticulo'])
    return rows
