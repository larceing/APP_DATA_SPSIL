from django.contrib.auth.models import Group
from django.db import models


class Report(models.Model):
    """Un informe (dashboard) estilo Power BI, compuesto de una o varias páginas."""

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50, blank=True, help_text='Nombre de icono, p.ej. "bar-chart"'
    )
    color = models.CharField(max_length=7, default='#2563eb', help_text='Color hex, p.ej. #2563eb')
    active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    allowed_groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name='reports',
        help_text='Grupos con acceso a este informe. Vacío = solo staff/superusuarios.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def user_has_access(self, user):
        if not self.active:
            return False
        if user.is_superuser or user.is_staff:
            return True
        return self.allowed_groups.filter(user=user).exists()


class ReportPage(models.Model):
    """Una página dentro de un informe, con su propia visualización y fuente de datos."""

    class Visualization(models.TextChoices):
        TABLE = 'table', 'Tabla'
        BAR = 'bar', 'Gráfico de barras'
        LINE = 'line', 'Gráfico de líneas'
        PIE = 'pie', 'Gráfico circular'
        KPI = 'kpi', 'Indicador (KPI)'

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='pages')
    title = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)
    visualization_type = models.CharField(
        max_length=20, choices=Visualization.choices, default=Visualization.TABLE
    )
    data_source = models.ForeignKey(
        'datasources.DataSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='report_pages',
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Configuración de la visualización (columnas, ejes, filtros...)',
    )

    class Meta:
        ordering = ['report', 'order']

    def __str__(self):
        return f'{self.report.name} · {self.title}'
