import asyncio
from functools import wraps

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Page, UserProfile


def get_accessible_pages(user):
    """Páginas/informes que este usuario puede ver: todas si es staff/superuser
    (Admin/Superadmin ya tienen acceso a todo lo de Usuario), si no, las de su
    departamento más las concedidas sueltas en su perfil."""
    if user.is_staff or user.is_superuser:
        return list(Page.objects.all())
    try:
        return user.profile.accessible_pages()
    except UserProfile.DoesNotExist:
        return []


def page_required(slug):
    """Exige que el usuario tenga acceso concedido a la página `slug`
    (por departamento o suelto), no solo estar logueado.

    Soporta tanto vistas síncronas (páginas normales, render de plantilla)
    como asíncronas (las que piden datos por el túnel — necesitan ser
    async para no bloquear el hilo compartido de Django mientras esperan
    la respuesta de equipo X; ver gateway/views.py::_ask_gateway)."""

    def decorator(view_func):
        if asyncio.iscoroutinefunction(view_func):
            @wraps(view_func)
            async def wrapped(request, *args, **kwargs):
                # request.user es un SimpleLazyObject: la resolución (que
                # dispara una consulta síncrona a la sesión) ocurre en el
                # primer acceso a un atributo, no al obtener la
                # referencia — por eso el propio "is_authenticated" tiene
                # que forzarse aquí dentro, en contexto síncrono. Django
                # 4.2 no tiene request.auser() (eso es de Django 5.0).
                def _resolve_user():
                    _ = request.user.is_authenticated
                    return request.user

                user = await sync_to_async(_resolve_user)()
                if not user.is_authenticated:
                    return redirect_to_login(request.get_full_path())
                accessible = await sync_to_async(get_accessible_pages)(user)
                if not any(page.slug == slug for page in accessible):
                    raise PermissionDenied('No tienes acceso a esta página.')
                return await view_func(request, *args, **kwargs)

            return wrapped

        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            accessible = get_accessible_pages(request.user)
            if not any(page.slug == slug for page in accessible):
                raise PermissionDenied('No tienes acceso a esta página.')
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
