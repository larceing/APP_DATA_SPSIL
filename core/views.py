from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST

from .middleware import LANGUAGE_COOKIE_NAME
from .templatetags.uistrings import SUPPORTED_LANGUAGES


@require_POST
def set_language(request):
    language = request.POST.get('language')
    next_url = request.POST.get('next') or '/'
    response = HttpResponseRedirect(next_url)
    if language in SUPPORTED_LANGUAGES:
        response.set_cookie(LANGUAGE_COOKIE_NAME, language, max_age=365 * 24 * 60 * 60)
    return response
