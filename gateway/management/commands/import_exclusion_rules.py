import csv
import io
import os

import requests
from django.core.management.base import BaseCommand, CommandError

from gateway.models import ExclusionRule


class Command(BaseCommand):
    help = (
        'Importa UNA VEZ la hoja de exclusión de Google Sheets (columnas CODART/FAMILIA) '
        'a ExclusionRule. A partir de aquí la lista se edita desde /gateway/config/, no '
        'se vuelve a leer Google Sheets en marcha.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--sheet-id', default=os.environ.get('GOOGLE_SHEET_ID'))
        parser.add_argument('--sheet-tab', default=os.environ.get('GOOGLE_SHEET_TAB', 'Hoja 2'))

    def handle(self, *args, **options):
        sheet_id = options['sheet_id']
        sheet_tab = options['sheet_tab']
        if not sheet_id:
            raise CommandError('Falta GOOGLE_SHEET_ID (variable de entorno o --sheet-id).')

        url = (
            f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq'
            f'?tqx=out:csv&sheet={requests.utils.quote(sheet_tab)}'
        )
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        articulos, familias = set(), set()
        for row in reader:
            codart = (row.get('CODART') or '').strip().upper()
            familia = (row.get('FAMILIA') or '').strip().upper()
            if codart:
                articulos.add(codart)
            if familia:
                familias.add(familia)

        if not articulos and not familias:
            raise CommandError(
                f'La pestaña "{sheet_tab}" no dio ninguna fila con CODART/FAMILIA. '
                'Comprueba el nombre de la pestaña (GOOGLE_SHEET_TAB) y que sea pública por enlace.'
            )

        for valor in articulos:
            ExclusionRule.objects.update_or_create(
                tipo=ExclusionRule.Tipo.ARTICULO, valor=valor, defaults={'activo': True},
            )
        for valor in familias:
            ExclusionRule.objects.update_or_create(
                tipo=ExclusionRule.Tipo.FAMILIA, valor=valor, defaults={'activo': True},
            )

        self.stdout.write(self.style.SUCCESS(
            f'Importadas {len(articulos)} exclusiones de artículo y {len(familias)} de familia '
            f'desde la pestaña "{sheet_tab}".'
        ))
