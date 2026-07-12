from django.db import migrations

STRINGS = [
    ('gateway.stock.col_articulo', 'Artículo', '商品', 'Article'),
    ('gateway.stock.col_stock', 'Stock', '库存', 'Stock'),
]


def seed(apps, schema_editor):
    UIString = apps.get_model('core', 'UIString')
    for key, es, zh, en in STRINGS:
        UIString.objects.update_or_create(key=key, defaults={'es': es, 'zh': zh, 'en': en})


def unseed(apps, schema_editor):
    UIString = apps.get_model('core', 'UIString')
    UIString.objects.filter(key__in=[row[0] for row in STRINGS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_seed_ubicaciones_and_submenu_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
