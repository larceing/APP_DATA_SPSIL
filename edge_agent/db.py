import os
import sqlite3

DB_PATH = os.environ.get('MOCK_DB_PATH', os.path.join(os.path.dirname(__file__), 'mock.db'))


def get_stock_actual(**params):
    """MOCK: hoy lee la tabla 'stock' de una BD SQLite de prueba.

    Este es el punto de aislamiento a sustituir por la consulta real a la
    BD de negocio (ERP/SQL Server/lo que sea) cuando equipo X tenga acceso
    a ella. La firma (devuelve list[dict] con sku/descripcion/cantidad/
    ubicacion) es lo que espera gateway/templates/gateway/stock.html.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT sku, descripcion, cantidad, ubicacion FROM stock ORDER BY sku'
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
