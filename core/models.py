from django.conf import settings
from django.db import models


class EnvironmentConfig(models.Model):
    """Singleton: guarda qué entorno de datos (test/prod/demo) está activo."""

    class Environment(models.TextChoices):
        TEST = 'test', 'Prueba'
        PROD = 'prod', 'Productivo'
        DEMO = 'demo', 'Demo'

    current = models.CharField(
        max_length=10, choices=Environment.choices, default=Environment.TEST
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = 'Configuración de entorno'
        verbose_name_plural = 'Configuración de entorno'

    def __str__(self):
        return self.get_current_display()

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UIString(models.Model):
    """Texto de interfaz traducido a es/it/en, referenciado por clave desde plantillas."""

    key = models.CharField(max_length=200, unique=True)
    es = models.TextField(blank=True)
    it = models.TextField(blank=True)
    en = models.TextField(blank=True)
    notes = models.CharField(
        max_length=255, blank=True, help_text='Contexto para quien traduzca'
    )

    class Meta:
        ordering = ['key']
        verbose_name = 'Texto de interfaz'
        verbose_name_plural = 'Textos de interfaz (UIStrings)'

    def __str__(self):
        return self.key

    def get(self, lang):
        return getattr(self, lang, '') or self.key
