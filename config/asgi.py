"""
ASGI config for config project.

Exposes the ASGI callable as a module-level variable named ``application``.
Sirve HTTP normal y el túnel WebSocket de gateway/consumers.py por el que
equipo X (el agente en edge_agent/) se conecta para servir datos en vivo.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Debe ejecutarse (django.setup()) antes de importar cualquier módulo que
# toque el registro de apps (routing -> consumers -> models), o revienta
# con AppRegistryNotReady.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from gateway.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
