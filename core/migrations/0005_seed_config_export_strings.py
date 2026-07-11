from django.db import migrations

STRINGS = [
    ('gateway.config.tipo_articulo', 'Artículo', '商品', 'Article'),
    ('gateway.config.tipo_familia', 'Familia', '类别', 'Family'),
    ('gateway.stock.export_button', 'Exportar Excel', '导出 Excel', 'Export Excel'),
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
        ('core', '0004_seed_nav_stock_string'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
