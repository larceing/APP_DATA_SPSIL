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
  - `Page` — una página/informe del sidebar (hoy solo "Stock"). `Department`
    agrupa usuarios y tiene un M2M a `Page` (todo el departamento ve esas
    páginas); `UserProfile.extra_pages` concede páginas sueltas a un usuario
    concreto además de las de su departamento (caso "Roger es de Almacén
    pero también lleva Logística"). Ver sección "Permisos por página".
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

## Permisos por página (Usuario)

Admin y Superadmin ven **todas** las páginas siempre (bypass en
`gateway/permissions.py::get_accessible_pages`). Para el rol Usuario, el
acceso a cada `Page` (hoy solo "Stock") se decide así:

1. **Por departamento**: en `/admin/gateway/department/`, cada `Department`
   tiene un M2M a `Page` — todo usuario con ese departamento asignado ve
   esas páginas.
2. **Suelto por usuario**: en `/admin/auth/user/<id>/change/`, la sección
   "User profile" (inline) tiene `extra_pages` — páginas concedidas solo a
   ese usuario, además de las de su departamento. Para el caso "Roger es de
   Almacén pero también lleva Logística": se le deja el departamento que
   corresponda y se le añade la página de Logística ahí, sin tocar el
   departamento de nadie más.

El permiso se aplica de verdad en las vistas (`@page_required('stock')`),
no solo se oculta el enlace del sidebar: entrar directo a `/gateway/stock/`
sin acceso da **403**, no solo lo esconde del menú.

Al desplegar este sistema (migración `gateway/0004_seed_stock_page.py`), se
apadrina automáticamente a los usuarios "Usuario" que ya existieran antes,
concediéndoles `extra_pages=[Stock]` — para que nadie se quede fuera en
silencio. Los usuarios nuevos que se creen después no tienen ninguna página
por defecto: hay que asignarles departamento o concesión suelta a mano.

## Interfaz

- **Sidebar izquierdo agrupado por rol** (`templates/base.html`): grupo
  "Almacén" → Stock (todos); grupo "Configuración" → reglas de exclusión
  (Admin/Superadmin); grupo "Administración" → enlaces a Usuarios/Nodos del
  admin de Django (solo Superadmin). Cada grupo se muestra u oculta según
  `request.user.is_staff`/`is_superuser` directamente en la plantilla.
- **Idioma (es/zh/en)**: selector en la cabecera. Usa un mecanismo **propio**
  (cookie `app_language` + `core/middleware.py` + `core/views.py::set_language`),
  **no** el `set_language`/`LocaleMiddleware` de Django — ese exige un
  catálogo de traducción compilado (gettext) por idioma, y aquí las
  traducciones viven en la tabla `UIString`, no en catálogos `.mo`. El tag
  `{% ui %}` (`core/templatetags/uistrings.py`) lee `request.app_language`.
- **Exportar a Excel**: botón en `/gateway/stock/` que descarga un `.xlsx`
  (`gateway/views.py::stock_export_view`, vía `openpyxl`) con el stock
  completo devuelto por el túnel (no respeta el filtro de búsqueda del
  navegador, que es solo una conveniencia visual).
- **Marca SPSIL**: colores en `static/css/variables.css`
  (`--color-brand-yellow`, `--color-brand-black`, `--color-primary` naranja).
  Tema siempre claro a propósito (pantallas de almacén). Logo: coloca el
  archivo en `static/img/spsil-logo.png` — la plantilla ya lo referencia
  (con `onerror` que lo oculta si aún no existe, sin romper el layout).
- **Modo almacén**: la pestaña Stock usa la clase `.warehouse-view` (texto
  y botones más grandes, pensado para pantallas táctiles de nave, no de
  oficina).

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

## Stock Tabla (sector Compras)

Segunda página real, réplica del informe "Control_Stock" de Power BI:
stock por almacén + histórico de ventas + categoría de proveedor + tamaño
de envase + desglose Picking/Almacenamiento, todo cruzado por artículo.

- `edge_agent/stock_tabla.py` — todo el cálculo: SQL Server
  (`dbo.VW_OFERTAS_STOCK_RAW` + `LINEOFER` con `RANK()` para mejores ventas)
  y MariaDB (`Hueco`/`TipoHueco`/`ArticuloEstipulado` para Picking/
  Almacenamiento y etiquetas físicas). Sin pandas a propósito: el volumen
  de artículos es modesto y los cruces se hacen con diccionarios normales.
- `SupplierCategory` (categoría 1-4 + organización de cada proveedor) sigue
  el mismo patrón que `ExclusionRule`: se importa **una vez** desde otro
  Google Sheet (`manage.py import_supplier_categories`) y se manda por el
  túnel en cada consulta — el agente no vuelve a tocar Google Sheets. A
  partir de esa carga inicial, se edita (añadir/editar/borrar) desde una
  sección propia en `/gateway/config/` — sin volver a tocar el Google Sheet
  ni el admin de Django. Cada fila se puede editar in-place (inputs con
  atributo `form="sc-save-<id>"`, ya que un `<form>` no puede anidar `<td>`
  de forma válida).
- Los umbrales de "Volumetría" (para clasificar PEQUEÑO/MEDIO/GRANDE/EXTRA)
  son constantes fijas en `edge_agent/stock_tabla.py::VOLUMETRIA`, no una
  consulta — si cambian, se edita ahí.
- La tabla se genera dinámicamente en el navegador a partir de las claves
  que devuelva cada fila (~40 columnas), sin cabeceras hardcodeadas.
- Acceso: página `Page(slug='stock-tabla', group_label='Compras')` — nadie
  la ve por defecto (a diferencia de "Stock", aquí no hubo que apadrinar a
  nadie porque es una página nueva). Se asigna por departamento
  (`/admin/gateway/department/`, ej. crear "Compras" y marcarle esta
  página) o suelta a un usuario en su perfil.

```
venv\Scripts\python.exe manage.py import_supplier_categories
```

## Añadir un segundo tipo de consulta

Ya hay dos ejemplos reales de cómo hacerlo (Stock y Stock Tabla): añade una
entrada a `QUERY_HANDLERS` en `edge_agent/agent.py`, una vista nueva en
`gateway/views.py` usando el helper compartido `_ask_gateway(query, params)`
(mismo `new_channel`/`send`/`receive` de siempre), una `Page` nueva (con su
`group_label` de sidebar) y su plantilla.

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
- No he podido probar `edge_agent/db.py` ni `edge_agent/stock_tabla.py`
  contra el MariaDB/SQL Server reales (son IPs privadas de tu LAN,
  `192.168.10.x`, inalcanzables desde aquí) — sí verificado: la lógica de
  cálculo de ambos (exclusión, multiplicadores, SIZE...) con datos
  simulados, la importación real de los dos Google Sheets (exclusión y
  categoría de proveedores), y el flujo completo túnel+roles+permisos con
  un agente de prueba. Falta la primera prueba real ya en equipo X con las
  credenciales/consultas de verdad — en particular, confirmar que las
  columnas exactas de `dbo.VW_OFERTAS_STOCK_RAW` coinciden con las que
  espera `_query_stock_raw()`.
- API externa de solo lectura — decidido dejarlo para después.
