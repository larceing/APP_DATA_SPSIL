from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('set-language/', core_views.set_language, name='set_language'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('gateway/', include('gateway.urls')),
    path('', RedirectView.as_view(pattern_name='gateway:stock', permanent=False)),
]
