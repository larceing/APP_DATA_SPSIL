from django.db import migrations

STRINGS = [
    ('gateway.nav.group_config_almacen', 'Almacén', '仓库', 'Warehouse'),
    ('gateway.nav.group_config_compras', 'Compras', '采购', 'Purchasing'),
    ('gateway.nav.config_ubicaciones', 'Ubicaciones', '库位', 'Locations'),
    ('gateway.config.hueco_tipos_id', 'ID', 'ID', 'ID'),
    ('gateway.config.hueco_tipos_incluido', 'Incluido', '包含', 'Included'),
    (
        'gateway.config.hueco_tipos_help',
        'Marca qué tipos de hueco cuentan para el cálculo de stock. Los tipos '
        'nuevos aparecen aquí solos en cuanto equipo X los detecta en la BD real '
        '(incluidos por defecto, salvo Salida).',
        '选择哪些货位类型计入库存计算。新类型一旦被X端在真实数据库中检测到会自动出现在此处'
        '（默认包含，"Salida"除外）。',
        'Choose which hueco types count toward the stock calculation. New types '
        'appear here automatically as soon as equipo X detects them in the real '
        'database (included by default, except Salida).',
    ),
    ('gateway.config.ubicaciones_title', 'Ubicaciones', '库位', 'Locations'),
    (
        'gateway.config.ubicaciones_help',
        'Combinaciones de centro/almacén/zona a incluir en los cálculos de stock '
        'por hueco. Añade una fila para sumar, por ejemplo, otra zona sin tocar código.',
        '库存按货位计算时要包含的中心/仓库/区域组合。添加一行即可，例如加入另一个区域，无需修改代码。',
        'Centro/almacén/zona combinations to include in hueco-based stock '
        'calculations. Add a row to include, e.g., another zone without touching code.',
    ),
    ('gateway.config.ubicaciones_centro', 'Centro', '中心', 'Centro'),
    ('gateway.config.ubicaciones_almacen', 'Almacén', '仓库', 'Almacén'),
    ('gateway.config.ubicaciones_zona', 'Zona', '区域', 'Zona'),
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
        ('core', '0011_seed_hueco_tipos_config_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
