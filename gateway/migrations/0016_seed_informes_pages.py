from django.db import migrations

from gateway import informes


def seed(apps, schema_editor):
    """Una Page por informe (permisos por departamento, perfil o grupo de
    Keycloak) más la de Orígenes de datos. Se lee del catálogo actual: si se
    añaden informes, otra migración igual los da de alta."""
    Page = apps.get_model('gateway', 'Page')
    for orden, pagina in enumerate(informes.PAGINAS):
        Page.objects.update_or_create(
            slug=informes.page_slug(pagina),
            defaults={
                'name': pagina['nombre'],
                'url_name': 'gateway:' + informes.url_name(pagina),
                'group_label': informes.group_label(pagina),
                'order': orden,
            },
        )
    Page.objects.update_or_create(
        slug='config-origenes',
        defaults={
            'name': 'Orígenes de datos',
            'url_name': 'gateway:config_origenes',
            'group_label': 'Configuración · Almacén',
            'order': 9,
        },
    )


def unseed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.filter(slug__startswith='informe-').delete()
    Page.objects.filter(slug='config-origenes').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0015_seed_config_stock_tabla_page'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
