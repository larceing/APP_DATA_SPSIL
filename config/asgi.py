"""
ASGI config for config project.

Exposes the ASGI callable as a module-level variable named ``application``.
Served by daphne. No websocket consumers yet; channels is wired up so
real-time features (e.g. live report refresh) can be added later without
changing the entrypoint.
"""

import os

from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
})
