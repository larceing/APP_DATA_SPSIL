from django.conf import settings
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


class ExclusionRule(models.Model):
    """Artículo o familia a excluir del stock, editable desde la pantalla de
    configuración de negocio. Sustituye editar el Google Sheet a mano; la
    hoja solo se usa una vez para la carga inicial (ver management command
    import_exclusion_rules)."""

    class Tipo(models.TextChoices):
        ARTICULO = 'articulo', 'Artículo'
        FAMILIA = 'familia', 'Familia'

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', 'valor']
        constraints = [
            models.UniqueConstraint(fields=['tipo', 'valor'], name='unique_exclusion_tipo_valor'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.valor}'

    def save(self, *args, **kwargs):
        self.valor = self.valor.strip().upper()
        super().save(*args, **kwargs)


class Department(models.Model):
    """Departamento de negocio. Todavía no se usa para filtrar datos: es el
    hueco estructural para cuando haga falta segmentar por departamento."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Perfil ligado a un usuario de Django. El rol (usuario/admin/superadmin)
    ya lo dan is_staff/is_superuser; este perfil solo añade el departamento."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='users'
    )

    def __str__(self):
        return self.user.get_username()
