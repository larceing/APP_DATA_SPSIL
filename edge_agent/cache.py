"""Caché en memoria para consultas pesadas, refrescada en segundo plano.

No es una capa de persistencia: guarda unos pocos miles de filas por
entrada, cabe cómodo en RAM y se recalcula sin problema si el agente se
reinicia. Pensada para que, cuando aparezcan más tablas pesadas además
de Stock Tabla, se registren con el mismo patrón sin rehacer nada.
"""

import asyncio
import datetime
import logging

log = logging.getLogger('edge_agent')

_STORE = {}


async def refresh_loop(name, compute_fn, interval_seconds):
    """Ejecuta compute_fn() en un hilo aparte (no bloquea la conexión
    WebSocket) cada interval_seconds, y guarda el resultado en _STORE[name].
    Un fallo en compute_fn no tumba el bucle: se registra y se reintenta
    en el siguiente ciclo, dejando mientras tanto el último dato válido
    disponible (o ninguno, si aún no ha corrido con éxito la primera vez).
    """
    loop = asyncio.get_running_loop()
    while True:
        inicio = loop.time()
        try:
            data = await loop.run_in_executor(None, compute_fn)
            _STORE[name] = {'data': data, 'updated_at': datetime.datetime.utcnow()}
            log.info('Caché %s actualizada: %d filas en %.1fs', name, len(data), loop.time() - inicio)
        except Exception:
            log.exception('Error refrescando caché %s (tras %.1fs)', name, loop.time() - inicio)
        await asyncio.sleep(interval_seconds)


def get(name):
    return _STORE.get(name)
