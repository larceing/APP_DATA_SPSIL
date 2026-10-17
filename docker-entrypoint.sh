#!/bin/sh
set -e

python manage.py migrate --noinput

# --root-path: la ruta pública (DJANGO_RUTA_BASE, p. ej. /stock) que el proxy
# quita al entrar; Django la usa para sus enlaces. Vacía = en la raíz.
# --ws-max-size: los informes grandes (facturas, ventas) mandan varios MB por
# el túnel del agente; el límite por defecto de uvicorn es 16 MB.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8010 --root-path "${DJANGO_RUTA_BASE:-}" --ws-max-size 104857600
