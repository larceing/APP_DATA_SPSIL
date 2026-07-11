from django.db import migrations

STRINGS = [
    ('gateway.stock_tabla.title', 'Stock Tabla', '库存表', 'Stock Table'),
    (
        'gateway.stock_tabla.description',
        'Consulta detallada de stock, ventas y necesidades de compra.',
        '库存、销售和采购需求的详细查询。',
        'Detailed stock, sales and purchasing needs report.',
    ),
    ('gateway.stock_tabla.filter_categoria', 'Categoría Proveedores', '供应商类别', 'Supplier Category'),
    ('gateway.stock_tabla.filter_busqueda', 'Código o Descripción', '代码或描述', 'Code or Description'),
    ('gateway.stock_tabla.filter_familia', 'Familia', '类别', 'Family'),
    ('gateway.stock_tabla.filter_todas', 'Todas', '全部', 'All'),
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
        ('core', '0007_seed_home_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
