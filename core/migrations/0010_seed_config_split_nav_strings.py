from django.db import migrations

STRINGS = [
    ('gateway.nav.config_exclusion', 'Exclusiones', '排除规则', 'Exclusions'),
    ('gateway.nav.config_suppliers', 'Categoría Proveedores', '供应商类别', 'Supplier Category'),
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
        ('core', '0009_seed_supplier_category_config_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
