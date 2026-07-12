from django.db import migrations

PAGES = [
    # (name, slug, url_name, group_label, order)
    ('Exclusiones', 'config-exclusion', 'gateway:config_exclusion', 'Configuración · Almacén', 1),
    ('Tipos de Hueco', 'config-hueco-tipos', 'gateway:config_hueco_tipos', 'Configuración · Almacén', 2),
    ('Ubicaciones', 'config-ubicaciones', 'gateway:config_ubicaciones', 'Configuración · Almacén', 3),
    ('Categoría Proveedores', 'config-proveedores', 'gateway:config_suppliers', 'Configuración · Compras', 1),
]


def seed(apps, schema_editor):
    """Hasta ahora, TODA la Configuración iba detrás de un único flag
    is_staff. Se convierte cada sección en una Page normal (mismo
    mecanismo que Stock/Stock Tabla: Department o UserProfile.extra_pages)
    para poder dar acceso a, por ejemplo, solo Exclusiones sin hacer
    Admin de todo a alguien. Admin/Superadmin siguen viendo todo, igual
    que con cualquier otra Page (bypass en get_accessible_pages)."""
    Page = apps.get_model('gateway', 'Page')
    for name, slug, url_name, group_label, order in PAGES:
        Page.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'url_name': url_name, 'group_label': group_label, 'order': order},
        )


def unseed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.filter(slug__in=[p[1] for p in PAGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0010_stock_total_solo_picking_almacenamiento'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
