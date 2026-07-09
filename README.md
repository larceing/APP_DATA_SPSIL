# APP_DATA_SPSIL — App de reporting (estilo Power BI)

Aplicación web de reporting construida con Django 4.2. Muestra informes
(`Report`) organizados en páginas (`ReportPage`), con permisos de acceso por
grupo de usuario. Los datos provienen de archivos CSV/Excel importados vía
`DataSource`, o de la base de datos real en el entorno productivo.

## Stack

- Python 3.12 (entorno de desarrollo; requiere >=3.10 por Django 4.2)
- Django 4.2, daphne, channels, whitenoise
- SQLite
- Sin frameworks JS externos — CSS propio con variables (`static/css/`)

## Apps

- `core` — configuración de entorno (test/prod/demo) y textos de interfaz multi-idioma (`UIString`)
- `reports` — `Report` y `ReportPage`
- `datasources` — `DataSource` y `ImportedRow` (datos importados desde CSV/Excel)

## Setup

```
setup.bat
venv\Scripts\python.exe manage.py createsuperuser
```

## Arrancar / parar / reiniciar (Windows)

```
scripts\start_server.vbs
scripts\stop_server.vbs
scripts\restart_server.vbs
```

Sirve con daphne en `http://localhost:8000`. El PID se guarda en `server.pid`
y el log en `logs\server.log`.

## Importar un DataSource

1. En `/admin/`, crea un `DataSource` (nombre, `target_table`, entorno, y su archivo CSV/Excel).
2. Ejecuta:

```
venv\Scripts\python.exe manage.py import_datasource <target_table> [--environment test|prod|demo] [--file ruta.csv] [--clear]
```

Las filas quedan en `ImportedRow` (JSON por fila), ligadas al `DataSource`.

## Cambiar de entorno

Desde `/admin/core/environmentconfig/` (solo staff/superusuarios), botones
para cambiar entre Prueba / Productivo / Demo.
