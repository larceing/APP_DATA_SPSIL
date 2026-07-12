import secrets

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import ActiveSession


@receiver(user_logged_in)
def set_active_session(sender, request, user, **kwargs):
    """Admin/Superadmin (is_staff) quedan exentos: pueden necesitar varias
    sesiones a la vez para soporte o pruebas. Un Usuario normal, no —
    este login pasa a ser el único válido; gateway/middleware.py corta
    cualquier sesión anterior suya en su siguiente petición."""
    if user.is_staff:
        return
    token = secrets.token_hex(16)
    ActiveSession.objects.update_or_create(user=user, defaults={'token': token})
    request.session['single_session_token'] = token
