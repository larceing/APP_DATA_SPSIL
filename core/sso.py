"""Inicio de sesión único con Keycloak (AUTH_MODO=sso).

Authorization Code Flow sin librerías extra (solo `requests`, que ya está):
/login/ manda a la pantalla de Keycloak, Keycloak vuelve a /oidc/callback/
con un code, aquí se cambia por un token (petición directa del servidor al
issuer, así que no hace falta validar la firma) y se lee /userinfo.

Keycloak manda sobre los usuarios: en cada entrada se sincroniza
- `is_staff`/`is_superuser` con el grupo "IT" (Admin/Superadmin de esta app);
- las páginas sueltas (`UserProfile.extra_pages`) con los grupos
  "Stock", "Stock Tabla" y "Stock Config" (todas las de configuración).
Con este modo la administración de usuarios desaparece de /admin/ y del menú;
el departamento que ya tuviera alguien se conserva, pero no se edita aquí.
Es el mismo realm que el Gestor de Tareas: entrar en una app vale para la otra.
"""
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

GRUPO_ADMIN = 'IT'
# grupo de Keycloak -> slugs de Page (gateway) que concede
GRUPOS_PAGINAS = {
    'Stock': ['stock'],
    'Stock Tabla': ['stock-tabla'],
    'Stock Config': ['config-exclusion', 'config-proveedores', 'config-hueco-tipos',
                     'config-ubicaciones', 'config-stock-tabla'],
}


def _redirect_uri(request):
    base = settings.APP_URL_PUBLICA.rstrip('/')
    return base + '/oidc/callback/' if base else request.build_absolute_uri(reverse('sso_callback'))


def sso_login(request):
    next_url = request.GET.get('next') or reverse('gateway:home')
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('gateway:home')
    state = secrets.token_urlsafe(24)
    request.session['sso_state'] = state
    request.session['sso_next'] = next_url
    return HttpResponseRedirect(f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/auth?' + urlencode({
        'client_id': settings.KEYCLOAK_CLIENT_ID, 'response_type': 'code', 'scope': 'openid',
        'redirect_uri': _redirect_uri(request), 'state': state,
    }))


def _datos_usuario(request, code):
    try:
        token = requests.post(
            f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/token',
            data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': _redirect_uri(request),
                  'client_id': settings.KEYCLOAK_CLIENT_ID, 'client_secret': settings.KEYCLOAK_CLIENT_SECRET},
            timeout=10,
        )
        if token.status_code != 200:
            return None
        info = requests.get(
            f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo',
            headers={'Authorization': f'Bearer {token.json()["access_token"]}'}, timeout=10,
        )
        if info.status_code != 200:
            return None
        return info.json()
    except (requests.RequestException, ValueError, KeyError):
        return None


def sincronizar_usuario(datos):
    """Crea o actualiza el usuario de Django a partir del userinfo de Keycloak."""
    from gateway.models import Page, UserProfile

    username = datos.get('preferred_username')
    if not username:
        return None
    grupos = set(datos.get('groups') or [])
    es_admin = GRUPO_ADMIN in grupos
    user, _ = get_user_model().objects.get_or_create(username=username)
    user.first_name = (datos.get('given_name') or '')[:150]
    user.last_name = (datos.get('family_name') or '')[:150]
    user.email = datos.get('email') or ''
    user.is_active = True
    user.is_staff = es_admin
    user.is_superuser = es_admin
    user.set_unusable_password()
    user.save()
    slugs = {slug for grupo, lista in GRUPOS_PAGINAS.items() if grupo in grupos for slug in lista}
    perfil, _ = UserProfile.objects.get_or_create(user=user)
    perfil.extra_pages.set(Page.objects.filter(slug__in=slugs))
    return user


def sso_callback(request):
    esperado = request.session.pop('sso_state', None)
    next_url = request.session.pop('sso_next', None) or reverse('gateway:home')
    state = request.GET.get('state', '')
    if request.GET.get('error') or not esperado or not secrets.compare_digest(state, esperado):
        return HttpResponseBadRequest('No se pudo completar el inicio de sesión. Vuelve a intentarlo.')
    datos = _datos_usuario(request, request.GET.get('code', ''))
    user = sincronizar_usuario(datos) if datos else None
    if user is None:
        return HttpResponseBadRequest('No se pudo completar el inicio de sesión. Vuelve a intentarlo.')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return HttpResponseRedirect(next_url)


def sso_logout(request):
    logout(request)
    salida = settings.SSO_URL_SALIDA or (settings.APP_URL_PUBLICA.rstrip('/') + '/')
    return HttpResponseRedirect(f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/logout?' + urlencode({
        'client_id': settings.KEYCLOAK_CLIENT_ID, 'post_logout_redirect_uri': salida,
    }))
