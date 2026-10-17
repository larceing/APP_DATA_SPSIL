"""Orígenes de datos del agente, todos configurables por variables de entorno.

Un solo sitio donde se decide a qué IP/puerto/base de datos/hoja se conecta
el agente. Si cambia el punto de acceso a la red (otra VPN, otra IP del
servidor, otra copia de la BD), basta con tocar el `.env` y reiniciar el
contenedor: ninguna consulta lleva un host escrito a mano.

Orígenes:
- `a3`       SQL Server del ERP A3 (antes MSSQL_*; se siguen aceptando).
- `innertia` MariaDB del almacén Innertia (antes MARIADB_*; se siguen aceptando).
- Hojas de Google (`GSHEET_<CLAVE>`): el id de la hoja o una URL CSV completa.

`describir()` devuelve la configuración sin contraseñas, para enseñarla en
la página "Orígenes de datos" del portal; `comprobar()` hace un ping a cada
origen (SELECT 1 / descarga de la hoja).
"""

import csv
import datetime
import decimal
import io
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pymysql
import pytds

log = logging.getLogger('edge_agent')


def _env(*nombres, default=None):
    """Primer valor no vacío entre varias variables (nombre nuevo, nombre
    antiguo), para no romper los `.env` que ya están desplegados."""
    for nombre in nombres:
        valor = os.environ.get(nombre)
        if valor not in (None, ''):
            return valor
    return default


DB_TIMEOUT = int(_env('DB_TIMEOUT', default='120'))
DB_LOGIN_TIMEOUT = int(_env('DB_LOGIN_TIMEOUT', default='15'))
GSHEET_TIMEOUT = int(_env('GSHEET_TIMEOUT', default='30'))


def config_a3():
    return {
        'tipo': 'sqlserver',
        'host': _env('A3_HOST', 'MSSQL_HOST'),
        'puerto': int(_env('A3_PORT', 'MSSQL_PORT', default='1433')),
        'base_datos': _env('A3_DATABASE', 'MSSQL_DATABASE', default='SG'),
        'usuario': _env('A3_USER', 'MSSQL_USER'),
        'clave': _env('A3_PASSWORD', 'MSSQL_PASSWORD'),
    }


def config_innertia():
    return {
        'tipo': 'mariadb',
        'host': _env('INNERTIA_HOST', 'MARIADB_HOST'),
        'puerto': int(_env('INNERTIA_PORT', 'MARIADB_PORT', default='3306')),
        'base_datos': _env('INNERTIA_DATABASE', 'MARIADB_DATABASE', default='almacenmultiforte'),
        'usuario': _env('INNERTIA_USER', 'MARIADB_USER'),
        'clave': _env('INNERTIA_PASSWORD', 'MARIADB_PASSWORD'),
    }


# Hojas de Google que usaban los Power BI (mismos ids y pestañas), cada una
# sustituible con GSHEET_<CLAVE> (id o URL CSV) y GSHEET_<CLAVE>_HOJA.
GSHEETS = {
    'COMERCIALES': ('1tMpaWqwIWnRkNIMQ_b9S-JF6mmP6aDbhoSGbBOOYR_w', None),
    'FILTRO_COBROS': ('1V5QszuvHhPp3spdKrU5nrM1wpq-d3ndHUL7CxF-80jQ', 'Hoja 1'),
    'EXPEDICIONES': ('1cKQ-M82GseLK_El-i45kwtl6E1IXPij7fjnzWbBQNa4', 'Estado de las Expediciones'),
    'COBRO_TRANSPORTE': ('1jgta_zXrBTa8acCD7pDf3z3KF_5a8D3bY04NLVURcJc', 'Fichero Excel'),
    'PRECIOS_TRANSPORTE': ('1Rh7a6w9rkRg9xl9hlGarkCG1fk38lcyiDqx_sAhAduY', 'Sheet1'),
    'VENTAS_WEB': ('1w5GoGyE098DOaYtiKY2B1JWj6uakkCJLVQvwr9tacNo', 'Hoja 1'),
    'ZONA_COM': ('1DqrjyDvu6mEqwzlN8pgLw-KYSzGNQO6mwIGpmz1jBIw', 'Hoja 1'),
    'VOLUMEN_PACKAGING': ('1xHBpxIURY2BO8MsSc7qGoij1sfvH6CjpVHhKWL-M1iw', 'Hoja 1'),
    'PASILLOS': ('1NGDCONR9REnYEekEh2ctMWiVYP-DQ8QGUBBVgxZdMHE', 'Hoja 1'),
    'CATEGORIA_PROVEEDORES': ('1SG_zmnza0Jgp_Jb3v6uyTGpjjKM0mz7kxeDKNfCSkq0', 'Hoja 1'),
}


