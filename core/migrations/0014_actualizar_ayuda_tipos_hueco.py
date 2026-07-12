from django.db import migrations

STRINGS = [
    (
        'gateway.config.hueco_tipos_help',
        'Marca qué tipos de hueco suman al Stock Total (Artículo + Stock). Por '
        'defecto solo Picking y Almacenamiento, que es como cuadra con el informe '
        'real — puedes marcar temporalmente otros (Carro, Carro Reposición...) '
        'para comprobar algo y desmarcarlos después. Los tipos nuevos aparecen '
        'aquí solos en cuanto equipo X los detecta en la BD real.',
        '选择哪些货位类型计入总库存（商品+库存）。默认只有拣货和存储位，这与真实报表一致——'
        '你可以临时勾选其他类型（如小车、补货小车等）来核对某些数据，之后再取消勾选。新类型'
        '一旦被X端在真实数据库中检测到会自动出现在此处。',
        'Choose which hueco types add up to Stock Total (Artículo + Stock). By '
        'default only Picking and Almacenamiento, matching the real report — you '
        'can temporarily check others (Carro, Carro Reposición...) to verify '
        'something and uncheck them again. New types appear here automatically '
        'as soon as equipo X detects them in the real database.',
    ),
]


def seed(apps, schema_editor):
    UIString = apps.get_model('core', 'UIString')
    for key, es, zh, en in STRINGS:
        UIString.objects.update_or_create(key=key, defaults={'es': es, 'zh': zh, 'en': en})


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_seed_stock_columnas_strings'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
