from django.db import models


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
