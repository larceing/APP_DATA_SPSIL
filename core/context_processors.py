from django.conf import settings

SHORT_LABELS = {
    'es': 'ES',
    'zh': '中文',
    'en': 'EN',
}


def languages(request):
    return {
        'LANGUAGES_DISPLAY': [
            (code, SHORT_LABELS.get(code, code.upper())) for code, _ in settings.LANGUAGES
        ],
        'CURRENT_LANGUAGE': getattr(request, 'app_language', 'es'),
    }


def plataforma(request):
    """Con login único (AUTH_MODO=sso) los usuarios se gestionan en Keycloak:
    se esconde su administración aquí. PORTAL_URL = la portada de apps."""
    return {
        'AUTH_SSO': settings.AUTH_MODO == 'sso',
        'PORTAL_URL': settings.SSO_URL_SALIDA,
    }
