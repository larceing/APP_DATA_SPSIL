from django.db import migrations

STRINGS = [
    ('gateway.nav.config_hueco_tipos', 'Tipos de Hueco', '货位类型', 'Hueco Types'),
    ('gateway.config.hueco_tipos_title', 'Tipos de Hueco', '货位类型', 'Hueco Types'),
    (
        'gateway.config.hueco_tipos_help',
        'Clasifica cada tipo de hueco físico como Picking, Almacenamiento o Ignorar. '
        'Los tipos nuevos aparecen aquí solos (sin clasificar) en cuanto equipo X los detecta.',
        '将每种货位类型分类为拣货、存储或忽略。新类型一旦被X端检测到会自动出现在此处（未分类）。',
        'Classify each physical hueco type as Picking, Storage, or Ignore. '
        'New types appear here automatically (unclassified) as soon as equipo X detects them.',
    ),
    ('gateway.config.hueco_tipos_descripcion', 'Descripción', '描述', 'Description'),
    ('gateway.config.hueco_tipos_categoria', 'Categoría', '类别', 'Category'),
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
        ('core', '0010_seed_config_split_nav_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
