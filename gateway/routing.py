from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/gateway/(?P<slug>[\w-]+)/$', consumers.GatewayNodeConsumer.as_asgi()),
]
