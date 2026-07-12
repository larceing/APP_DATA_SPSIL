from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class GatewayNode(models.Model):
    """Un equipo remoto (equipo X) que se conecta por WebSocket para servir datos en vivo."""

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=100, unique=True)
    token_hash = models.CharField(max_length=128, blank=True, editable=False)
    active = models.BooleanField(default=True)
    last_connected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def set_token(self, raw_token):
        self.token_hash = make_password(raw_token)

    def check_token(self, raw_token):
        return bool(self.token_hash) and check_password(raw_token, self.token_hash)


class ExclusionRule(models.Model):
    """Artículo o familia a excluir del stock, editable desde la pantalla de
    configuración de negocio. Sustituye editar el Google Sheet a mano; la
    hoja solo se usa una vez para la carga inicial (ver management command
    import_exclusion_rules)."""

    class Tipo(models.TextChoices):
        ARTICULO = 'articulo', 'Artículo'
        FAMILIA = 'familia', 'Familia'

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    valor = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', 'valor']
        constraints = [
            models.UniqueConstraint(fields=['tipo', 'valor'], name='unique_exclusion_tipo_valor'),
        ]

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.valor}'

    def save(self, *args, **kwargs):
        self.valor = self.valor.strip().upper()
        super().save(*args, **kwargs)


class SupplierCategory(models.Model):
    """Categoría (1-4) y organización de un proveedor (CODPRO), usada para
    los multiplicadores de Stock Mín/Máx/Punto de Pedido de Stock Tabla.
    Se importa una sola vez desde un Google Sheet de control (ver
    management command import_supplier_categories); no se vuelve a leer
    Google Sheets en marcha."""

    codpro = models.CharField(max_length=20, unique=True)
    organizacion = models.CharField(max_length=150, blank=True)
    categoria = models.PositiveSmallIntegerField()
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['codpro']
        verbose_name_plural = 'Supplier categories'

    def __str__(self):
        return f'{self.codpro} (cat. {self.categoria})'


class HuecoTipoCategoria(models.Model):
    """Filtro de inclusión/exclusión sobre los tipos de hueco físico reales
    de MariaDB (TipoHueco: Picking, Almacenamiento, Carro, Entrada,
    Salida...). `activo=False` excluye ese tipo por completo del cálculo
    de stock (Stock y Stock Tabla) — no es una categorización, Picking y
    Almacenamiento como columnas son siempre los tipoHueco 1 y 2 fijos
    (así los calcula el Power BI original).

    Keyed por id_tipo_hueco (la clave real de TipoHueco.idTipoHueco en
    MariaDB), no por el texto: equipo X manda de vuelta los tipos que ve
    realmente en la BD (id + descripción) y aquí se registran solos
    (activos, salvo el 9 = Salida, excluido por defecto — igual que el
    filtro que traía el Power BI original) para que el usuario los
    revise en /gateway/config/tipos-hueco/ — ver
    gateway/views.py::_registrar_tipos_hueco_nuevos."""

    id_tipo_hueco = models.PositiveIntegerField(unique=True)
    descripcion = models.CharField(max_length=100)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id_tipo_hueco']
        verbose_name_plural = 'Hueco tipo categorias'

    def __str__(self):
        return f'{self.id_tipo_hueco} - {self.descripcion} ({"incluido" if self.activo else "excluido"})'


class UbicacionAlmacen(models.Model):
    """Combinación (centro, almacén, zona) de MariaDB a incluir en los
    cálculos de stock por hueco. Antes eran variables de entorno fijas en
    equipo X (ID_CENTRO/ID_ALMACEN, más idZona=1 hardcodeado); ahora es
    configuración editable — añadir una fila es, por ejemplo, sumar una
    segunda zona sin tocar código ni redeploy."""

    id_centro = models.PositiveIntegerField()
    id_almacen = models.PositiveIntegerField()
    id_zona = models.PositiveIntegerField()
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id_centro', 'id_almacen', 'id_zona']
        constraints = [
            models.UniqueConstraint(
                fields=['id_centro', 'id_almacen', 'id_zona'], name='unique_ubicacion_almacen',
            ),
        ]

    def __str__(self):
        return f'Centro {self.id_centro} / Almacén {self.id_almacen} / Zona {self.id_zona}'


class Page(models.Model):
    """Una página/informe del sidebar (hoy solo 'Stock'). El acceso se
    concede por departamento (todos los miembros la ven) o suelto a un
    usuario concreto (UserProfile.extra_pages), para casos tipo "Roger
    es de Almacén pero también lleva Logística"."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    url_name = models.CharField(
        max_length=100, help_text='Nombre de URL Django, ej. gateway:stock'
    )
    group_label = models.CharField(
        max_length=100, help_text='Título del grupo en el sidebar, ej. Almacén'
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['group_label', 'order', 'name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """Departamento de negocio: agrupa usuarios y las páginas que todos
    sus miembros pueden ver."""

    name = models.CharField(max_length=100, unique=True)
    pages = models.ManyToManyField(Page, blank=True, related_name='departments')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Perfil ligado a un usuario de Django. El rol (usuario/admin/superadmin)
    ya lo dan is_staff/is_superuser; este perfil añade el departamento (acceso
    de grupo) y páginas sueltas concedidas solo a este usuario."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='users'
    )
    extra_pages = models.ManyToManyField(Page, blank=True, related_name='granted_profiles')

    def __str__(self):
        return self.user.get_username()

    def accessible_pages(self):
        pages = {page.id: page for page in self.extra_pages.all()}
        if self.department_id:
            for page in self.department.pages.all():
                pages[page.id] = page
        return sorted(pages.values(), key=lambda p: (p.group_label, p.order, p.name))


class ActiveSession(models.Model):
    """Token de la única sesión "válida" de un Usuario normal (no
    Admin/Superadmin, exentos): cada login nuevo lo reemplaza
    (gateway/signals.py), y gateway/middleware.py corta cualquier otra
    sesión que no lleve este token en su siguiente petición."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='active_session'
    )
    token = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.get_username()
