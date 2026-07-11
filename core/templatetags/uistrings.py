from django import template

from core.models import UIString

register = template.Library()

SUPPORTED_LANGUAGES = ('es', 'zh', 'en')


@register.simple_tag(takes_context=True)
def ui(context, key, lang=None):
    """{% ui "reports.title" %} -> texto traducido para el idioma activo, o la propia key si no existe."""
    if lang is None:
        request = context.get('request')
        lang = getattr(request, 'app_language', 'es')
    lang = (lang or 'es')[:2]
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'es'
    try:
        return UIString.objects.get(key=key).get(lang)
    except UIString.DoesNotExist:
        return key
