from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('switch-environment/', views.switch_environment, name='switch_environment'),
]
