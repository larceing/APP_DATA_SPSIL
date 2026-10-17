import asyncio
import functools
import json
import logging
import os

import websockets

import cache
import informes
import local_api
from db import get_stock_actual
from stock_tabla import _refrescar_stock_raw, _refrescar_ventas_y_huecos, get_stock_tabla, set_activo

# p.ej. wss://y.example.com/ws/gateway/nave-central/ — sin él, el agente
# arranca solo con la API local (modo prueba en el propio equipo X).
GATEWAY_URL = os.environ.get('GATEWAY_URL', '')
NODE_TOKEN = os.environ.get('NODE_TOKEN', '')
# Ventas/huecos ya son baratos (~1s): refresco frecuente. VW_OFERTAS_STOCK_RAW
# se llama entera sin filtro y tarda ~27s en sí misma — con 30s de
# intervalo se repetía prácticamente sin parar, día y noche, aunque nadie
# estuviera mirando Stock Tabla (carga constante e innecesaria sobre SQL
# Server y la red de equipo X). Stock/ventas de los últimos 30 días no
# necesitan frescura al segundo para un informe de compras, así que el
# intervalo por defecto sube a 10 minutos — sigue siendo configurable por
# variable de entorno si hiciera falta otro valor.
STOCK_TABLA_REFRESH_SECONDS = int(os.environ.get('STOCK_TABLA_REFRESH_SECONDS', '15'))
STOCK_RAW_REFRESH_SECONDS = int(os.environ.get('STOCK_RAW_REFRESH_SECONDS', '600'))

QUERY_HANDLERS = {
    'stock_actual': get_stock_actual,
    'stock_tabla': get_stock_tabla,
    # Aviso inmediato desde /gateway/config/stock-tabla/ al guardar el
    # interruptor de pausa — no consulta nada, solo actualiza el flag en
    # memoria (ver stock_tabla._CONFIG_ACTIVO).
    'stock_tabla_config': set_activo,
    # Informes Susana / Cobros / Almacén (edge_agent/informes.py): un solo
    # tipo de consulta con el nombre del conjunto de datos en params.
    'dataset': informes.get_dataset,
    'datasets_list': informes.get_datasets_list,
    'sources_status': informes.get_sources_status,
}

log = logging.getLogger('edge_agent')


async def handle_message(ws, raw_message):
    message = json.loads(raw_message)
    handler = QUERY_HANDLERS.get(message['query'])
    try:
        if handler is None:
            reply = {'request_id': message['request_id'], 'ok': False, 'rows': [], 'error': 'unknown_query'}
        else:
            # run_in_executor: una consulta bloqueante (pymysql/pytds) no
            # debe congelar la recepción de otros mensajes por el mismo
            # WebSocket mientras se resuelve.
            loop = asyncio.get_running_loop()
            call = functools.partial(handler, **message.get('params', {}))
            result = await loop.run_in_executor(None, call)
            # Un handler puede devolver una lista de filas (stock_actual)
            # o un dict con clave 'rows' más datos extra (stock_tabla,
            # para tipos_hueco_descubiertos) sin romper el contrato genérico.
            if isinstance(result, dict) and 'rows' in result:
                reply = {'request_id': message['request_id'], 'ok': True, 'error': None, **result}
            else:
                reply = {'request_id': message['request_id'], 'ok': True, 'rows': result, 'error': None}
    except Exception as exc:
        log.exception('Error resolviendo query %s', message.get('query'))
        reply = {'request_id': message['request_id'], 'ok': False, 'rows': [], 'error': str(exc)}
    await ws.send(json.dumps(reply))


async def run():
    if not GATEWAY_URL:
        log.warning('Sin GATEWAY_URL: no se abre el túnel, solo la API local (si LOCAL_API_PORT está puesto)')
        local_api.ESTADO['tunel'] = 'sin configurar'
        return
    url = f'{GATEWAY_URL}?token={NODE_TOKEN}'
    local_api.ESTADO['gateway_url'] = GATEWAY_URL
    backoff = 1
    while True:
        try:
            # Margen amplio: no necesitamos detectar una caída real en
            # segundos, con 2 minutos sobra para este uso. max_size sin
            # límite: algunos informes (facturas) mandan varios MB de filas.
            async with websockets.connect(url, ping_interval=30, ping_timeout=120, max_size=None) as ws:
                log.info('Conectado a %s', GATEWAY_URL)
                local_api.ESTADO['tunel'] = 'conectado'
                backoff = 1
                async for raw_message in ws:
                    # Cada mensaje en su propia tarea: un informe lento no
                    # bloquea a los demás que llegan por el mismo túnel.
                    asyncio.create_task(handle_message(ws, raw_message))
        except Exception as exc:
            local_api.ESTADO['tunel'] = 'desconectado'
            log.warning('Conexión perdida (%s); reintento en %ss', exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def main():
    local_api.arrancar()
    await asyncio.gather(
        run(),
        cache.refresh_loop('stock_raw', _refrescar_stock_raw, STOCK_RAW_REFRESH_SECONDS),
        cache.refresh_loop('stock_tabla_ventas_huecos', _refrescar_ventas_y_huecos, STOCK_TABLA_REFRESH_SECONDS),
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main())
