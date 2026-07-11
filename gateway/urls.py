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
    path('config/exclusion/', views.config_exclusion_view, name='config_exclusion'),
    path('config/add/', views.config_add_rule, name='config_add_rule'),
    path('config/<int:rule_id>/delete/', views.config_delete_rule, name='config_delete_rule'),
    path('config/proveedores/', views.config_suppliers_view, name='config_suppliers'),
    path('config/supplier-categories/save/', views.config_save_supplier_category, name='config_save_supplier_category'),
    path(
        'config/supplier-categories/<int:supplier_id>/delete/',
        views.config_delete_supplier_category,
        name='config_delete_supplier_category',
    ),
    path('config/tipos-hueco/', views.config_hueco_tipos_view, name='config_hueco_tipos'),
    path('config/tipos-hueco/<int:hueco_tipo_id>/save/', views.config_save_hueco_tipo, name='config_save_hueco_tipo'),
    path(
        'config/tipos-hueco/<int:hueco_tipo_id>/delete/',
        views.config_delete_hueco_tipo,
        name='config_delete_hueco_tipo',
    ),
]
