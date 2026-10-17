from django.db import migrations

STRINGS = [
    ('gateway.nav.config_origenes', 'Orígenes de datos', '数据来源', 'Data sources'),
    ('gateway.informes.actualizar', 'Actualizar', '刷新', 'Refresh'),
    ('gateway.informes.recargar_bd', 'Recargar desde la BD', '从数据库重新加载', 'Reload from DB'),
    ('gateway.informes.limpiar', 'Quitar filtros', '清除筛选', 'Clear filters'),
    ('gateway.informes.exportar', 'Exportar CSV', '导出 CSV', 'Export CSV'),
    ('gateway.informes.cargando', 'Cargando datos…', '正在加载数据…', 'Loading data…'),
    ('gateway.informes.actualizado', 'Actualizado', '更新于', 'Updated'),
    ('gateway.informes.origen', 'Origen', '来源', 'Source'),
    ('gateway.informes.buscar', 'Buscar…', '搜索…', 'Search…'),
    ('gateway.informes.todos', 'Todos', '全部', 'All'),
    ('gateway.informes.sin_datos', 'Sin datos con estos filtros', '当前筛选无数据', 'No data for these filters'),
    ('gateway.informes.filas', 'filas', '行', 'rows'),
    ('gateway.informes.error_offline', 'El agente del almacén no está conectado. Revisa el equipo de SPSIL.', '仓库代理未连接。', 'The warehouse agent is not connected.'),
    ('gateway.informes.error', 'No se pudieron cargar los datos', '无法加载数据', 'Could not load the data'),
    ('gateway.origenes.titulo', 'Orígenes de datos', '数据来源', 'Data sources'),
    ('gateway.origenes.descripcion',
     'A qué bases de datos y hojas se conecta el agente del almacén y si responden. Se cambian en el .env del agente (sin contraseñas aquí).',
     '仓库代理连接的数据库和表格及其状态。在代理的 .env 中修改。',
     'Which databases and sheets the warehouse agent connects to, and whether they respond. Change them in the agent .env.'),
    ('gateway.origenes.comprobar', 'Comprobar conexiones', '检查连接', 'Check connections'),
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
        ('core', '0018_seed_portal_string'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
