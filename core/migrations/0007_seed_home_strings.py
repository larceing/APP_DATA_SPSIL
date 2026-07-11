from django.db import migrations

STRINGS = [
    ('gateway.nav.home', 'Inicio', '首页', 'Home'),
    ('gateway.home.title', 'Inicio', '首页', 'Home'),
    ('gateway.home.welcome', 'Bienvenido', '欢迎', 'Welcome'),
    ('gateway.home.subtitle', 'Elige dónde quieres ir.', '请选择您要前往的页面。', 'Choose where you want to go.'),
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
        ('core', '0006_seed_sidebar_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
