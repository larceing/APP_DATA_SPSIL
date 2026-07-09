from django.db import models


class DataSource(models.Model):
    """Un origen de datos: un archivo CSV/Excel a importar para un entorno concreto."""

    class Environment(models.TextChoices):
        TEST = 'test', 'Prueba'
        PROD = 'prod', 'Productivo'
        DEMO = 'demo', 'Demo'

    name = models.CharField(max_length=150)
    file = models.FileField(
        upload_to='datasources/%Y/%m/', blank=True, null=True, help_text='Archivo CSV o Excel (.xlsx)'
    )
    target_table = models.SlugField(
        max_length=100,
        help_text='Nombre lógico de la tabla destino (identifica los datos importados)',
    )
    environment = models.CharField(max_length=10, choices=Environment.choices, default=Environment.TEST)
    active = models.BooleanField(default=True)
    last_imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['target_table', 'environment'], name='unique_target_table_per_environment'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.get_environment_display()})'


class ImportedRow(models.Model):
    """Fila importada de un DataSource.

    Actúa como tabla temporal genérica para los datos de CSV/Excel: en vez de
    crear una tabla real por cada DataSource, cada fila se guarda como JSON
    ligada a su DataSource. El entorno productivo sustituirá esto por consultas
    a la BD real, sin cambiar el modelo de Report/ReportPage.
    """

    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='rows')
    row_number = models.PositiveIntegerField()
    data = models.JSONField()
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data_source', 'row_number']
        indexes = [models.Index(fields=['data_source', 'row_number'])]

    def __str__(self):
        return f'{self.data_source.target_table} #{self.row_number}'
