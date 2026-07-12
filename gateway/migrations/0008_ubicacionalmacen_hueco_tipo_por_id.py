from django.db import migrations, models


def vaciar_hueco_tipo_categoria(apps, schema_editor):
    """Los registros actuales solo tienen descripcion+categoria (texto);
    con el nuevo esquema (keyed por id_tipo_hueco real de MariaDB) no hay
    forma fiable de mapear uno a otro. Se vacía y se deja que equipo X
    los vuelva a registrar solos (activos, salvo el 9=Salida) la próxima
    vez que responda una consulta — ver gateway/views.py::_registrar_tipos_hueco_nuevos."""
    HuecoTipoCategoria = apps.get_model('gateway', 'HuecoTipoCategoria')
    HuecoTipoCategoria.objects.all().delete()


def seed_ubicacion_inicial(apps, schema_editor):
    """Semilla con los valores ya vistos en producción (antes fijos por
    variable de entorno ID_CENTRO/ID_ALMACEN + idZona=1 hardcodeado)."""
    UbicacionAlmacen = apps.get_model('gateway', 'UbicacionAlmacen')
    UbicacionAlmacen.objects.get_or_create(id_centro=6, id_almacen=1, id_zona=1)


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0007_huecotipocategoria'),
    ]

    operations = [
        migrations.RunPython(vaciar_hueco_tipo_categoria, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='huecotipocategoria',
            name='categoria',
        ),
        migrations.AddField(
            model_name='huecotipocategoria',
            name='id_tipo_hueco',
            field=models.PositiveIntegerField(default=0, unique=True),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name='huecotipocategoria',
            options={'ordering': ['id_tipo_hueco'], 'verbose_name_plural': 'Hueco tipo categorias'},
        ),
        migrations.CreateModel(
            name='UbicacionAlmacen',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('id_centro', models.PositiveIntegerField()),
                ('id_almacen', models.PositiveIntegerField()),
                ('id_zona', models.PositiveIntegerField()),
                ('activo', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['id_centro', 'id_almacen', 'id_zona'],
            },
        ),
        migrations.AddConstraint(
            model_name='ubicacionalmacen',
            constraint=models.UniqueConstraint(
                fields=('id_centro', 'id_almacen', 'id_zona'), name='unique_ubicacion_almacen',
            ),
        ),
        migrations.RunPython(seed_ubicacion_inicial, migrations.RunPython.noop),
    ]
