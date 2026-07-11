from django.urls import path

from . import views

app_name = 'gateway'

urlpatterns = [
    path('home/', views.home_view, name='home'),
    path('stock/', views.stock_view, name='stock'),
    path('stock/actual/', views.stock_actual_api, name='stock_actual_api'),
    path('stock/export/', views.stock_export_view, name='stock_export'),
    path('stock-tabla/', views.stock_tabla_view, name='stock_tabla'),
    path('stock-tabla/actual/', views.stock_tabla_api, name='stock_tabla_api'),
    path('stock-tabla/export/', views.stock_tabla_export_view, name='stock_tabla_export'),
    path('config/', views.config_view, name='config'),
    path('config/add/', views.config_add_rule, name='config_add_rule'),
    path('config/<int:rule_id>/delete/', views.config_delete_rule, name='config_delete_rule'),
]
