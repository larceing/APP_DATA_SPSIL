from django.db import migrations

STRINGS = [
    ('gateway.nav.group_almacen', 'Almacén', '仓库', 'Warehouse'),
    ('gateway.nav.group_config', 'Configuración', '配置', 'Configuration'),
    ('gateway.nav.group_admin', 'Administración', '管理', 'Administration'),
    ('gateway.nav.users', 'Usuarios', '用户', 'Users'),
    ('gateway.nav.nodes', 'Nodos', '节点', 'Nodes'),
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
        ('core', '0005_seed_config_export_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
