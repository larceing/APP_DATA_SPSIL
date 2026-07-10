from django import template
from django.utils.translation import get_language

from core.models import UIString

register = template.Library()

SUPPORTED_LANGUAGES = ('es', 'zh', 'en')


@register.simple_tag
def ui(key, lang=None):
    """{% ui "reports.title" %} -> texto traducido para el idioma activo, o la propia key si no existe."""
    lang = (lang or get_language() or 'es')[:2]
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'es'
    try:
        return UIString.objects.get(key=key).get(lang)
    except UIString.DoesNotExist:
        return key
