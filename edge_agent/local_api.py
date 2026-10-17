"""API HTTP local del agente (opcional), para probar y diagnosticar en el
propio equipo X sin pasar por el portal.

Se activa con LOCAL_API_PORT (p. ej. 8765). Si además hay LOCAL_API_TOKEN,
cada petición tiene que traer `Authorization: Bearer <token>` o
`?token=<token>`. Escucha solo en localhost; el docker-compose la publica
en 127.0.0.1 del equipo, nunca hacia la red.

Rutas (solo GET, solo lectura):
  /salud                     estado del agente y del túnel
  /origenes                  configuración (sin contraseñas) + ping a cada origen
  /datasets                  lista de conjuntos de datos
  /datasets/<nombre>         filas del conjunto (JSON columnar); ?refrescar=1
"""

import json
import logging
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import informes

log = logging.getLogger('edge_agent')

ESTADO = {'tunel': 'desconectado', 'gateway_url': None}


class _Handler(BaseHTTPRequestHandler):
    server_version = 'spsil-edge-agent'

    def log_message(self, fmt, *args):
        log.info('local_api %s', fmt % args)

    def _json(self, codigo, cuerpo):
        datos = json.dumps(cuerpo, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _autorizado(self, query):
        token = os.environ.get('LOCAL_API_TOKEN')
        if not token:
            return True
        cabecera = self.headers.get('Authorization', '')
        return cabecera == f'Bearer {token}' or query.get('token', [''])[0] == token

    def do_GET(self):  # noqa: N802 - nombre impuesto por BaseHTTPRequestHandler
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._autorizado(query):
            return self._json(401, {'error': 'token'})
        partes = [p for p in url.path.split('/') if p]
        try:
            if partes == ['salud']:
                return self._json(200, {'ok': True, **ESTADO, 'datasets': len(informes.DATASETS)})
            if partes == ['origenes']:
                return self._json(200, informes.get_sources_status())
            if partes == ['datasets']:
                return self._json(200, informes.get_datasets_list())
            if len(partes) == 2 and partes[0] == 'datasets':
                refrescar = query.get('refrescar', ['0'])[0] in ('1', 'true', 'si')
                return self._json(200, informes.get_dataset(name=partes[1], refrescar=refrescar))
            return self._json(404, {'error': 'no_encontrado'})
        except ValueError as exc:
            return self._json(404, {'error': str(exc)})
        except Exception as exc:  # noqa: BLE001 - se devuelve el error al que prueba
            log.exception('local_api: error en %s', self.path)
            return self._json(500, {'error': str(exc)})


def arrancar():
    puerto = os.environ.get('LOCAL_API_PORT')
    if not puerto:
        return None
    # Por defecto solo en localhost. Dentro de Docker el compose pone
    # LOCAL_API_HOST=0.0.0.0 y publica el puerto únicamente en 127.0.0.1
    # del equipo, así que nunca queda abierta hacia la red.
    host = os.environ.get('LOCAL_API_HOST', '127.0.0.1')
    servidor = ThreadingHTTPServer((host, int(puerto)), _Handler)
    hilo = threading.Thread(target=servidor.serve_forever, name='local_api', daemon=True)
    hilo.start()
    log.info('API local escuchando en %s:%s', host, puerto)
    return servidor
