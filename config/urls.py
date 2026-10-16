from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core import sso
from core import views as core_views

if settings.AUTH_MODO == 'sso':
    # Keycloak: también el login de /admin/ pasa por la pantalla de Keycloak
    acceso = [
        path('admin/login/', RedirectView.as_view(pattern_name='login', query_string=True)),
        path('login/', sso.sso_login, name='login'),
        path('logout/', sso.sso_logout, name='logout'),
        path('oidc/callback/', sso.sso_callback, name='sso_callback'),
    ]
else:
    acceso = [
        path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
        path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    ]

urlpatterns = acceso + [
    path('admin/', admin.site.urls),
    path('set-language/', core_views.set_language, name='set_language'),
    path('gateway/', include('gateway.urls')),
    path('', RedirectView.as_view(pattern_name='gateway:home', permanent=False)),
]
