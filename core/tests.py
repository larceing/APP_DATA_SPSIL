from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings

from core import sso


@override_settings(KEYCLOAK_ISSUER='http://keycloak.test/realms/spsil', KEYCLOAK_CLIENT_ID='app-stock',
                   KEYCLOAK_CLIENT_SECRET='x', APP_URL_PUBLICA='https://spsil.test/stock')
class SsoTests(TestCase):
    def _request(self, path):
        request = RequestFactory().get(path)
        SessionMiddleware(lambda r: None).process_request(request)
        return request

    def test_grupos_de_keycloak_dan_rol_y_paginas(self):
        user = sso.sincronizar_usuario({'preferred_username': 'pedro', 'groups': ['Stock']})
        self.assertFalse(user.is_staff)
        self.assertEqual({p.slug for p in user.profile.extra_pages.all()}, {'stock'})
        user = sso.sincronizar_usuario({'preferred_username': 'pedro', 'groups': ['IT', 'Stock Config']})
        self.assertTrue(user.is_staff and user.is_superuser)
        self.assertIn('config-exclusion', {p.slug for p in user.profile.extra_pages.all()})
        self.assertNotIn('stock', {p.slug for p in user.profile.extra_pages.all()})
        self.assertFalse(user.has_usable_password())

    def test_login_manda_a_keycloak(self):
        respuesta = sso.sso_login(self._request('/login/?next=/gateway/stock/'))
        self.assertTrue(respuesta['Location'].startswith('http://keycloak.test/realms/spsil/protocol/openid-connect/auth?'))
        self.assertIn('redirect_uri=https%3A%2F%2Fspsil.test%2Fstock%2Foidc%2Fcallback%2F', respuesta['Location'])

    def test_state_distinto_no_entra(self):
        request = self._request('/oidc/callback/?code=abc&state=otro')
        request.session['sso_state'] = 'bueno'
        with patch('core.sso.requests.post') as mock_post:
            respuesta = sso.sso_callback(request)
        mock_post.assert_not_called()
        self.assertEqual(respuesta.status_code, 400)

    @patch('core.sso.requests.get')
    @patch('core.sso.requests.post')
    def test_vuelta_correcta_inicia_sesion(self, mock_post, mock_get):
        mock_post.return_value = Mock(status_code=200, json=lambda: {'access_token': 't'})
        mock_get.return_value = Mock(status_code=200, json=lambda: {'preferred_username': 'lucia', 'groups': []})
        request = self._request('/oidc/callback/?code=abc&state=bueno')
        request.session['sso_state'] = 'bueno'
        request.session['sso_next'] = '/stock/gateway/home/'
        respuesta = sso.sso_callback(request)
        self.assertEqual((respuesta.status_code, respuesta['Location']), (302, '/stock/gateway/home/'))
        self.assertTrue(get_user_model().objects.filter(username='lucia').exists())
        self.assertEqual(mock_post.call_args.kwargs['data']['grant_type'], 'authorization_code')
