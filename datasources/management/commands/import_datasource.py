import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from datasources.models import DataSource, ImportedRow

try:
    import openpyxl
except ImportError:
    openpyxl = None


class Command(BaseCommand):
    help = 'Importa el archivo CSV/Excel de un DataSource y carga sus filas en ImportedRow.'

    def add_arguments(self, parser):
        parser.add_argument('target_table', help='target_table del DataSource a importar')
        parser.add_argument(
            '--environment',
            default=None,
            help='Entorno del DataSource (test/prod/demo), para desambiguar si hay varios',
        )
        parser.add_argument(
            '--file',
            default=None,
            help='Ruta a un CSV/Excel alternativo, en vez del archivo ya asociado al DataSource',
        )
        parser.add_argument(
            '--clear', action='store_true', help='Elimina las filas existentes antes de importar'
        )

    def handle(self, *args, **options):
        data_source = self._resolve_data_source(options['target_table'], options['environment'])
        file_path = self._resolve_file_path(data_source, options['file'])
        rows = self._read_rows(file_path)

        if options['clear']:
            data_source.rows.all().delete()

        objs = [
            ImportedRow(data_source=data_source, row_number=i, data=row)
            for i, row in enumerate(rows, start=1)
        ]
        ImportedRow.objects.bulk_create(objs, batch_size=500)

        data_source.last_imported_at = timezone.now()
        data_source.save(update_fields=['last_imported_at'])

        self.stdout.write(
            self.style.SUCCESS(
                f"Importadas {len(objs)} filas en '{data_source}' desde {file_path.name}"
            )
        )

    def _resolve_data_source(self, target_table, environment):
        qs = DataSource.objects.filter(target_table=target_table)
        if environment:
            qs = qs.filter(environment=environment)
        if qs.count() > 1:
            raise CommandError(
                f"Hay varios DataSource con target_table='{target_table}'. "
                'Especifica --environment para desambiguar.'
            )
        data_source = qs.first()
        if data_source is None:
            raise CommandError(f"No existe ningún DataSource con target_table='{target_table}'.")
        return data_source

    def _resolve_file_path(self, data_source, file_option):
        file_path = Path(file_option) if file_option else None
        if file_path is None:
            if not data_source.file:
                raise CommandError(f"El DataSource '{data_source}' no tiene archivo asociado. Usa --file.")
            file_path = Path(data_source.file.path)
        if not file_path.exists():
            raise CommandError(f'No se encuentra el archivo: {file_path}')
        return file_path

    def _read_rows(self, file_path):
        suffix = file_path.suffix.lower()
        if suffix == '.csv':
            return self._read_csv(file_path)
        if suffix in ('.xlsx', '.xlsm'):
            return self._read_excel(file_path)
        raise CommandError(f'Formato no soportado: {suffix}. Usa .csv o .xlsx')

    def _read_csv(self, file_path):
        with open(file_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    def _read_excel(self, file_path):
        if openpyxl is None:
            raise CommandError('openpyxl no está instalado. Ejecuta: pip install openpyxl')
        workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header = [str(h) if h is not None else '' for h in next(rows_iter)]
        except StopIteration:
            return []
        rows = []
        for values in rows_iter:
            if all(v is None for v in values):
                continue
            rows.append({header[i]: values[i] for i in range(len(header))})
        return rows
