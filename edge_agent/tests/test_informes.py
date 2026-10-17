"""Pruebas sin base de datos de la lógica de informes del agente.

    cd edge_agent && python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fuentes  # noqa: E402
import informes  # noqa: E402


class ClavesTests(unittest.TestCase):
    def test_clave_rep(self):
        self.assertEqual(informes.clave_rep('     838'), '838')
        self.assertEqual(informes.clave_rep('838-HAO'), '838')
        self.assertEqual(informes.clave_rep('0044'), '44')
        self.assertEqual(informes.clave_rep('610-AHAN'), '610')
        self.assertIsNone(informes.clave_rep(None))

    def test_tipo_pedido(self):
        self.assertEqual(informes._tipo_pedido('P123456'), 'P')
        self.assertEqual(informes._tipo_pedido('Y998877'), 'Y')
        self.assertEqual(informes._tipo_pedido('P12'), 'Otro')
        self.assertEqual(informes._tipo_pedido(None), 'Otro')

    def test_numeros_y_fechas_de_hojas(self):
        self.assertEqual(informes._num('1.234,56'), 1234.56)
        self.assertEqual(informes._num('12,5'), 12.5)
        self.assertEqual(informes._num(''), 0.0)
        self.assertEqual(informes._fecha('17/10/2026'), '2026-10-17')
        self.assertEqual(informes._fecha('2026-10-17 00:00:00'), '2026-10-17')
        self.assertIsNone(informes._fecha('no'))


class TransporteTests(unittest.TestCase):
    def test_provincia_por_codigo_postal(self):
        self.assertEqual(informes._codprovi_cp('03201'), '03')
        self.assertEqual(informes._codprovi_cp('3201'), '03')
        self.assertEqual(informes._codprovi_cp('46191'), '46')
        self.assertEqual(informes._codprovi_cp('800'), '01')
        self.assertIsNone(informes._codprovi_cp(''))

    def test_rango_y_escalado(self):
        self.assertEqual(informes._rango_peso(None), '0-100')
        self.assertEqual(informes._rango_peso(150), '101-200')
        self.assertEqual(informes._rango_peso(950), '900+')
        self.assertEqual(informes._escalado('0-100', 3), '1-7')
        self.assertEqual(informes._escalado('201-400', 2), '2')
        self.assertEqual(informes._escalado('201-400', 5), '3-7')
        self.assertEqual(informes._escalado('900+', 9), '7')
        self.assertIsNone(informes._escalado('0-100', 0))

    def test_codcli_del_consignatario(self):
        self.assertEqual(informes._codcli_desde_texto('TIENDA *4600005* SL'), '4600005')
        self.assertEqual(informes._codcli_desde_texto('BAZAR (7101)'), '7101')
        self.assertIsNone(informes._codcli_desde_texto('SIN CODIGO'))


class ComercialesTests(unittest.TestCase):
    def setUp(self):
        informes._CACHE.clear()

    def test_enriquecer_aplica_cambios_y_grupos(self):
        com = {'correctos': {'853': {'GRUPOS': 'A', 'ENTRA': 'LISTADO', 'ZIP': '46'}}, 'cambios': {'854': '853'}}
        reps = {'853': {'NOMREP': '853-LUIS', 'Nombre': 'LUIS'}}
        with patch.object(informes, 'comerciales', return_value=com), patch.object(informes, 'representantes', return_value=reps):
            fila = informes.enriquecer_rep({'CODREP': '     854'}, 'CODREP')
            self.assertEqual((fila['CODREP_NORM'], fila['GRUPOS'], fila['Listado'], fila['NOMREP']), ('853', 'A', 'LISTADO', '853-LUIS'))
            fila = informes.enriquecer_rep({'CODREP': '999'}, 'CODREP')
            self.assertEqual((fila['GRUPOS'], fila['Listado']), ('Z', 'NO LISTADO'))


class RespuestaTests(unittest.TestCase):
    def setUp(self):
        informes._CACHE.clear()

    def test_columnar_y_diccionario(self):
        filas = [{'CLIENTE': 'A' if i % 2 else 'B', 'IMPORTE': i} for i in range(300)]
        columnas, valores = informes._columnar(filas)
        valores, dicts = informes._codificar_diccionario(columnas, valores)
        self.assertEqual(columnas, ['CLIENTE', 'IMPORTE'])
        self.assertEqual(set(dicts), {'0'})
        self.assertEqual(dicts['0'][valores[1][0]], 'A')
        self.assertEqual(valores[5][1], 5)

    def test_get_dataset_cachea(self):
        llamadas = []

        def falso(params):
            llamadas.append(params)
            return [{'x': 1}]

        informes.DATASETS['_prueba'] = {'func': falso, 'ttl': 60, 'descripcion': ''}
        try:
            r1 = informes.get_dataset(name='_prueba', ubicaciones=[1])
            r2 = informes.get_dataset(name='_prueba', ubicaciones=[1])
            informes.get_dataset(name='_prueba', ubicaciones=[1], refrescar=True)
        finally:
            del informes.DATASETS['_prueba']
        self.assertEqual(r1['rows'], [[1]])
        self.assertEqual(r1['updated_at'], r2['updated_at'])
        self.assertEqual(len(llamadas), 2)

    def test_dataset_desconocido(self):
        with self.assertRaises(ValueError):
            informes.get_dataset(name='no_existe')


class FuentesTests(unittest.TestCase):
    def test_nombres_nuevos_y_antiguos(self):
        with patch.dict(os.environ, {'MSSQL_HOST': '10.0.0.1', 'A3_HOST': ''}, clear=False):
            self.assertEqual(fuentes.config_a3()['host'], '10.0.0.1')
        with patch.dict(os.environ, {'MSSQL_HOST': '10.0.0.1', 'A3_HOST': '10.9.9.9'}, clear=False):
            self.assertEqual(fuentes.config_a3()['host'], '10.9.9.9')

    def test_hoja_por_id_o_url(self):
        with patch.dict(os.environ, {'GSHEET_ZONA_COM': 'abc', 'GSHEET_ZONA_COM_HOJA': 'Hoja 2'}):
            c = fuentes.config_gsheet('ZONA_COM')
            self.assertIn('/d/abc/gviz/tq?tqx=out:csv&sheet=Hoja%202', c['url'])
        with patch.dict(os.environ, {'GSHEET_ZONA_COM': 'https://ejemplo.test/hoja.csv'}):
            self.assertEqual(fuentes.config_gsheet('ZONA_COM')['url'], 'https://ejemplo.test/hoja.csv')

    def test_describir_no_muestra_claves(self):
        with patch.dict(os.environ, {'A3_PASSWORD': 'secreta', 'INNERTIA_PASSWORD': 'otra'}):
            texto = str(fuentes.describir())
        self.assertNotIn('secreta', texto)
        self.assertNotIn('otra', texto)

    def test_valor_json(self):
        import datetime
        import decimal
        self.assertEqual(fuentes.valor_json(decimal.Decimal('1.5')), 1.5)
        self.assertEqual(fuentes.valor_json(datetime.datetime(2026, 10, 17)), '2026-10-17')
        self.assertEqual(fuentes.valor_json('  838 '), '838')


if __name__ == '__main__':
    unittest.main()
