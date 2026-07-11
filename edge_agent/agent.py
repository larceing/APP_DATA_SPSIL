import asyncio
import functools
import json
import logging
import os

import websockets

import cache
from db import get_stock_actual
from stock_tabla import _compute_base_data, get_stock_tabla

GATEWAY_URL = os.environ['GATEWAY_URL']  # p.ej. wss://y.example.com/ws/gateway/nave-central/
NODE_TOKEN = os.environ['NODE_TOKEN']
STOCK_TABLA_REFRESH_SECONDS = int(os.environ.get('STOCK_TABLA_REFRESH_SECONDS', '15'))

QUERY_HANDLERS = {
    'stock_actual': get_stock_actual,
    'stock_tabla': get_stock_tabla,
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
            rows = await loop.run_in_executor(None, call)
            reply = {'request_id': message['request_id'], 'ok': True, 'rows': rows, 'error': None}
    except Exception as exc:
        log.exception('Error resolviendo query %s', message.get('query'))
        reply = {'request_id': message['request_id'], 'ok': False, 'rows': [], 'error': str(exc)}
    await ws.send(json.dumps(reply))


async def run():
    url = f'{GATEWAY_URL}?token={NODE_TOKEN}'
    backoff = 1
    while True:
        try:
            # Margen amplio: no necesitamos detectar una caída real en
            # segundos, con 2 minutos sobra para este uso.
            async with websockets.connect(url, ping_interval=30, ping_timeout=120) as ws:
                log.info('Conectado a %s', GATEWAY_URL)
                backoff = 1
                async for raw_message in ws:
                    await handle_message(ws, raw_message)
        except Exception as exc:
            log.warning('Conexión perdida (%s); reintento en %ss', exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def main():
    await asyncio.gather(
        run(),
        cache.refresh_loop('stock_tabla_base', _compute_base_data, STOCK_TABLA_REFRESH_SECONDS),
    )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main())
