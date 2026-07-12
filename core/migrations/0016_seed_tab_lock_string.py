from django.db import migrations

STRINGS = [
    (
        'gateway.tabs.blocked_message',
        'Esta cuenta ya se está usando en otra pestaña o ventana. Cierra esta '
        'para seguir en la otra.',
        '此账户已在另一个标签页或窗口中使用。请关闭此页面，在另一个中继续操作。',
        'This account is already in use in another tab or window. Close this '
        'one to continue in the other.',
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
        ('core', '0015_seed_session_kicked_string'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
