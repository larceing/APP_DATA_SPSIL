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