def config_gsheet(clave, hoja=None):
    id_defecto, hoja_defecto = GSHEETS[clave]
    origen = _env(f'GSHEET_{clave}', default=id_defecto)
    hoja = hoja or _env(f'GSHEET_{clave}_HOJA', default=hoja_defecto)
    if origen.startswith('http'):
        url = origen
    else:
        url = f'https://docs.google.com/spreadsheets/d/{origen}/gviz/tq?tqx=out:csv'
        if hoja:
            url += '&sheet=' + urllib.parse.quote(hoja)
    return {'tipo': 'gsheet', 'id': origen, 'hoja': hoja, 'url': url}


# --- Conexiones -----------------------------------------------------------

def conectar_a3():
    c = config_a3()
    return pytds.connect(
        server=c['host'], port=c['puerto'], database=c['base_datos'],
        user=c['usuario'], password=c['clave'],
        timeout=DB_TIMEOUT, login_timeout=DB_LOGIN_TIMEOUT,
    )


def conectar_innertia():
    c = config_innertia()
    return pymysql.connect(
        host=c['host'], port=c['puerto'], user=c['usuario'], password=c['clave'],
        database=c['base_datos'], connect_timeout=DB_LOGIN_TIMEOUT, read_timeout=DB_TIMEOUT,
    )


CONECTORES = {'a3': conectar_a3, 'innertia': conectar_innertia}


def valor_json(valor):
    """Fechas a ISO, Decimal a float y textos recortados: lo que viaja por el
    túnel tiene que ser JSON plano."""
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    if isinstance(valor, datetime.datetime):
        if valor.hour == valor.minute == valor.second == 0 and not valor.microsecond:
            return valor.date().isoformat()
        return valor.isoformat(sep=' ', timespec='seconds')
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, bytes):
        return valor.decode('utf-8', 'replace').strip()
    return valor


def consultar(origen, sql, parametros=None):
    """Ejecuta `sql` en el origen dado (`a3` o `innertia`) y devuelve una
    lista de diccionarios con valores ya aptos para JSON."""
    inicio = time.monotonic()
    conn = CONECTORES[origen]()
    try:
        cur = conn.cursor()
        # Sin parámetros, sin formateo: los LIKE '%...%' del SQL no deben
        # interpretarse como marcadores (pymysql formatea con % si recibe args).
        if parametros:
            cur.execute(sql, parametros)
        else:
            cur.execute(sql)
        columnas = [d[0] for d in cur.description]
        filas = [
            {col: valor_json(v) for col, v in zip(columnas, fila)}
            for fila in cur.fetchall()
        ]
    finally:
        conn.close()
    log.info('consulta %s: %s filas en %.1fs', origen, len(filas), time.monotonic() - inicio)
    return filas


# Hojas privadas: cuenta de servicio de Google (fichero JSON de la clave).
# Se comparte la hoja con el correo de la cuenta como Lector y el agente la
# lee con la API de Sheets; las hojas públicas siguen yendo por CSV directo.
GOOGLE_CREDENCIALES = _env('GOOGLE_CREDENCIALES')


