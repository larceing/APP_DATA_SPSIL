import csv
import io
import os

import requests
from django.core.management.base import BaseCommand, CommandError

from gateway.models import SupplierCategory

# CODPRO de categoría 1 que sí se conservan (el resto de categoría 1 se
# descarta). Viene tal cual del filtro original del Power Query.
CODPRO_PERMITIDOS_CATEGORIA_1 = {'6', '7', '9', '89', '197', '318', '228', '56'}

DEFAULT_SHEET_ID = '1SG_zmnza0Jgp_Jb3v6uyTGpjjKM0mz7kxeDKNfCSkq0'


class Command(BaseCommand):
    help = (
        'Importa UNA VEZ la hoja de Categoría de Proveedores (Google Sheets) a '
        'SupplierCategory. No se vuelve a leer Google Sheets en marcha.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sheet-id',
            default=os.environ.get('SUPPLIER_CATEGORY_SHEET_ID', DEFAULT_SHEET_ID),
        )
        parser.add_argument(
            '--sheet-tab',
            default=os.environ.get('SUPPLIER_CATEGORY_SHEET_TAB', 'Hoja 1'),
        )

    def handle(self, *args, **options):
        sheet_id = options['sheet_id']
        sheet_tab = options['sheet_tab']
        if not sheet_id:
            raise CommandError('Falta SUPPLIER_CATEGORY_SHEET_ID (variable de entorno o --sheet-id).')

        url = (
            f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq'
            f'?tqx=out:csv&sheet={requests.utils.quote(sheet_tab)}'
        )
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        imported = 0
        skipped = 0
        for row in reader:
            codpro = (row.get('CODPRO') or '').strip()
            organizacion = (row.get('Organización') or '').strip()
            categoria_raw = (row.get('CATEGORÍA') or '').strip()
            if not codpro or not categoria_raw:
                continue
            try:
                categoria = int(categoria_raw)
            except ValueError:
                continue

            if categoria == 1 and codpro not in CODPRO_PERMITIDOS_CATEGORIA_1:
                skipped += 1
                continue

            SupplierCategory.objects.update_or_create(
                codpro=codpro,
                defaults={'organizacion': organizacion, 'categoria': categoria, 'activo': True},
            )
            imported += 1

        if imported == 0:
            raise CommandError(
                f'La pestaña "{sheet_tab}" no dio ninguna fila válida con CODPRO/CATEGORÍA. '
                'Comprueba el nombre de la pestaña y que sea pública por enlace.'
            )

        self.stdout.write(self.style.SUCCESS(
            f'Importados {imported} proveedores ({skipped} de categoría 1 descartados '
            f'por no estar en la lista permitida) desde la pestaña "{sheet_tab}".'
        ))
