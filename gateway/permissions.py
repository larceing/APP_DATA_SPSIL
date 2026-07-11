from functools import wraps

from django.contrib.auth.decorators import login_required
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
    (por departamento o suelto), no solo estar logueado."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            accessible = get_accessible_pages(request.user)
            if not any(page.slug == slug for page in accessible):
                raise PermissionDenied('No tienes acceso a esta página.')
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
