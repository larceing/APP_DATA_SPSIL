from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core import sso
from gateway import informes, views
from gateway.models import Page, UserProfile


class CatalogoInformesTests(TestCase):
    def test_cada_informe_tiene_page_y_url(self):
        for pagina in informes.PAGINAS:
            page = Page.objects.get(slug=informes.page_slug(pagina))
            self.assertEqual(page.url_name, 'gateway:' + informes.url_name(pagina))
            self.assertTrue(reverse(page.url_name).endswith(f'/informes/{pagina["slug"]}/'))

    def test_visuales_conocidos(self):
        tipos = {'kpi', 'barras', 'columnas', 'tarta', 'tabla', 'resumen', 'matriz'}
        for pagina in informes.PAGINAS:
            for visual in pagina['visuales']:
                self.assertIn(visual['tipo'], tipos, pagina['slug'])
                if visual.get('dataset'):
                    self.assertIn(visual['dataset'], informes.datasets_de(pagina), pagina['slug'])

    def test_grupo_keycloak_da_los_informes_de_su_seccion(self):
        user = sso.sincronizar_usuario({'preferred_username': 'ana', 'groups': ['Informes Cobros']})
        slugs = {p.slug for p in user.profile.extra_pages.all()}
        esperados = {informes.page_slug(p) for p in informes.PAGINAS if p['grupo'] == 'Cobros'}
        self.assertEqual(slugs, esperados)
        user = sso.sincronizar_usuario({'preferred_username': 'ana', 'groups': ['Informes']})
        self.assertEqual(user.profile.extra_pages.count(), len(informes.PAGINAS))


class InformeVistasTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('roger', password='x')
        self.pagina = informes.PAGINAS_POR_SLUG['cobros-clientes']
        views._INFORMES_CACHE.clear()

    def _conceder(self):
        perfil, _ = UserProfile.objects.get_or_create(user=self.user)
        perfil.extra_pages.add(Page.objects.get(slug=informes.page_slug(self.pagina)))

    def test_sin_acceso_403(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('gateway:informe_cobros_clientes')).status_code, 403)
        datos = self.client.get(reverse('gateway:informe_datos', args=['cobros-clientes']))
        self.assertEqual(datos.status_code, 403)

    def test_con_acceso_pinta_la_pagina(self):
        self._conceder()
        self.client.force_login(self.user)
        respuesta = self.client.get(reverse('gateway:informe_cobros_clientes'))
        self.assertContains(respuesta, 'inf-spec')
        self.assertContains(respuesta, 'Cobros clientes')

    def test_los_anios_se_resuelven(self):
        spec = views._resolver_anios(informes.PAGINAS_POR_SLUG['clientes-ritmo'])
        self.assertNotIn('{Y0}', str(spec))

    def test_datos_piden_el_dataset_al_agente(self):
        self._conceder()
        self.client.force_login(self.user)
        payload = {'ok': True, 'columns': ['CODCLI'], 'rows': [['1']], 'dicts': {}, 'updated_at': '2026-10-17 10:00:00'}
        with patch('gateway.views._ask_gateway', new=AsyncMock(return_value=payload)) as pedir:
            respuesta = self.client.get(reverse('gateway:informe_datos', args=['cobros-clientes']))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['datasets']['cobros_clientes']['rows'], [['1']])
        query, params = pedir.call_args.args[:2]
        self.assertEqual((query, params['name']), ('dataset', 'cobros_clientes'))

    def test_agente_desconectado_503(self):
        self._conceder()
        self.client.force_login(self.user)
        error = views.GatewayFetchError(503, 'node_offline')
        with patch('gateway.views._ask_gateway', new=AsyncMock(side_effect=error)):
            respuesta = self.client.get(reverse('gateway:informe_datos', args=['cobros-clientes']))
        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json()['error'], 'node_offline')
