from django.db import migrations


def ajustar(apps, schema_editor):
    """Stock Total ahora suma todos los tipos marcados "Incluido" (antes
    solo Picking+Almacenamiento fijos, ignorando el resto aunque estuviera
    incluido). El valor verificado contra el informe real es exactamente
    Picking(1)+Almacenamiento(2), así que se deja esa configuración como
    punto de partida — el usuario puede marcar temporalmente otros tipos
    (Carro, Carro Reposición...) desde /gateway/config/tipos-hueco/ para
    comprobar algo, y desmarcarlos después."""
    HuecoTipoCategoria = apps.get_model('gateway', 'HuecoTipoCategoria')
    HuecoTipoCategoria.objects.exclude(id_tipo_hueco__in=[1, 2]).update(activo=False)
    HuecoTipoCategoria.objects.filter(id_tipo_hueco__in=[1, 2]).update(activo=True)


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0009_alter_huecotipocategoria_descripcion'),
    ]

    operations = [
        migrations.RunPython(ajustar, migrations.RunPython.noop),
    ]
