from django.db import migrations


def seed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.update_or_create(
        slug='stock-tabla',
        defaults={
            'name': 'Stock Tabla',
            'url_name': 'gateway:stock_tabla',
            'group_label': 'Compras',
            'order': 1,
        },
    )


def unseed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.filter(slug='stock-tabla').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0005_suppliercategory'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
