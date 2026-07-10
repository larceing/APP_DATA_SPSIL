from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class GatewayNode(models.Model):
    """Un equipo remoto (equipo X) que se conecta por WebSocket para servir datos en vivo."""

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=100, unique=True)
    token_hash = models.CharField(max_length=128, blank=True, editable=False)
    active = models.BooleanField(default=True)
    last_connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def set_token(self, raw_token):
        self.token_hash = make_password(raw_token)

    def check_token(self, raw_token):
        return bool(self.token_hash) and check_password(raw_token, self.token_hash)
