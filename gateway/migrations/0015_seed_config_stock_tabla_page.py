from django.db import migrations


def seed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.update_or_create(
        slug='config-stock-tabla',
        defaults={
            'name': 'Refresco Stock Tabla',
            'url_name': 'gateway:config_stock_tabla',
            'group_label': 'Configuración · Compras',
            'order': 2,
        },
    )


def unseed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.filter(slug='config-stock-tabla').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0014_stocktablaconfig'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
