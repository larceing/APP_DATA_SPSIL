#!/bin/sh
set -e

python manage.py migrate --noinput

# --root-path: la ruta pública (DJANGO_RUTA_BASE, p. ej. /stock) que el proxy
# quita al entrar; Django la usa para sus enlaces. Vacía = en la raíz.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8010 --root-path "${DJANGO_RUTA_BASE:-}"
