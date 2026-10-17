"""Inicio de sesión único con Keycloak (AUTH_MODO=sso).

Authorization Code Flow sin librerías extra (solo `requests`, que ya está):
/login/ manda a la pantalla de Keycloak, Keycloak vuelve a /oidc/callback/
con un code, aquí se cambia por un token (petición directa del servidor al
issuer, así que no hace falta validar la firma) y se lee /userinfo.

Keycloak manda sobre los usuarios, con un espacio por aplicación (grupos con
"Full group path" activado en el mapper "groups" del cliente):
- `/Stock`: entrar en esta app (ve la página Stock). Sin ningún grupo de la
  app (ni IT) no se entra, aunque se sea admin de otra app.
- `/Stock/Admin`: administrador solo de esta app (ve y configura todo aquí).
- `/Stock/<Departamento>`: páginas de ese departamento (ver DEPARTAMENTOS:
  Almacén, Compras, Cobros, Pedidos, Ventas, Pendientes, Logística, Config).
- `IT`: administrador global, entra y administra todas las apps.
Los grupos sueltos antiguos ("Stock Tabla", "Stock Config", "Informes...")
siguen valiendo mientras se migra a la estructura nueva.
Con este modo la administración de usuarios desaparece de /admin/ y del menú;
el departamento que ya tuviera alguien se conserva, pero no se edita aquí.
Es el mismo realm que el Gestor de Tareas: entrar en una app vale para la otra.
"""
import secrets
import unicodedata
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

GRUPO_ADMIN = 'IT'
APP = 'Stock'
CONFIG = ['config-exclusion', 'config-proveedores', 'config-hueco-tipos',
          'config-ubicaciones', 'config-stock-tabla', 'config-origenes']
# grupos sueltos antiguos -> slugs de Page (gateway) que conceden
GRUPOS_PAGINAS = {
    'Stock': ['stock'],
    'Stock Tabla': ['stock-tabla'],
    'Stock Config': CONFIG,
}


def _clave(texto):
    """'Almacén' y 'almacen' cuentan igual."""
    sin_tildes = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()
    return sin_tildes.strip().casefold()


def departamentos():
    """/Stock/<Departamento> -> slugs de Page. Cada sección de informes es un
    departamento; Almacén y Compras incluyen además Stock y Stock Tabla."""
    from gateway import informes

    deps = {seccion: [informes.page_slug(p) for p in informes.PAGINAS if p['grupo'] == seccion]
            for seccion in informes.SECCIONES}
    deps['Almacén'] = ['stock', 'stock-tabla'] + deps.get('Almacén', [])
    deps['Compras'] = ['stock-tabla'] + deps.get('Compras', [])
    deps['Config'] = CONFIG
    return {_clave(nombre): slugs for nombre, slugs in deps.items()}


def leer_grupos(grupos):
    """(acceso, es_admin, slugs) a partir de los grupos de Keycloak, con o
    sin ruta completa ('/Stock/Compras' o 'Stock/Compras')."""
    nombres = {g.strip('/') for g in grupos or [] if g}
    es_admin = GRUPO_ADMIN in nombres or f'{APP}/Admin' in nombres
    slugs, acceso = set(), es_admin
    deps = departamentos()
    for nombre in nombres:
        partes = nombre.split('/')
        if partes[0] == APP:
            acceso = True
            if len(partes) == 1:
                slugs.add('stock')
            else:
                slugs.update(deps.get(_clave(partes[1]), []))
        elif nombre in grupos_paginas():
            acceso = True
            slugs.update(grupos_paginas()[nombre])
    return acceso, es_admin, slugs


def grupos_paginas():
    """GRUPOS_PAGINAS más los grupos de informes, sacados del catálogo
    (gateway/informes.py) para que un informe nuevo no haya que darlo de
    alta también aquí."""
    from gateway import informes

    grupos = dict(GRUPOS_PAGINAS)
    grupos[informes.GRUPO_TODOS] = [informes.page_slug(p) for p in informes.PAGINAS]
    for seccion in informes.SECCIONES:
        grupos[informes.grupo_keycloak(seccion)] = [
            informes.page_slug(p) for p in informes.PAGINAS if p['grupo'] == seccion
        ]
    return grupos


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
    """Crea o actualiza el usuario de Django a partir del userinfo de Keycloak.
    Devuelve None si no tiene ningún grupo de esta app (ni IT)."""
    from gateway.models import Page, UserProfile

    username = datos.get('preferred_username')
    if not username:
        return None
    acceso, es_admin, slugs = leer_grupos(datos.get('groups'))
    if not acceso:
        return None
    user, _ = get_user_model().objects.get_or_create(username=username)
    user.first_name = (datos.get('given_name') or '')[:150]
    user.last_name = (datos.get('family_name') or '')[:150]
    user.email = datos.get('email') or ''
    user.is_active = True
    user.is_staff = es_admin
    user.is_superuser = es_admin
    user.set_unusable_password()
    user.save()
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
    if not datos:
        return HttpResponseBadRequest('No se pudo completar el inicio de sesión. Vuelve a intentarlo.')
    user = sincronizar_usuario(datos)
    if user is None:
        return HttpResponseForbidden('No tienes acceso a esta aplicación. Pide a un administrador que te añada al grupo Stock.')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return HttpResponseRedirect(next_url)


def sso_logout(request):
    logout(request)
    salida = settings.SSO_URL_SALIDA or (settings.APP_URL_PUBLICA.rstrip('/') + '/')
    return HttpResponseRedirect(f'{settings.KEYCLOAK_ISSUER}/protocol/openid-connect/logout?' + urlencode({
        'client_id': settings.KEYCLOAK_CLIENT_ID, 'post_logout_redirect_uri': salida,
    }))
