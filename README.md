# APP_DATA_SPSIL — Gateway de datos en tiempo real (estilo Power BI On-Premises Gateway)

Un usuario en la web (**servidor Y**, este repo) pulsa un botón ("ver stock
actual"). La web le pide el dato a una máquina de la red interna del cliente
(**equipo X**), que corre un contenedor Docker con acceso a la base de datos
real de negocio. Equipo X consulta su BD y devuelve el resultado fresco por
el mismo túnel que él mismo abrió.

Igual que el Power BI On-Premises Gateway: **equipo X nunca abre puertos
entrantes**; siempre es él quien inicia la conexión saliente (WebSocket)
hacia el servidor Y.

## Stack

- Python 3.12, Django 4.2, Channels + Daphne (WebSocket/ASGI), whitenoise
- SQLite
- Sin frameworks JS externos — CSS propio con variables (`static/css/`)
- `edge_agent/`: cliente Python asyncio puro (librería `websockets`), sin Django

## Apps / carpetas

- `core` — textos de interfaz multi-idioma (`UIString`, tag `{% ui %}`)
- `gateway` — `GatewayNode` (equipo X registrado + token), el consumer
  WebSocket (`gateway/consumers.py`) y la vista que pide datos y espera
  respuesta (`gateway/views.py`)
- `edge_agent/` — el agente que corre en equipo X: se conecta al gateway,
  resuelve consultas contra su BD (mock por ahora, `edge_agent/db.py`) y
  responde

## Cómo funciona el túnel

1. Equipo X (`edge_agent/agent.py`) abre un WebSocket hacia
   `wss://servidor-y/ws/gateway/<slug>/?token=...` y lo mantiene vivo con
   reconexión automática (backoff exponencial) si se cae.
2. `gateway/consumers.py` autentica el token contra `GatewayNode` y guarda
   el `channel_name` de esa conexión en `CONNECTED_NODES`.
3. Cuando un usuario pulsa el botón, `gateway/views.py` crea un canal de
   respuesta efímero (`channel_layer.new_channel()`), le pide al consumer
   de ese nodo que reenvíe la consulta por el socket real, y espera la
   respuesta con `asyncio.wait_for(..., timeout=10)`.
4. El agente responde por el mismo socket; el consumer reenvía la
   respuesta al canal efímero, la vista la recibe y la devuelve como JSON.

Si el nodo no está conectado, la vista responde **503 al instante** (no
espera). Si se cae a media consulta, responde **504** a los 10s (nunca se
cuelga indefinidamente).

## Setup local (sin Docker)

```
setup.bat
venv\Scripts\python.exe manage.py createsuperuser
```

En desarrollo, `manage.py runserver` ya sirve HTTP + WebSocket (requiere
`daphne` en `INSTALLED_APPS`, ya configurado). En producción se sirve con
`daphne` explícito vía Docker (ver más abajo) o `scripts\start_server.vbs`.

## Probar el flujo completo en local

1. `venv\Scripts\python.exe manage.py runserver`
2. En `/admin/`, crear un `GatewayNode` (nombre + slug). El token generado
   se muestra **una sola vez** en un mensaje flash — cópialo ya.
3. En otra terminal:
   ```
   pip install -r edge_agent/requirements.txt
   python edge_agent/seed_db.py
   set GATEWAY_URL=ws://localhost:8000/ws/gateway/<slug>/
   set NODE_TOKEN=<token>
   python edge_agent/agent.py
   ```
4. En el admin, la columna "Conectado" del `GatewayNode` pasa a Sí; el
   badge del header pasa a `online`.
5. Ir a `/gateway/stock/`, pulsar el botón: llegan las filas de la BD mock.

## Añadir un segundo tipo de consulta

No hace falta generalizar nada todavía: añade una entrada a
`QUERY_HANDLERS` en `edge_agent/agent.py` y una vista/URL/plantilla nueva
en `gateway/` reutilizando el mismo bloque `new_channel`/`send`/`receive`
de `gateway/views.py`.

## Despliegue con Docker

- **Servidor Y** (raíz del repo): `Dockerfile` + `docker-compose.server.yml`,
  se une a una red externa `proxy_default` (el proxy compartido del host
  —Traefik/nginx-proxy— que enruta por dominio vive fuera de este repo,
  igual que en `APP_CRM_V2`). El proxy debe soportar upgrade de WebSocket
  para el host de esta app.
- **Equipo X**: `edge_agent/Dockerfile` + `edge_agent/docker-compose.yml`,
  sin `ports:` — nunca escucha, siempre inicia la conexión saliente.
- Copia `.env.example` → `.env` en la raíz (servidor Y) y en `edge_agent/`
  (equipo X), y rellena los valores.

## Limitaciones conocidas

- `CHANNEL_LAYERS` usa `InMemoryChannelLayer`: los registros
  `CONNECTED_NODES`/`PENDING_REQUESTS` solo funcionan con **un único
  proceso** daphne sirviendo `spsil-web`. No escalar a varias réplicas sin
  antes migrar a Redis (`channels_redis`) y pasar `CONNECTED_NODES` a
  Channels Groups (`group_add`/`group_send`); `PENDING_REQUESTS` no
  necesita tocarse.
- El token del nodo viaja en el query string del WebSocket; mitigado por
  TLS (`wss://`) en el proxy compartido.
- V1 asume un único `GatewayNode` activo.
