from django.db import migrations

STRINGS = [
    ('gateway.nav.config_stock_tabla', 'Refresco Stock Tabla', '库存表刷新', 'Stock Tabla refresh'),
    ('gateway.config.stock_tabla_title', 'Refresco de Stock Tabla', '库存表刷新', 'Stock Tabla refresh'),
    (
        'gateway.config.stock_tabla_help',
        'Interruptor de emergencia: pausa el refresco en segundo plano de '
        'Stock Tabla en equipo X (la consulta completa de stock/ventas es '
        'pesada) sin necesidad de redeploy. En pausa, la página sigue '
        'mostrando el último dato calculado, solo deja de actualizarse.',
        '紧急开关：暂停X端Stock Tabla的后台刷新（完整的库存/销售查询开销较大），无需重新部署。'
        '暂停期间，页面仍显示最后一次计算的数据，只是不再更新。',
        'Emergency switch: pauses Stock Tabla\'s background refresh on '
        'equipo X (the full stock/sales query is heavy) without a redeploy. '
        'While paused, the page keeps showing the last computed data, it '
        'just stops updating.',
    ),
    ('gateway.config.stock_tabla_activo', 'Refresco activo', '刷新已启用', 'Refresh active'),
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
        ('core', '0016_seed_tab_lock_string'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