def _leer_con_cuenta_servicio(clave, hoja):
    """CSV de una hoja privada leída con la cuenta de servicio (API de Sheets)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credenciales = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENCIALES, scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
    )
    credenciales.refresh(Request())
    c = config_gsheet(clave, hoja)
    rango = urllib.parse.quote(c['hoja'] or 'A:ZZ', safe='')
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{c['id']}/values/{rango}?valueRenderOption=FORMATTED_VALUE"
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {credenciales.token}'})
    with urllib.request.urlopen(req, timeout=GSHEET_TIMEOUT) as resp:
        valores = json.loads(resp.read().decode('utf-8')).get('values', [])
    salida = io.StringIO()
    csv.writer(salida).writerows(valores)
    return salida.getvalue()


def _descargar_gsheet(clave, hoja=None):
    """CSV de la hoja como texto. Si la hoja no es pública (401/403 o página
    de login) y hay GOOGLE_CREDENCIALES, se lee con la cuenta de servicio; si
    no, se lanza un error que dice qué hacer."""
    c = config_gsheet(clave, hoja)
    aviso = (f'La hoja {clave} no es pública: compártela con la cuenta de servicio del agente '
             f'(GOOGLE_CREDENCIALES), como "cualquiera con el enlace", o pon en GSHEET_{clave} '
             f'la URL de "Publicar en la web" en formato CSV')
    req = urllib.request.Request(c['url'], headers={'User-Agent': 'spsil-edge-agent'})
    try:
        with urllib.request.urlopen(req, timeout=GSHEET_TIMEOUT) as resp:
            texto = resp.read().decode('utf-8-sig', 'replace')
    except urllib.error.HTTPError as exc:
        if exc.code not in (401, 403):
            raise
        texto = '<'
    if texto.lstrip().startswith('<'):
        if GOOGLE_CREDENCIALES and not c['id'].startswith('http'):
            return _leer_con_cuenta_servicio(clave, hoja)
        raise RuntimeError(aviso)
    return texto


def leer_gsheet(clave, hoja=None):
    """Descarga una hoja de Google como CSV y la devuelve como lista de
    diccionarios (cabecera = primera fila)."""
    filas = list(csv.reader(io.StringIO(_descargar_gsheet(clave, hoja))))
    if not filas:
        return []
    cabecera = [h.strip() for h in filas[0]]
    return [
        {cabecera[i]: (v.strip() if isinstance(v, str) else v) for i, v in enumerate(fila) if i < len(cabecera)}
        for fila in filas[1:]
        if any((v or '').strip() for v in fila)
    ]


def leer_gsheet_filas(clave, hoja=None):
    """Igual que leer_gsheet pero sin interpretar cabecera (lista de listas),
    para hojas con varias filas de cabecera como la de precios de transporte."""
    return list(csv.reader(io.StringIO(_descargar_gsheet(clave, hoja))))


# --- Diagnóstico ------------------------------------------------------------

def describir():
    """Configuración efectiva, sin contraseñas."""
    salida = {}
    for nombre, funcion in (('a3', config_a3), ('innertia', config_innertia)):
        c = dict(funcion())
        c['clave'] = '***' if c.get('clave') else ''
        salida[nombre] = c
    for clave in GSHEETS:
        salida['gsheet:' + clave] = config_gsheet(clave)
    return salida


def comprobar():
    """Ping a cada origen. Devuelve {origen: {'ok': bool, 'ms': int, 'error': str}}."""
    resultado = {}
    for nombre, sql in (('a3', 'SELECT 1'), ('innertia', 'SELECT 1')):
        inicio = time.monotonic()
        try:
            conn = CONECTORES[nombre]()
            try:
                cur = conn.cursor()
                cur.execute(sql)
                cur.fetchall()
            finally:
                conn.close()
            resultado[nombre] = {'ok': True, 'ms': int((time.monotonic() - inicio) * 1000), 'error': None}
        except Exception as exc:  # noqa: BLE001 - el diagnóstico tiene que contar cualquier fallo
            resultado[nombre] = {'ok': False, 'ms': int((time.monotonic() - inicio) * 1000), 'error': str(exc)[:200]}
    for clave in GSHEETS:
        inicio = time.monotonic()
        try:
            leer_gsheet_filas(clave)
            resultado['gsheet:' + clave] = {'ok': True, 'ms': int((time.monotonic() - inicio) * 1000), 'error': None}
        except Exception as exc:  # noqa: BLE001
            resultado['gsheet:' + clave] = {'ok': False, 'ms': int((time.monotonic() - inicio) * 1000), 'error': str(exc)[:200]}
    return resultado
