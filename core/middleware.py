from core.templatetags.uistrings import SUPPORTED_LANGUAGES

LANGUAGE_COOKIE_NAME = 'app_language'


class AppLanguageMiddleware:
    """Idioma de la interfaz (es/zh/en) para el sistema propio UIString.

    Deliberadamente independiente del framework de i18n/gettext de Django
    (LocaleMiddleware, set_language...): ese mecanismo exige un catálogo de
    traducción compilado por idioma, y aquí las traducciones viven en la
    tabla UIString, no en catálogos gettext.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.COOKIES.get(LANGUAGE_COOKIE_NAME)
        request.app_language = lang if lang in SUPPORTED_LANGUAGES else 'es'
        return self.get_response(request)
