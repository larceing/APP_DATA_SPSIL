from django.db import migrations

STRINGS = [
    ('gateway.config.supplier_title', 'Categoría de Proveedores', '供应商类别', 'Supplier Category'),
    ('gateway.config.supplier_codpro', 'CODPRO', 'CODPRO', 'CODPRO'),
    ('gateway.config.supplier_organizacion', 'Organización', '组织', 'Organization'),
    ('gateway.config.supplier_categoria', 'Categoría', '类别编号', 'Category'),
    ('gateway.config.save_button', 'Guardar', '保存', 'Save'),
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
        ('core', '0008_seed_stock_tabla_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
