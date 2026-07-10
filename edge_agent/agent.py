import asyncio
import json
import logging
import os

import websockets

from db import get_stock_actual

GATEWAY_URL = os.environ['GATEWAY_URL']  # p.ej. wss://y.example.com/ws/gateway/nave-central/
NODE_TOKEN = os.environ['NODE_TOKEN']

QUERY_HANDLERS = {
    'stock_actual': get_stock_actual,
}

log = logging.getLogger('edge_agent')


async def handle_message(ws, raw_message):
    message = json.loads(raw_message)
    handler = QUERY_HANDLERS.get(message['query'])
    try:
        if handler is None:
            reply = {'request_id': message['request_id'], 'ok': False, 'rows': [], 'error': 'unknown_query'}
        else:
            rows = handler(**message.get('params', {}))
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
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                log.info('Conectado a %s', GATEWAY_URL)
                backoff = 1
                async for raw_message in ws:
                    await handle_message(ws, raw_message)
        except Exception as exc:
            log.warning('Conexión perdida (%s); reintento en %ss', exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(run())
