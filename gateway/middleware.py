from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from .models import ActiveSession


class SingleSessionMiddleware:
    """Si un Usuario normal (no Admin/Superadmin, exentos) inicia sesión
    en otro sitio, gateway/signals.py ya dejó su token viejo sin validez;
    aquí se corta esa sesión vieja en su siguiente petición y se manda a
    login con un aviso (?session_kicked=1, ver templates/registration/login.html)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_staff:
            token = request.session.get('single_session_token')
            active = ActiveSession.objects.filter(user=user).first()
            if active and token != active.token:
                logout(request)
                login_url = redirect_to_login(request.get_full_path()).url
                separator = '&' if '?' in login_url else '?'
                return redirect(f'{login_url}{separator}session_kicked=1')
        return self.get_response(request)
