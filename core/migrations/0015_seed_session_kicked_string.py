from django.db import migrations

STRINGS = [
    (
        'gateway.login.session_kicked',
        'Tu sesión se ha cerrado porque se ha iniciado sesión en otro dispositivo o pestaña.',
        '您的会话已被关闭，因为在其他设备或标签页上登录了。',
        'Your session was closed because it was opened from another device or tab.',
    ),
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
        ('core', '0014_actualizar_ayuda_tipos_hueco'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
