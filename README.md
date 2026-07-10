# APP_DATA_SPSIL — Gateway de datos en tiempo real (estilo Power BI On-Premises Gateway)

Un usuario en la web (**servidor Y**, este repo) pulsa un botón ("ver stock
actual"). La web le pide el dato a una máquina de la red interna del cliente
(**equipo X**), que corre un contenedor Docker con acceso a las bases de
datos reales de negocio (MariaDB + SQL Server). Equipo X consulta, filtra y
devuelve el resultado fresco por el mismo túnel que él mismo abrió.

Igual que el Power BI On-Premises Gateway: **equipo X nunca abre puertos
entrantes**; siempre es él quien inicia la conexión saliente (WebSocket)
hacia el servidor Y.

## Stack

- Python 3.12, Django 4.2, Channels + Daphne (WebSocket/ASGI), whitenoise
- SQLite
- Sin frameworks JS externos — CSS propio con variables (`static/css/`)
- `edge_agent/`: cliente Python asyncio puro (`websockets`, `PyMySQL`,
  `python-tds`), sin Django

## Apps / carpetas

- `core` — textos de interfaz multi-idioma (`UIString` es/zh/en, tag `{% ui %}`)
- `gateway`:
  - `GatewayNode` — equipo X registrado + token (hasheado).
  - `ExclusionRule` — artículos/familias a excluir del stock, editable desde
    `/gateway/config/` (Admin/Superadmin). Se carga una vez desde el Google
    Sheet de control con `manage.py import_exclusion_rules`; a partir de ahí
    no se vuelve a leer Google Sheets en marcha.
  - `Department`/`UserProfile` — hueco estructural para cuando haga falta
    segmentar por departamento (no se usa todavía para filtrar nada).
  - El consumer WebSocket (`gateway/consumers.py`) y la vista que pide datos
    y espera respuesta (`gateway/views.py`).
- `edge_agent/` — el agente que corre en equipo X: se conecta al gateway,
  consulta MariaDB + SQL Server (`edge_agent/db.py`), aplica las reglas de
  exclusión que le llegan por el túnel, y responde.

## Roles

3 perfiles, sobre los flags nativos de Django (sin modelo de rol nuevo):

| Rol        | Flags                          | Puede                                             |
|------------|---------------------------------|----------------------------------------------------|
| Usuario    | ninguno                         | Ver `/gateway/stock/` (buscar + tabla + recargar)  |
| Admin      | `is_staff=True`                 | Todo lo de Usuario + `/gateway/config/` (incluir/excluir artículos o familias) |
| Superadmin | `is_staff=True` + `is_superuser=True` | Todo lo de Admin + crear/gestionar cuentas en `/admin/` |

Un Admin normal **no puede crear usuarios**: Django no da permisos `auth.*`
a un `is_staff` no-superusuario a menos que se los asignes a mano, así que
por construcción solo el superusuario puede dar de alta cuentas — no toques
los permisos de `auth` de los Admin si quieres mantener esta restricción.

## Cómo funciona el túnel

1. Equipo X (`edge_agent/agent.py`) abre un WebSocket hacia
   `wss://servidor-y/ws/gateway/<slug>/?token=...` y lo mantiene vivo con
   reconexión automática (backoff exponencial) si se cae.
2. `gateway/consumers.py` autentica el token contra `GatewayNode` y guarda
   el `channel_name` de esa conexión en `CONNECTED_NODES`.
3. Cuando un usuario pulsa el botón, `gateway/views.py` lee las
   `ExclusionRule` activas, crea un canal de respuesta efímero
   (`channel_layer.new_channel()`), le pide al consumer de ese nodo que
   reenvíe la consulta (con las reglas dentro) por el socket real, y espera
   la respuesta con `asyncio.wait_for(..., timeout=20)`.
4. El agente consulta MariaDB (stock) y SQL Server (familia), aplica las
   reglas de exclusión **en memoria** (no las guarda en disco, no vuelve a
   tocar Google Sheets) y responde por el mismo socket. El consumer reenvía
   la respuesta al canal efímero, la vista la recibe y la devuelve como JSON.

Si el nodo no está conectado, la vista responde **503 al instante** (no
espera). Si se cae a media consulta, responde **504** a los 20s (nunca se
cuelga indefinidamente).

## Setup local (sin Docker)

```
setup.bat
venv\Scripts\python.exe manage.py createsuperuser
```

En desarrollo, `manage.py runserver` ya sirve HTTP + WebSocket (requiere
`daphne` en `INSTALLED_APPS`, ya configurado). En producción se sirve con
`daphne` explícito vía Docker (ver más abajo) o `scripts\start_server.vbs`.

## Cargar la lista de exclusión (una sola vez)

```
set GOOGLE_SHEET_ID=1nzO_kGbkPnY8xi_OvglGTCl6kh83DMi8CZnLr-v-ru4
set GOOGLE_SHEET_TAB=Hoja 2
venv\Scripts\python.exe manage.py import_exclusion_rules
```

`GOOGLE_SHEET_TAB=Hoja 2` está **confirmado**: es la pestaña bien formada
(`CODART`/`FAMILIA` limpios); la otra pestaña del mismo Sheet tiene la
cabecera corrupta y no se usa. A partir de aquí, edita las reglas desde
`/gateway/config/`, no vuelvas a tocar el Google Sheet.

## Probar el flujo completo en local

1. `venv\Scripts\python.exe manage.py runserver`
2. En `/admin/`, crear un `GatewayNode` (nombre + slug). El token generado
   se muestra **una sola vez** en un mensaje flash — cópialo ya.
3. En otra terminal, en equipo X (necesita red hacia el MariaDB/SQL Server
   reales — no funciona fuera de esa LAN):
   ```
   pip install -r edge_agent/requirements.txt
   set GATEWAY_URL=ws://localhost:8000/ws/gateway/<slug>/
   set NODE_TOKEN=<token>
   set MARIADB_HOST=192.168.10.215
   set MARIADB_DATABASE=almacenmultiforte
   set MARIADB_USER=...
   set MARIADB_PASSWORD=...
   set ID_CENTRO=6
   set ID_ALMACEN=1
   set MSSQL_HOST=192.168.10.209
   set MSSQL_DATABASE=SG
   set MSSQL_USER=...
   set MSSQL_PASSWORD=...
   python edge_agent/agent.py
   ```
4. En el admin, la columna "Conectado" del `GatewayNode` pasa a Sí; el
   badge del header pasa a `online`.
5. Ir a `/gateway/stock/`, pulsar el botón: llegan las filas de stock ya
   filtradas.

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
- No he podido probar `edge_agent/db.py` contra el MariaDB/SQL Server
  reales (son IPs privadas de tu LAN, `192.168.10.x`, inalcanzables desde
  aquí) — sí verificado: la lógica de exclusión (por código y por familia)
  con datos simulados, la importación real desde el Google Sheet, y el
  flujo completo túnel+roles con un agente de prueba. Falta la primera
  prueba real ya en equipo X con las credenciales de verdad.
- API externa de solo lectura — decidido dejarlo para después.
