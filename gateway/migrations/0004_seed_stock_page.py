from django.conf import settings
from django.db import migrations


def seed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    UserProfile = apps.get_model('gateway', 'UserProfile')
    User = apps.get_model(settings.AUTH_USER_MODEL)

    stock_page, _ = Page.objects.update_or_create(
        slug='stock',
        defaults={
            'name': 'Stock',
            'url_name': 'gateway:stock',
            'group_label': 'Almacén',
            'order': 1,
        },
    )

    # Apadrinar a los usuarios "normales" que ya existían antes de este
    # sistema de permisos: sin esto perderían el acceso a Stock que ya
    # tenían, en silencio, al desplegar esta migración.
    for user in User.objects.filter(is_staff=False, is_superuser=False):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.extra_pages.add(stock_page)


def unseed(apps, schema_editor):
    Page = apps.get_model('gateway', 'Page')
    Page.objects.filter(slug='stock').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('gateway', '0003_page_department_pages_userprofile_extra_pages'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
