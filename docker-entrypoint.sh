#!/bin/sh
set -e

python manage.py migrate --noinput

exec daphne -b 0.0.0.0 -p 8010 config.asgi:application
