import sqlite3

from db import DB_PATH

SAMPLE_ROWS = [
    ('SKU-001', 'Tornillo M6x20', 1200, 'A-01-01'),
    ('SKU-002', 'Tuerca M6', 3400, 'A-01-02'),
    ('SKU-003', 'Arandela M6', 5000, 'A-01-03'),
    ('SKU-010', 'Cable USB-C 1m', 150, 'B-02-01'),
    ('SKU-011', 'Cable HDMI 2m', 80, 'B-02-02'),
    ('SKU-020', 'Caja cartón mediana', 600, 'C-03-01'),
    ('SKU-021', 'Caja cartón grande', 320, 'C-03-02'),
    ('SKU-030', 'Guantes talla M', 250, 'D-01-01'),
    ('SKU-031', 'Guantes talla L', 210, 'D-01-02'),
    ('SKU-040', 'Palet de madera', 45, 'E-00-01'),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            sku TEXT PRIMARY KEY,
            descripcion TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            ubicacion TEXT NOT NULL
        )
    ''')
    conn.executemany(
        'INSERT OR IGNORE INTO stock (sku, descripcion, cantidad, ubicacion) VALUES (?, ?, ?, ?)',
        SAMPLE_ROWS,
    )
    conn.commit()
    conn.close()


if __name__ == '__main__':
    seed()
    print(f'BD mock de stock lista en {DB_PATH}')
