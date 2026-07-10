from django.db import migrations

STRINGS = [
    ('gateway.stock.title', 'Stock actual', '当前库存', 'Current stock'),
    ('gateway.stock.description', 'Consulta en tiempo real el stock disponible.', '实时查询可用库存。', 'Check available stock in real time.'),
    ('gateway.stock.button', 'Actualizar', '刷新', 'Refresh'),
    ('gateway.stock.search_placeholder', 'Buscar artículo...', '搜索商品...', 'Search article...'),
    ('gateway.stock.error_prefix', 'Error', '错误', 'Error'),
    ('gateway.login.title', 'Iniciar sesión', '登录', 'Log in'),
    ('gateway.login.username', 'Usuario', '用户名', 'Username'),
    ('gateway.login.password', 'Contraseña', '密码', 'Password'),
    ('gateway.login.submit', 'Entrar', '登录', 'Sign in'),
    ('gateway.nav.logout', 'Cerrar sesión', '退出登录', 'Log out'),
    ('gateway.nav.config', 'Configuración', '配置', 'Settings'),
    ('gateway.config.title', 'Configuración de negocio', '业务配置', 'Business configuration'),
    ('gateway.config.add_button', 'Añadir regla', '添加规则', 'Add rule'),
    ('gateway.config.delete_button', 'Eliminar', '删除', 'Delete'),
    ('gateway.config.tipo_label', 'Tipo', '类型', 'Type'),
    ('gateway.config.valor_label', 'Valor', '值', 'Value'),
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
        ('core', '0002_remove_uistring_it_uistring_zh'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
