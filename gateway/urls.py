from django.urls import path

from . import views

app_name = 'gateway'

urlpatterns = [
    path('stock/', views.stock_view, name='stock'),
    path('stock/actual/', views.stock_actual_api, name='stock_actual_api'),
]
