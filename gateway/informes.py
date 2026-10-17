"""Catálogo de páginas de informes (réplica web de Informe Susana, Informe
Cobros e Informe Almacén de Power BI).

Cada página es una descripción declarativa: qué conjunto de datos pide al
agente (edge_agent/informes.py), qué segmentaciones tiene y qué visuales
pinta. El navegador (static/js/informes.js) hace el filtrado y las medidas,
igual que Power BI con el modelo ya cargado.

Medidas (`medida`): {'agg': 'sum'|'count'|'distinct'|'avg'|'min'|'max', 'col': ...}
más estas, que replican medidas DAX concretas:
- 'pedidos_validos': pares cliente/día del tipo dado cuyo pedido anterior del
  mismo cliente (de cualquier tipo, dentro de los filtros) fue hace más de
  15 días — "Pedidos P/Y/Otros", "Total Ventas Válidas".
- 'ratio': medida `num` / medida `den`.
- 'participacion': la medida del grupo / la misma medida sin agrupar (% del total).
- 'suma': suma de varias medidas.
- 'top': valor de `dim` con la medida más alta ("Mejor Familia", "Representante con más ventas").
- 'rango_fechas': "aaaa/mm/dd a aaaa/mm/dd" de `col`.
Cualquier medida admite 'donde': {columna: valor | [valores]} para filtrar filas antes.

Formatos: 'eur', 'int', 'dec', 'pct', 'fecha', 'texto'.
"""

from django.utils.text import slugify

# Medidas reutilizadas
PEDIDOS_P = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA', 'donde': {'Tipo pedido': 'P'}}
PEDIDOS_Y = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA', 'donde': {'Tipo pedido': 'Y'}}
PEDIDOS_OTROS = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA', 'donde': {'Tipo pedido': 'Otro'}}
PEDIDOS_EXTRA = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA', 'donde': {'Tipo pedido': ['Y', 'Otro']}}
PEDIDOS_TOTALES = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}
VENTAS_VALIDAS = {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA', 'donde': {'Tipologia': {'distinto': 'Abono'}}}
PAQUETES_TOTALES = {'agg': 'sum', 'col': 'PaquetesVendidos', 'donde': {'Tipologia': {'distinto': 'Abono'}}}

F_REP = {'col': 'NOMREP', 'label': 'Representante'}
F_GRUPO = {'col': 'GRUPOS', 'label': 'Grupo'}
F_LISTADO = {'col': 'Listado', 'label': 'Listado'}


def _pagina(slug, nombre, grupo, origen, dataset, filtros, visuales, descripcion='', datasets_extra=None):
    return {
        'slug': slug, 'nombre': nombre, 'grupo': grupo, 'origen': origen,
        'dataset': dataset, 'datasets_extra': datasets_extra or [],
        'filtros': filtros, 'visuales': visuales, 'descripcion': descripcion,
    }


PAGINAS = [
    # ------------------------------------------------------------------ COBROS
    _pagina(
        'cobros-clientes', 'Cobros clientes', 'Cobros', 'Informe Cobros · Cobros Clientes', 'cobros_clientes',
        descripcion='Deuda pendiente por cliente (VW_COBROS) sin reembolsos ni los documentos de pago excluidos en la hoja FILTRO.',
        filtros=[F_REP, {'col': 'COD-CLIENTE', 'label': 'Cliente'}, {'col': 'FECHAFACTURA', 'label': 'Fecha factura', 'tipo': 'fechas'},
                 F_GRUPO, {'col': 'Documento de pago', 'label': 'Documento de pago'},
                 {'col': 'Nº PEDIDO WEB', 'label': 'Nº pedido web', 'tipo': 'texto'},
                 {'col': 'Con observaciones', 'label': 'Con observaciones'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Nº de deudores', 'medida': {'agg': 'distinct', 'col': 'CODCLI'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Deuda', 'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Deuda sin observaciones', 'medida': {'agg': 'sum', 'col': 'Importe', 'donde': {'Con observaciones': 'NO'}}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Media días de adeudo', 'medida': {'agg': 'avg', 'col': 'Días de adeudo'}, 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Deuda por representante', 'dim': 'NOMREP', 'medidas': [{'label': 'Deuda', 'agg': 'sum', 'col': 'Importe'}], 'formato': 'eur', 'top': 25},
            {'tipo': 'tarta', 'titulo': 'Deuda por documento de pago', 'dim': 'Documento de pago', 'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'tabla', 'titulo': 'Detalle de cobros', 'ancho': 'completo', 'orden': [('Días de adeudo', True)], 'columnas': [
                {'col': 'CODREP_NORM', 'label': 'Rep.'}, {'col': 'Documento de pago'}, {'col': 'Documento de pago - Tr', 'label': 'Doc. pago (中文)'},
                {'col': 'CODCLI'}, {'col': 'NOMCLI', 'label': 'Cliente'},
                {'col': 'Días de adeudo', 'formato': 'int', 'semaforo': [[60, 'rojo'], [30, 'ambar']]},
                {'col': 'FECHAFACTURA', 'label': 'Fecha factura', 'formato': 'fecha'}, {'col': 'FECHAVTO', 'label': 'Vencimiento', 'formato': 'fecha'},
                {'col': 'Importe', 'formato': 'eur'}, {'col': 'Suma Importe Por Cliente', 'label': 'Deuda cliente', 'formato': 'eur'},
                {'col': 'Importe Total Pedido', 'formato': 'eur'}, {'col': 'Nº PEDIDO WEB'}, {'col': 'DOCUFACTURA', 'label': 'Factura'},
                {'col': 'Dirección'}, {'col': 'SW3_MULTIFORTE_OBSERVACIONES', 'label': 'Observaciones'},
            ]},
        ],
    ),
    _pagina(
        'facturas-clientes', 'Facturas clientes', 'Cobros', 'Informe Cobros · Facturas Clientes', 'facturas_clientes',
        descripcion='Facturas de venta con su cobro (VW_FACTURACION).',
        filtros=[F_REP, {'col': 'COD-CLIENTE', 'label': 'Cliente'}, {'col': 'Fecha Factura', 'label': 'Fecha factura', 'tipo': 'fechas', 'defecto': 'anio'},
                 F_GRUPO, {'col': 'DocumentoPago', 'label': 'Documento de pago'}, {'col': 'Nº PEDIDO WEB', 'label': 'Nº pedido web', 'tipo': 'texto'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Importe total', 'medida': {'agg': 'sum', 'col': 'Importe Factura'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Importe cobrado', 'medida': {'agg': 'sum', 'col': 'ImporteCobrado'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Nº de facturas', 'medida': {'agg': 'distinct', 'col': 'IDFACV'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Media importe / factura', 'medida': {'agg': 'ratio', 'num': {'agg': 'sum', 'col': 'Importe Factura'}, 'den': {'agg': 'distinct', 'col': 'IDFACV'}}, 'formato': 'eur'},
            {'tipo': 'columnas', 'titulo': 'Facturación por mes', 'dim': 'Fecha Factura', 'granularidad': 'mes', 'medidas': [
                {'label': 'Facturado', 'agg': 'sum', 'col': 'Importe Factura'}, {'label': 'Cobrado', 'agg': 'sum', 'col': 'ImporteCobrado'}], 'formato': 'eur'},
            {'tipo': 'barras', 'titulo': 'Facturación por representante', 'dim': 'NOMREP', 'medidas': [{'label': 'Facturado', 'agg': 'sum', 'col': 'Importe Factura'}], 'formato': 'eur', 'top': 25},
            {'tipo': 'tabla', 'titulo': 'Facturas', 'ancho': 'completo', 'orden': [('Fecha Factura', True)], 'columnas': [
                {'col': 'CODCLI'}, {'col': 'ClienteFacturado', 'label': 'Cliente facturado'}, {'col': 'CODCLIFAC', 'label': 'Cód. cliente fact.'},
                {'col': 'ClientePedido', 'label': 'Cliente pedido'}, {'col': 'CODREP_NORM', 'label': 'Rep.'}, {'col': 'DocumentoFactura', 'label': 'Factura'},
                {'col': 'Fecha Factura', 'formato': 'fecha'}, {'col': 'FechaCobro', 'label': 'Fecha cobro', 'formato': 'fecha'},
                {'col': 'FechaVencimiento', 'label': 'Vencimiento', 'formato': 'fecha'}, {'col': 'Importe Factura', 'formato': 'eur'},
                {'col': 'ImporteCobrado', 'label': 'Cobrado', 'formato': 'eur'}, {'col': 'Nº PEDIDO WEB'},
            ]},
        ],
    ),
    _pagina(
        'resumen-pedidos-web', 'Resumen pedidos web', 'Cobros', 'Informe Cobros · Resumen Pedidos Web', 'cobros_clientes',
        descripcion='Cobros agrupados por pedido web: cuántas líneas de cobro tiene cada pedido.',
        filtros=[{'col': 'Nº PEDIDO WEB', 'label': 'Nº pedido web', 'tipo': 'texto'}, {'col': 'CODCLI', 'label': 'Cliente'}, {'col': 'CODREP_NORM', 'label': 'Representante'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pedidos web', 'medida': {'agg': 'distinct', 'col': 'Nº PEDIDO WEB'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos con varios cobros', 'medida': {'agg': 'distinct', 'col': 'Nº PEDIDO WEB', 'donde': {'Repeticiones Nº Pedido Web': {'mayor': 1}}}, 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Cobros por pedido web', 'ancho': 'completo', 'orden': [('Repeticiones Nº Pedido Web', True)], 'columnas': [
                {'col': 'CODCLI'}, {'col': 'NOMCLI', 'label': 'Cliente'}, {'col': 'NUMDOC', 'label': 'Nº doc.'}, {'col': 'CODREP_NORM', 'label': 'Rep.'},
                {'col': 'Importe', 'formato': 'eur'}, {'col': 'Nº PEDIDO WEB'}, {'col': 'Repeticiones Nº Pedido Web', 'label': 'Repeticiones', 'formato': 'int'},
            ]},
        ],
    ),

    # ----------------------------------------------------------------- PEDIDOS
    _pagina(
        'pedidos-diarios', 'Pedidos diarios', 'Pedidos', 'Informe Cobros · Pedidos Diarios', 'pedidos_diarios',
        descripcion='Pedidos válidos (un cliente cuenta de nuevo si han pasado más de 15 días desde su pedido anterior) por tipo: P (web P), Y (web Y) y Otros.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': '30d'}, {'col': 'CODREP_NORM', 'label': 'Representante'},
                 {'col': 'CODCLI', 'label': 'Cliente'}, F_GRUPO, F_LISTADO],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pedidos totales', 'medida': PEDIDOS_TOTALES, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos P', 'medida': PEDIDOS_P, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos Y', 'medida': PEDIDOS_Y, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos otros', 'medida': PEDIDOS_OTROS, 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Cronología de pedidos', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'dia', 'apilado': True,
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_Y, label='Y'), dict(PEDIDOS_OTROS, label='Otros')], 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Por fecha', 'dims': ['FECHA'], 'orden': [('FECHA', True)],
             'medidas': [dict(PEDIDOS_OTROS, label='Otros'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_Y, label='Y')], 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Por representante', 'dims': ['CODREP_NORM', 'NOMREP'],
             'medidas': [dict(PEDIDOS_OTROS, label='Otros'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_Y, label='Y')], 'formato': 'int'},
        ],
    ),
    _pagina(
        'pedidos-general', 'Pedidos por grupo', 'Pedidos', 'Informe Cobros · Pedidos General', 'pedidos_diarios',
        descripcion='Pedidos válidos por representante de los comerciales del listado, separados por grupo.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'mes'}, F_GRUPO, {'col': 'Listado', 'label': 'Listado', 'defecto': ['LISTADO']}],
        visuales=[
            {'tipo': 'columnas', 'titulo': 'Pedidos por representante (grupo A)', 'ancho': 'completo', 'dim': 'NOMREP', 'apilado': True, 'donde': {'GRUPOS': 'A'},
             'medidas': [dict(PEDIDOS_Y, label='Y'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_OTROS, label='Otros')], 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Pedidos por representante (resto de grupos)', 'ancho': 'completo', 'dim': 'NOMREP', 'apilado': True, 'donde': {'GRUPOS': {'distinto': 'A'}},
             'medidas': [dict(PEDIDOS_Y, label='Y'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_OTROS, label='Otros')], 'formato': 'int'},
        ],
    ),
    _pagina(
        'pedidos-grandes', 'Pedidos de 500 € o más', 'Pedidos', 'Informe Susana · Pedidos Diarios', 'pedidos_grandes',
        descripcion='Pedidos de 500 € o más, con el representante de la última factura del cliente. Objetivo: 2 pedidos por representante y día.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'mes'}, {'col': 'CODREP_NORM', 'label': 'Representante'},
                 {'col': 'CODCLI', 'label': 'Cliente'}, F_GRUPO],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pedidos (cliente total)', 'medida': PEDIDOS_TOTALES, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos P', 'medida': PEDIDOS_P, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos extra (Y + otros)', 'medida': PEDIDOS_EXTRA, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Objetivo (2 × rep. × día)', 'medida': {'agg': 'objetivo_pedidos', 'fecha': 'FECHA', 'rep': 'CODREP_NORM', 'por': 2}, 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Pedidos por día', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'dia', 'apilado': True,
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Por representante', 'dims': ['CODREP_NORM', 'NOMREP'],
             'medidas': [dict(PEDIDOS_EXTRA, label='Extra'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_TOTALES, label='Total')], 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Por fecha', 'dims': ['FECHA'], 'orden': [('FECHA', True)],
             'medidas': [dict(PEDIDOS_EXTRA, label='Extra'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_TOTALES, label='Total')], 'formato': 'int'},
        ],
    ),
    _pagina(
        'pedidos-ventas', 'Pedidos y paquetes', 'Pedidos', 'Informe Susana · Pedidos Ventas', 'pedidos_grandes',
        descripcion='Pedidos de 500 € o más por tipología y paquetes vendidos por familia.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'mes'}, F_GRUPO, {'col': 'CODREP_NORM', 'label': 'Representante'},
                 {'col': 'Tipología Avanzada', 'label': 'Tipología'}, {'col': 'Listado', 'label': 'Listado', 'defecto': ['LISTADO']}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pedidos totales', 'medida': PEDIDOS_TOTALES, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Paquetes vendidos', 'medida': {'agg': 'sum', 'col': 'Paquetes Vendidos'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Media paquetes por venta', 'medida': {'agg': 'ratio', 'num': {'agg': 'sum', 'col': 'Paquetes Vendidos'}, 'den': PEDIDOS_TOTALES}, 'formato': 'dec'},
            {'tipo': 'columnas', 'titulo': 'Pedidos por grupo', 'dim': 'GRUPOS', 'apilado': True,
             'medidas': [dict(PEDIDOS_Y, label='Y'), dict(PEDIDOS_P, label='P'), dict(PEDIDOS_OTROS, label='Otros')], 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Pedidos por día y tipología', 'dim': 'FECHA', 'granularidad': 'dia', 'apilado': True,
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Paquetes vendidos por familia', 'dim': 'Familia', 'medidas': [{'label': 'Paquetes', 'agg': 'sum', 'col': 'Paquetes Vendidos'}], 'formato': 'int', 'top': 20},
            {'tipo': 'barras', 'titulo': '% de paquetes por familia', 'dim': 'Familia', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': {'agg': 'sum', 'col': 'Paquetes Vendidos'}}], 'formato': 'pct', 'top': 20},
            {'tipo': 'barras', 'titulo': 'Pedidos por familia', 'dim': 'Familia', 'medidas': [dict(PEDIDOS_TOTALES, label='Pedidos')], 'formato': 'int', 'top': 20},
        ],
    ),
    _pagina(
        'pedidos-hoy', 'Pedidos de hoy', 'Pedidos', 'Informe Susana · Pedidos hoy', 'pedidos_grandes',
        descripcion='Pedidos P y extra del día por grupo y por representante (comerciales del listado).',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'hoy'}, {'col': 'Listado', 'label': 'Listado', 'defecto': ['LISTADO']}],
        visuales=[
            {'tipo': 'columnas', 'titulo': 'Por grupo', 'dim': 'GRUPOS', 'apilado': True, 'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Grupo A por representante', 'dim': 'NOMREP', 'apilado': True, 'donde': {'GRUPOS': 'A'},
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Grupo B por representante', 'dim': 'NOMREP', 'apilado': True, 'donde': {'GRUPOS': 'B'},
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Resto de grupos por representante', 'dim': 'NOMREP', 'apilado': True, 'donde': {'GRUPOS': {'fuera': ['A', 'B']}},
             'medidas': [dict(PEDIDOS_P, label='P'), dict(PEDIDOS_EXTRA, label='Extra')], 'formato': 'int'},
        ],
    ),
    _pagina(
        'clientes-ritmo', 'Clientes: ritmo de pedidos', 'Pedidos', 'Informe Susana · Hoja Clientes Pedidos Mayores', 'pedidos_clientes',
        descripcion='Pedidos e importes por cliente en los últimos cuatro años y su ritmo de compra (VW_PEDIDOS_CLIENTES).',
        filtros=[{'col': 'CODCLI', 'label': 'Cliente'}, {'col': 'REPRESENTANTE', 'label': 'Representante'}, {'col': 'NOMPROVI', 'label': 'Provincia'},
                 {'col': 'NOMCLI', 'label': 'Nombre', 'tipo': 'texto'}, {'col': 'POBFISCAL', 'label': 'Población'}, {'col': 'ESTADO_RITMO', 'label': 'Ritmo'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Clientes', 'medida': {'agg': 'distinct', 'col': 'CODCLI'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Ritmo bueno', 'medida': {'agg': 'distinct', 'col': 'CODCLI', 'donde': {'ESTADO_RITMO': 'RITMO BUENO'}}, 'formato': 'int', 'clase': 'verde'},
            {'tipo': 'kpi', 'titulo': 'Ritmo justo', 'medida': {'agg': 'distinct', 'col': 'CODCLI', 'donde': {'ESTADO_RITMO': 'RITMO JUSTO'}}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Ritmo algo bajo', 'medida': {'agg': 'distinct', 'col': 'CODCLI', 'donde': {'ESTADO_RITMO': 'RITMO ALGO BAJO'}}, 'formato': 'int', 'clase': 'ambar'},
            {'tipo': 'kpi', 'titulo': 'Ritmo muy bajo', 'medida': {'agg': 'distinct', 'col': 'CODCLI', 'donde': {'ESTADO_RITMO': 'RITMO MUY BAJO'}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'kpi', 'titulo': 'Sin actividad', 'medida': {'agg': 'distinct', 'col': 'CODCLI', 'donde': {'ESTADO_RITMO': 'SIN ACTIVIDAD'}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Clientes', 'ancho': 'completo', 'orden': [('IMPORTE_TOTAL_{Y0}', True)], 'columnas': [
                {'col': 'CODCLI'}, {'col': 'NOMCLI', 'label': 'Cliente'}, {'col': 'NOMPROVI', 'label': 'Provincia'}, {'col': 'REPRESENTANTE', 'label': 'Rep.'},
                {'col': 'ESTADO_RITMO', 'label': 'Ritmo'}, {'col': 'SKU_DISTINTOS_{Y0}', 'label': 'SKU distintos {Y0}', 'formato': 'int'},
                {'col': 'SKU / PEDIDOS', 'formato': 'dec'}, {'col': 'TOTAL_PEDIDOS_{Y0}', 'label': 'Pedidos {Y0}', 'formato': 'int'},
                {'col': 'IMPORTE_MEDIO_{Y0}', 'label': 'Importe medio {Y0}', 'formato': 'eur'}, {'col': 'IMPORTE_TOTAL_{Y0}', 'label': 'Importe {Y0}', 'formato': 'eur'},
                {'col': 'UltimaPedido', 'label': 'Último pedido', 'formato': 'fecha'},
                {'col': 'Dias_Transcurridos', 'label': 'Días sin pedir', 'formato': 'int', 'semaforo': [[90, 'rojo'], [45, 'ambar']]},
                {'col': 'IMPORTE_SUBIDA_BAJADA_{Y1}_{Y0}', 'label': 'Subida/bajada {Y1}-{Y0}', 'formato': 'eur', 'signo': True},
                {'col': 'TOTAL_PEDIDOS_{Y1}', 'label': 'Pedidos {Y1}', 'formato': 'int'}, {'col': 'IMPORTE_TOTAL_{Y1}', 'label': 'Importe {Y1}', 'formato': 'eur'},
                {'col': 'TOTAL_PEDIDOS_{Y2}', 'label': 'Pedidos {Y2}', 'formato': 'int'}, {'col': 'IMPORTE_TOTAL_{Y2}', 'label': 'Importe {Y2}', 'formato': 'eur'},
                {'col': 'TOTAL_PEDIDOS_{Y3}', 'label': 'Pedidos {Y3}', 'formato': 'int'}, {'col': 'IMPORTE_TOTAL_{Y3}', 'label': 'Importe {Y3}', 'formato': 'eur'},
                {'col': 'POBFISCAL', 'label': 'Población'}, {'col': 'DIRFISCAL', 'label': 'Dirección'}, {'col': 'Telefonos Cliente', 'label': 'Teléfonos'},
            ]},
        ],
    ),
    _pagina(
        'representantes-ranking', 'Ranking de representantes', 'Pedidos', 'Informe Cobros · Representantes Rankings', 'ofertas_representantes',
        descripcion='Clientes distintos con oferta por representante del listado en el periodo elegido.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'mes'}, {'col': 'Nombre - COD', 'label': 'Representante'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Periodo', 'medida': {'agg': 'rango_fechas', 'col': 'FECHA'}, 'formato': 'texto'},
            {'tipo': 'kpi', 'titulo': 'Clientes distintos', 'medida': {'agg': 'distinct', 'col': 'CODCLI'}, 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Ranking por clientes distintos', 'dims': ['Nombre - COD'], 'ranking': True, 'orden': [('Clientes', True)],
             'medidas': [{'label': 'Clientes', 'agg': 'distinct', 'col': 'CODCLI'}, {'label': 'Clientes por mes (suma)', 'agg': 'distinct_por_mes', 'col': 'CODCLI', 'fecha': 'FECHA'},
                         {'label': 'Importe ofertas', 'agg': 'sum', 'col': 'TOTDOC', 'formato': 'eur'}], 'formato': 'int'},
        ],
    ),

    # ------------------------------------------------------------------ VENTAS
    _pagina(
        'ventas-visual', 'Ventas visual', 'Ventas', 'Informe Susana · Ventas Visual', 'ventas_familia_detalle',
        descripcion='Ventas válidas (cliente/día, más de 15 días desde la anterior) e importes por familia; incluye abonos como tipología aparte.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'anio'}, {'col': 'NOMREP', 'label': 'Representante'},
                 {'col': 'CODCLI - NOMCLI', 'label': 'Cliente'}, {'col': 'Familia', 'label': 'Familia'}, {'col': 'CODART', 'label': 'Artículo'},
                 {'col': 'Familia Descuento', 'label': 'Familia descuento'}, {'col': 'Código Proveedor', 'label': 'Proveedor'},
                 {'col': 'REPRESENTANTE LISTADO', 'label': 'Listado'}, {'col': 'Tipologia', 'label': 'Tipología'}, F_GRUPO],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Ventas válidas', 'medida': VENTAS_VALIDAS, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Importe total', 'medida': {'agg': 'sum', 'col': 'BASEMONEDAMASIVA'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Importe sin abonos', 'medida': {'agg': 'sum', 'col': 'BASEMONEDAMASIVA', 'donde': {'Tipologia': {'distinto': 'Abono'}}}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Importe abonado', 'medida': {'agg': 'sum', 'col': 'BASEMONEDAMASIVA', 'donde': {'Tipologia': 'Abono'}}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Clientes', 'medida': {'agg': 'distinct', 'col': 'CODCLI'}, 'formato': 'int'},
            {'tipo': 'columnas', 'titulo': 'Ventas válidas por mes y tipología', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'mes', 'series': 'Tipologia',
             'medidas': [{'label': 'Ventas', 'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}], 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Ventas válidas por familia', 'dim': 'Familia', 'medidas': [dict(VENTAS_VALIDAS, label='Ventas')], 'formato': 'int', 'top': 25},
            {'tipo': 'barras', 'titulo': '% participación por familia', 'dim': 'Familia', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': VENTAS_VALIDAS}], 'formato': 'pct', 'top': 25},
            {'tipo': 'barras', 'titulo': 'Ventas válidas por familia descuento', 'dim': 'Familia Descuento', 'medidas': [dict(VENTAS_VALIDAS, label='Ventas')], 'formato': 'int', 'top': 25},
            {'tipo': 'barras', 'titulo': '% participación por familia descuento', 'dim': 'Familia Descuento', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': VENTAS_VALIDAS}], 'formato': 'pct', 'top': 25},
            {'tipo': 'resumen', 'titulo': 'Por artículo y representante', 'dims': ['CODART', 'NOMREP'], 'orden': [('Importe', True)], 'ancho': 'completo',
             'medidas': [dict(VENTAS_VALIDAS, label='Ventas'), {'label': 'Paquetes', 'agg': 'sum', 'col': 'PaquetesVendidos'},
                         {'label': 'Importe', 'agg': 'sum', 'col': 'BASEMONEDAMASIVA', 'formato': 'eur'}], 'formato': 'int'},
            {'tipo': 'resumen', 'titulo': 'Por familia y cliente', 'dims': ['Familia', 'Familia Descuento', 'CODCLI - NOMCLI', 'NOMREP'], 'orden': [('Importe', True)], 'ancho': 'completo',
             'medidas': [dict(VENTAS_VALIDAS, label='Ventas'), {'label': 'Paquetes', 'agg': 'sum', 'col': 'PaquetesVendidos'},
                         {'label': 'Importe', 'agg': 'sum', 'col': 'BASEMONEDAMASIVA', 'formato': 'eur'}], 'formato': 'int'},
        ],
    ),
    _pagina(
        'ventas-paquetes', 'Ventas en paquetes', 'Ventas', 'Informe Susana · Ventas Paquetes', 'ventas_familia_detalle',
        descripcion='Paquetes vendidos (sin abonos) por fecha y familia.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'anio'}, {'col': 'Familia', 'label': 'Familia'}, {'col': 'CODART', 'label': 'Artículo'},
                 {'col': 'NOMREP', 'label': 'Representante'}, {'col': 'CODCLI - NOMCLI', 'label': 'Cliente'}, F_GRUPO,
                 {'col': 'REPRESENTANTE LISTADO', 'label': 'Listado', 'defecto': ['LISTADO']}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Paquetes totales', 'medida': PAQUETES_TOTALES, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Mejor familia (unidades)', 'medida': {'agg': 'top', 'dim': 'Familia', 'medida': {'agg': 'sum', 'col': 'UNIDADES'}}, 'formato': 'texto'},
            {'tipo': 'columnas', 'titulo': 'Paquetes por mes', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'mes', 'medidas': [dict(PAQUETES_TOTALES, label='Paquetes')], 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Paquetes por familia', 'dim': 'Familia', 'medidas': [dict(PAQUETES_TOTALES, label='Paquetes')], 'formato': 'int', 'top': 25},
            {'tipo': 'barras', 'titulo': '% de paquetes por familia', 'dim': 'Familia', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': PAQUETES_TOTALES}], 'formato': 'pct', 'top': 25},
        ],
    ),
    _pagina(
        'tabla-familias', 'Ventas por familia', 'Ventas', 'Informe Cobros · Tabla Familias', 'ventas_familia',
        descripcion='Importe con IVA de las ofertas de venta por familia, representante y mes.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'Representante', 'label': 'Representante'},
                 {'col': 'CODCLI - NOMCLI', 'label': 'Cliente'}, {'col': 'Familia', 'label': 'Familia'}, {'col': 'Semana', 'label': 'Semana'},
                 {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Código Proveedor', 'label': 'Proveedor'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Importe', 'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Unidades', 'medida': {'agg': 'sum', 'col': 'UNIDADES'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Paquetes', 'medida': {'agg': 'sum', 'col': 'PaquetesVendidos'}, 'formato': 'int'},
            {'tipo': 'matriz', 'titulo': 'Importe por familia y representante', 'ancho': 'completo', 'filas': 'Familia', 'columnas': 'Representante',
             'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'matriz', 'titulo': 'Importe por familia y mes', 'ancho': 'completo', 'filas': 'Familia', 'columnas': 'FECHA', 'granularidad': 'mes',
             'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
        ],
    ),
    _pagina(
        'ventas-cobros', 'Ventas por familia (visual)', 'Ventas', 'Informe Cobros · Ventas Visual', 'ventas_familia',
        descripcion='Ventas válidas, unidades y paquetes por familia y artículo.',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'CODCLI - NOMCLI', 'label': 'Cliente'}, {'col': 'Familia', 'label': 'Familia'},
                 {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Representante', 'label': 'Representante'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Ventas válidas', 'medida': {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Unidades', 'medida': {'agg': 'sum', 'col': 'UNIDADES'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Paquetes', 'medida': {'agg': 'sum', 'col': 'PaquetesVendidos'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Representante con más ventas', 'medida': {'agg': 'top', 'dim': 'NOMREP', 'medida': {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}}, 'formato': 'texto'},
            {'tipo': 'columnas', 'titulo': 'Ventas válidas por día', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'dia',
             'medidas': [{'label': 'Ventas', 'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}], 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Ventas válidas por familia', 'dim': 'Familia', 'medidas': [{'label': 'Ventas', 'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}], 'formato': 'int', 'top': 25},
            {'tipo': 'barras', 'titulo': '% participación por familia', 'dim': 'Familia', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': {'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}}], 'formato': 'pct', 'top': 25},
            {'tipo': 'resumen', 'titulo': 'Por artículo', 'dims': ['CODART'], 'orden': [('Unidades', True)],
             'medidas': [{'label': 'Ventas', 'agg': 'pedidos_validos', 'cliente': 'CODCLI', 'fecha': 'FECHA'}, {'label': 'Unidades', 'agg': 'sum', 'col': 'UNIDADES'}], 'formato': 'int'},
        ],
    ),
    _pagina(
        'ofertas-familia', 'Ofertas por familia', 'Ventas', 'Informe Susana · OFERTAS FAMILIA', 'ofertas_familia',
        descripcion='SKU distintos y peso de cada familia por cliente en las ofertas desde el año pasado (VW_OFERTAS_FAMILIA).',
        filtros=[{'col': 'Fecha', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'CODCLI', 'label': 'Cliente', 'tipo': 'texto'}, {'col': 'Familia', 'label': 'Familia'},
                 {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Codigo_Proveedor', 'label': 'Proveedor'}, {'col': 'Tipo_Comercial', 'label': 'Grupo'},
                 {'col': 'Listado', 'label': 'Listado'}, {'col': 'Comercial', 'label': 'Comercial'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Importe', 'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'SKU distintos', 'medida': {'agg': 'distinct', 'col': 'CODART'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Clientes', 'medida': {'agg': 'distinct', 'col': 'CODCLI'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Paquetes', 'medida': {'agg': 'sum', 'col': 'Paquetes'}, 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Importe por familia descuento', 'dim': 'Familia_Descuento', 'medidas': [{'label': 'Importe', 'agg': 'sum', 'col': 'Importe'}], 'formato': 'eur', 'top': 25},
            {'tipo': 'barras', 'titulo': '% de importe por familia', 'dim': 'Familia', 'medidas': [{'label': '%', 'agg': 'participacion', 'medida': {'agg': 'sum', 'col': 'Importe'}}], 'formato': 'pct', 'top': 25},
            {'tipo': 'resumen', 'titulo': 'Familia por cliente', 'ancho': 'completo', 'dims': ['Familia', 'Comercial', 'CODCLI', 'Nombre_Cliente', 'DIRCLI1', 'POBCLI'],
             'orden': [('SKU', True)], 'medidas': [{'label': 'SKU', 'agg': 'distinct', 'col': 'CODART'},
                                                   {'label': '% SKU del cliente', 'agg': 'participacion', 'medida': {'agg': 'distinct', 'col': 'CODART'}, 'respecto': ['CODCLI'], 'formato': 'pct'},
                                                   {'label': 'Importe', 'agg': 'sum', 'col': 'Importe', 'formato': 'eur'}], 'formato': 'int'},
        ],
    ),
    _pagina(
        'historico-representantes', 'Histórico por comercial', 'Ventas', 'Informe Susana · Detalle Venta', 'historico_representantes',
        descripcion='Importes de facturas, pedidos, albaranes y ofertas por comercial (VW_RESUMEN_COMERCIAL_TOTDOC).',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'mes'}, {'col': 'NOMREP', 'label': 'Comercial'}, F_GRUPO],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Facturado', 'medida': {'agg': 'sum', 'col': 'IMP.FAC'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Pedidos', 'medida': {'agg': 'sum', 'col': 'IMP.PED'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Albaranes', 'medida': {'agg': 'sum', 'col': 'IMP.ALB'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Ofertas', 'medida': {'agg': 'sum', 'col': 'IMP.OFE'}, 'formato': 'eur'},
            {'tipo': 'columnas', 'titulo': 'Total por mes', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'mes', 'apilado': True, 'medidas': [
                {'label': 'Facturas', 'agg': 'sum', 'col': 'IMP.FAC'}, {'label': 'Pedidos', 'agg': 'sum', 'col': 'IMP.PED'},
                {'label': 'Albaranes', 'agg': 'sum', 'col': 'IMP.ALB'}, {'label': 'Ofertas', 'agg': 'sum', 'col': 'IMP.OFE'}], 'formato': 'eur'},
            {'tipo': 'resumen', 'titulo': 'Por comercial', 'ancho': 'completo', 'dims': ['COMERCIAL', 'NOMREP'], 'orden': [('Total', True)], 'medidas': [
                {'label': 'Facturas', 'agg': 'sum', 'col': 'IMP.FAC'}, {'label': 'Pedidos', 'agg': 'sum', 'col': 'IMP.PED'},
                {'label': 'Albaranes', 'agg': 'sum', 'col': 'IMP.ALB'}, {'label': 'Ofertas', 'agg': 'sum', 'col': 'IMP.OFE'},
                {'label': 'Total', 'agg': 'sum', 'col': 'TOTAL'}], 'formato': 'eur'},
        ],
    ),
    _pagina(
        'ventas-web', 'Ventas web', 'Ventas', 'Informe Susana · Ventas Web', 'ventas_web',
        descripcion='Pedidos de la tienda web y marketplaces (hoja de Google "Ventas Web").',
        filtros=[{'col': 'FECHA', 'label': 'Fecha', 'tipo': 'fechas', 'defecto': 'anio'}, {'col': 'MARKETPLACE', 'label': 'Marketplace'},
                 {'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'SKU', 'label': 'SKU'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pedidos', 'medida': {'agg': 'distinct', 'col': 'Nº PEDIDO'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Unidades', 'medida': {'agg': 'sum', 'col': 'UNIDADES'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'PVP corregido', 'medida': {'agg': 'sum', 'col': 'PVP Corregido'}, 'formato': 'eur'},
            {'tipo': 'columnas', 'titulo': 'PVP corregido por mes', 'ancho': 'completo', 'dim': 'FECHA', 'granularidad': 'mes', 'medidas': [{'label': 'PVP', 'agg': 'sum', 'col': 'PVP Corregido'}], 'formato': 'eur'},
            {'tipo': 'tarta', 'titulo': 'Pedidos por marketplace', 'dim': 'MARKETPLACE', 'medida': {'agg': 'distinct', 'col': 'Nº PEDIDO'}, 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Unidades por familia', 'dim': 'Familia', 'medidas': [{'label': 'Unidades', 'agg': 'sum', 'col': 'UNIDADES'}], 'formato': 'int', 'top': 20},
            {'tipo': 'barras', 'titulo': 'Pedidos por SKU', 'dim': 'SKU', 'medidas': [{'label': 'Pedidos', 'agg': 'distinct', 'col': 'Nº PEDIDO'}], 'formato': 'int', 'top': 20},
            {'tipo': 'resumen', 'titulo': 'Por familia', 'dims': ['Familia'], 'orden': [('PVP corregido', True)], 'medidas': [
                {'label': 'Unidades', 'agg': 'sum', 'col': 'UNIDADES'}, {'label': 'PVP corregido', 'agg': 'sum', 'col': 'PVP Corregido', 'formato': 'eur'},
                {'label': 'PVP', 'agg': 'sum', 'col': 'PVP', 'formato': 'eur'}, {'label': 'Pedidos', 'agg': 'distinct', 'col': 'Nº PEDIDO'}], 'formato': 'int'},
        ],
    ),

    # -------------------------------------------------------------- PENDIENTES
    _pagina(
        'ofertas-pendientes', 'Ofertas pendientes', 'Pendientes', 'Informe Susana · Ofertas Pendientes', 'ofertas_pendientes',
        descripcion='Ofertas de pedidos pendientes del año (en rojo las de fecha anterior a hoy).',
        filtros=[{'col': 'REFERENCIA', 'label': 'Referencia', 'tipo': 'texto'}, {'col': 'CODREP_NORM', 'label': 'Representante'},
                 {'col': 'NOMPROVI', 'label': 'Provincia'}, {'col': 'Codigo Cliente', 'label': 'Cliente'}, F_LISTADO],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Pendientes', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Atrasadas', 'medida': {'agg': 'count', 'donde': {'Estado': 'Atrasada'}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'kpi', 'titulo': 'En plazo', 'medida': {'agg': 'count', 'donde': {'Estado': 'En plazo'}}, 'formato': 'int', 'clase': 'verde'},
            {'tipo': 'kpi', 'titulo': 'Importe', 'medida': {'agg': 'sum', 'col': 'Importe'}, 'formato': 'eur'},
            {'tipo': 'tabla', 'titulo': 'Ofertas de pedidos pendientes / 未完成订单的报价', 'ancho': 'completo', 'orden': [('fecha', False)], 'columnas': [
                {'col': 'Codigo Cliente', 'label': 'Cliente'}, {'col': 'fecha', 'label': 'Fecha', 'formato': 'fecha', 'marca_vencido': True},
                {'col': 'codrep', 'label': 'Rep.'}, {'col': 'REFERENCIA', 'label': 'Referencia'}, {'col': 'Direccion Cliente', 'label': 'Dirección'},
                {'col': 'Importe', 'formato': 'eur'}, {'col': 'Nombre Cliente', 'label': 'Nombre'}, {'col': 'NOMPROVI', 'label': 'Provincia'},
                {'col': 'Poblacion', 'label': 'Población'},
            ]},
        ],
    ),
    _pagina(
        'ofertas-pendientes-dias', 'Ofertas pendientes (días)', 'Pendientes', 'Informe Susana · Ofer_Pendin', 'consulta_ofertas',
        descripcion='Ofertas de venta pendientes con los días que llevan abiertas.',
        filtros=[{'col': 'Fecha', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'Fecha entrega', 'label': 'Fecha entrega', 'tipo': 'fechas'},
                 {'col': 'Provincia', 'label': 'Provincia'}, F_GRUPO, F_LISTADO, {'col': 'CODREP', 'label': 'Representante'},
                 {'col': 'Código cliente', 'label': 'Cliente'}, {'col': 'Nombre cliente', 'label': 'Nombre', 'tipo': 'texto'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Ofertas', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Importe', 'medida': {'agg': 'sum', 'col': 'Total documento moneda'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Más de 7 días', 'medida': {'agg': 'count', 'donde': {'DAY': {'mayor': 7}}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Ofertas pendientes', 'ancho': 'completo', 'orden': [('DAY', True)], 'columnas': [
                {'col': 'Situación'}, {'col': 'T', 'label': 'F. pago'}, {'col': 'Fecha', 'formato': 'fecha'}, {'col': 'Total documento moneda', 'label': 'Total', 'formato': 'eur'},
                {'col': 'Código cliente', 'label': 'Cliente'}, {'col': 'Nombre cliente', 'label': 'Nombre'}, {'col': 'CODREP', 'label': 'Rep.'},
                {'col': 'Referencia'}, {'col': 'Código moneda', 'label': 'Moneda'}, {'col': 'DAY', 'label': 'Días', 'formato': 'int', 'semaforo': [[14, 'rojo'], [7, 'ambar']]},
            ]},
        ],
    ),
    _pagina(
        'albaranes-pendientes', 'Albaranes pendientes', 'Pendientes', 'Informe Susana · Alb_Pendin', 'consulta_albaranes',
        descripcion='Albaranes de venta pendientes con los días que llevan abiertos.',
        filtros=[{'col': 'Fecha', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'Provincia', 'label': 'Provincia'},
                 {'col': 'Número documento', 'label': 'Nº documento', 'tipo': 'texto'}, F_GRUPO, F_LISTADO, {'col': 'CODREP', 'label': 'Representante'},
                 {'col': 'Código cliente', 'label': 'Cliente'}, {'col': 'Nombre cliente', 'label': 'Nombre', 'tipo': 'texto'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Albaranes', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Importe', 'medida': {'agg': 'sum', 'col': 'Total documento moneda'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Más de 7 días', 'medida': {'agg': 'count', 'donde': {'DAY': {'mayor': 7}}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Albaranes pendientes', 'ancho': 'completo', 'orden': [('DAY', True)], 'columnas': [
                {'col': 'Código cliente', 'label': 'Cliente'}, {'col': 'Fecha', 'formato': 'fecha'}, {'col': 'Total documento moneda', 'label': 'Total', 'formato': 'eur'},
                {'col': 'Nombre cliente', 'label': 'Nombre'}, {'col': 'Pueblo'}, {'col': 'Dirección'}, {'col': 'Teléfono'}, {'col': 'CODREP', 'label': 'Rep.'},
                {'col': 'DAY', 'label': 'Días', 'formato': 'int', 'semaforo': [[14, 'rojo'], [7, 'ambar']]},
            ]},
        ],
    ),
    _pagina(
        'pendientes-zona', 'Pendientes Alicante y Murcia', 'Pendientes', 'Informe Susana · Pendientes', 'pendientes_zona',
        descripcion='Ofertas, pedidos y albaranes pendientes de Alicante y Murcia con su ruta de reparto.',
        filtros=[{'col': 'Provincia', 'label': 'Provincia'}, {'col': 'Cliente', 'label': 'Cliente'}, {'col': 'fecha', 'label': 'Fecha', 'tipo': 'fechas'},
                 {'col': 'Ruta', 'label': 'Ruta'}, {'col': 'Tipo', 'label': 'Tipo'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Documentos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Clientes', 'medida': {'agg': 'distinct', 'col': 'Cliente'}, 'formato': 'int'},
            {'tipo': 'tarta', 'titulo': 'Por tipo', 'dim': 'Tipo', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Por ruta', 'dim': 'Ruta', 'medidas': [{'label': 'Documentos', 'agg': 'count'}], 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Situación pendientes zona Alicante / Murcia', 'ancho': 'completo', 'orden': [('fecha', True)], 'columnas': [
                {'col': 'Tipo'}, {'col': 'Cliente'}, {'col': 'Codigo Postal', 'label': 'C.P.'}, {'col': 'Direccion Cliente', 'label': 'Dirección'},
                {'col': 'REFERENCIA', 'label': 'Referencia'}, {'col': 'fecha', 'label': 'Fecha', 'formato': 'fecha'}, {'col': 'Ruta'},
                {'col': 'Poblacion', 'label': 'Población'}, {'col': 'Provincia'},
            ]},
        ],
    ),
    _pagina(
        'revision-albaran', 'Revisión de albaranes', 'Pendientes', 'Informe Susana · Revisión Albarán', 'analisis_albaran',
        descripcion='Líneas de pedido pendientes frente al stock de Innertia (disponible, picking y almacenamiento) con sus ubicaciones.',
        filtros=[{'col': 'FECHA_ALBARAN', 'label': 'Fecha albarán', 'tipo': 'fechas'}, {'col': 'NOMCODCLI', 'label': 'Cliente', 'tipo': 'texto'},
                 {'col': 'ARTICULO PEDIDO', 'label': 'Artículo'}, {'col': 'CODCLI', 'label': 'Cód. cliente'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Líneas pendientes', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Unidades pedidas', 'medida': {'agg': 'sum', 'col': 'UNIDADES_PEDIDO'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Sin stock disponible', 'medida': {'agg': 'count', 'donde': {'Disponible': {'menor_igual': 0}}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Líneas pendientes', 'ancho': 'completo', 'orden': [('FECHA_PEDIDO', False)], 'columnas': [
                {'col': 'FECHA_ALBARAN', 'label': 'Fecha albarán', 'formato': 'fecha'}, {'col': 'CODCLI'}, {'col': 'NOMBRE CLIENTE', 'label': 'Cliente'},
                {'col': 'ARTICULO PEDIDO', 'label': 'Artículo'}, {'col': 'ESTADO_PEDIDO', 'label': 'Estado'},
                {'col': 'UNIDADES_PEDIDO', 'label': 'Uds. pedido', 'formato': 'int'}, {'col': 'UNIDADES_SERVIDAS', 'label': 'Uds. servidas', 'formato': 'int'},
                {'col': 'Disponible', 'formato': 'int', 'semaforo': [[0, 'verde', 'mayor']]}, {'col': 'Picking_Stock', 'label': 'Picking', 'formato': 'int'},
                {'col': 'Packing', 'label': 'Almacenamiento', 'formato': 'int'}, {'col': 'PICKING 2', 'label': 'Ubic. picking'},
                {'col': 'ALMACENAMIENTO', 'label': 'Ubic. almacenamiento'}, {'col': 'FECHA_PEDIDO', 'label': 'Fecha pedido', 'formato': 'fecha'},
            ]},
        ],
    ),

    # ----------------------------------------------------------------- COMPRAS
    _pagina(
        'estado-compras', 'Estado de compras', 'Compras', 'Informe Susana · Estado Compras', 'stock_tabla',
        descripcion='催货: artículos cuyo stock más lo que viene en camino no llega a 1,2 veces el stock mínimo.',
        filtros=[{'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Categoria_Proveedor', 'label': 'Categoría'},
                 {'col': 'Familia', 'label': 'Familia'}, {'col': 'Ratio_Stock_Min', 'label': 'Ratio stock mín.', 'tipo': 'rango', 'defecto': [None, 1.2]}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Bajo mínimo (ratio < 1)', 'medida': {'agg': 'count', 'donde': {'Ratio_Stock_Min': {'menor': 1}}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Artículos a reclamar', 'ancho': 'completo', 'orden': [('Ratio_Stock_Min', False)], 'columnas': [
                {'col': 'CODART', 'label': 'Artículo'}, {'col': 'CODPRO', 'label': 'Prov.'}, {'col': 'Diferencial_Cantidad_Pedido_A3', 'label': 'Diferencial pedido', 'formato': 'int'},
                {'col': 'Diferencial_Cantidad_Pedido_Innertia', 'label': 'Diferencial pedido Inn.', 'formato': 'int'},
                {'col': 'Ratio_Stock_Min', 'label': 'Ratio stock mín.', 'formato': 'dec', 'semaforo': [[1, 'rojo', 'menor'], [1.2, 'ambar', 'menor']]},
                {'col': 'Ratio_Stock_Min_Innertia', 'label': 'Ratio Inn.', 'formato': 'dec'}, {'col': 'Stock_Total', 'label': 'Stock A3', 'formato': 'int'},
                {'col': 'Stock_Total_Innertia', 'label': 'Stock Innertia', 'formato': 'int'}, {'col': 'Reservas', 'formato': 'int'}, {'col': 'Reserva_B', 'label': 'Reserva B', 'formato': 'int'},
                {'col': 'StockMin', 'formato': 'int'}, {'col': 'StockMax', 'formato': 'int'}, {'col': 'PuntoPedido', 'label': 'Punto pedido', 'formato': 'int'},
                {'col': 'Media_Ventas_Mes', 'label': 'Media ventas mes', 'formato': 'int'}, {'col': 'Media_Ventas_Anio_Anterior', 'label': 'Media ventas año ant.', 'formato': 'int'},
                {'col': 'MejorAnio', 'label': 'Mejor año'}, {'col': 'MejorMes', 'label': 'Mejor mes'},
            ]},
        ],
    ),
    _pagina(
        'stock-proveedor', 'Stock por proveedor', 'Compras', 'Informe Susana · Stock Proveedor Otro', 'stock_tabla',
        descripcion='Situación de stock y reservas por artículo y almacén (A3).',
        filtros=[{'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Categoria_Proveedor', 'label': 'Categoría'}, {'col': 'Familia', 'label': 'Familia'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Stock total', 'medida': {'agg': 'sum', 'col': 'Stock_Total'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Reservas', 'medida': {'agg': 'sum', 'col': 'Reservas'}, 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Situación compras / pedidos', 'ancho': 'completo', 'orden': [('Stock_Total', True)], 'columnas': [
                {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Descripcion', 'label': 'Descripción'}, {'col': 'Diferencial_Cantidad_Pedido_A3', 'label': 'Diferencial pedido', 'formato': 'int'},
                {'col': 'Ratio_Stock_Min', 'label': '(Stock + Res. B) / Mín.', 'formato': 'dec'}, {'col': 'Stock_mas_Reserva_A_mas_B', 'label': 'Stock + Res. A + B', 'formato': 'int'},
                {'col': 'Stock_Total', 'label': 'Stock total', 'formato': 'int'}, {'col': 'CODPRO', 'label': 'Prov.'}, {'col': 'Reservas', 'formato': 'int'},
                {'col': 'StockMin', 'formato': 'int'}, {'col': 'PuntoPedido', 'label': 'Punto pedido', 'formato': 'int'}, {'col': 'StockMax', 'formato': 'int'},
                {'col': 'Reserva_B', 'label': 'Reserva B', 'formato': 'int'}, {'col': 'Stock_Almacen_1', 'label': 'Almacén 1', 'formato': 'int'},
                {'col': 'Stock_Almacen_ASPE', 'label': 'ASPE', 'formato': 'int'}, {'col': 'Stock_Almacen_Toledo', 'label': 'Toledo', 'formato': 'int'},
            ]},
        ],
    ),
    _pagina(
        'compras', 'Compras pendientes de recibir', 'Compras', 'Informe Susana · Compras', 'compras',
        descripcion='Unidades pendientes de recibir por artículo y proveedor, con referencia numerada y sin numerar.',
        filtros=[{'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'Referencia_Numerada', 'label': 'Referencia'}, {'col': 'Codigo Articulo', 'label': 'Artículo'},
                 {'col': 'Fecha', 'label': 'Fecha', 'tipo': 'fechas'}, {'col': 'Categoria_Proveedor', 'label': 'Categoría'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Unidades pendientes', 'medida': {'agg': 'sum', 'col': 'Total Unidades Compra'}, 'formato': 'int'},
            {'tipo': 'barras', 'titulo': 'Unidades por proveedor', 'dim': 'CODPRO', 'medidas': [{'label': 'Unidades', 'agg': 'sum', 'col': 'Total Unidades Compra'}], 'formato': 'int', 'top': 20},
            {'tipo': 'tabla', 'titulo': 'Situación compras / pedidos', 'ancho': 'completo', 'orden': [('Fecha', True)], 'columnas': [
                {'col': 'CODPRO', 'label': 'Prov.'}, {'col': 'Fecha', 'formato': 'fecha'}, {'col': 'Codigo Articulo', 'label': 'Artículo'},
                {'col': 'Referencia_No_Numerada', 'label': 'Ref. sin numerar'}, {'col': 'Unidades_No_Numeradas', 'label': 'Uds. sin numerar', 'formato': 'int'},
                {'col': 'Referencia_Numerada', 'label': 'Ref. numerada'}, {'col': 'Unidades_Numeradas', 'label': 'Uds. numeradas', 'formato': 'int'},
                {'col': 'Total Unidades Compra', 'label': 'Total uds.', 'formato': 'int'},
                {'col': 'DiasDesdePedido', 'label': 'Días desde pedido', 'formato': 'int', 'semaforo': [[60, 'rojo'], [30, 'ambar']]},
            ]},
        ],
    ),
    _pagina(
        'situacion-compras', 'Situación de compras', 'Compras', 'Informe Susana · Situación Compras', 'situacion_compras',
        descripcion='Pedidos de compra con referencia numerada: si ya se recibieron y si el artículo tiene ubicación.',
        filtros=[{'col': 'Código Proveedor', 'label': 'Proveedor'}, {'col': 'Referencia', 'label': 'Referencia', 'tipo': 'texto'}, {'col': 'CODART', 'label': 'Artículo'},
                 {'col': 'EstadoLogico', 'label': 'Estado'}, {'col': 'SituacionPedido', 'label': 'Situación'}, {'col': 'Categoria_Proveedor', 'label': 'Categoría'},
                 {'col': 'SituacionDetallePedido', 'label': 'Situación detalle'}, {'col': 'FechaPedido', 'label': 'Fecha pedido', 'tipo': 'fechas', 'defecto': 'anio'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'No recibido', 'medida': {'agg': 'count', 'donde': {'EstadoLogico': 'No recibido'}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'kpi', 'titulo': 'Recibido sin ubicar', 'medida': {'agg': 'count', 'donde': {'EstadoLogico': 'Recibido sin ubicar'}}, 'formato': 'int', 'clase': 'ambar'},
            {'tipo': 'kpi', 'titulo': 'Recibido y ubicado', 'medida': {'agg': 'count', 'donde': {'EstadoLogico': 'Recibido y ubicado'}}, 'formato': 'int', 'clase': 'verde'},
            {'tipo': 'tarta', 'titulo': 'Por estado', 'dim': 'EstadoLogico', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Situación compras / pedidos', 'ancho': 'completo', 'orden': [('FechaPedido', True)], 'columnas': [
                {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Código Proveedor', 'label': 'Prov.'}, {'col': 'Descripción'},
                {'col': 'DiasDesdePedido', 'label': 'Días', 'formato': 'int'}, {'col': 'FechaPedido', 'label': 'Fecha pedido', 'formato': 'fecha'},
                {'col': 'FechaRecepcion', 'label': 'Fecha recepción', 'formato': 'fecha'}, {'col': 'Referencia'},
                {'col': 'SituacionDetallePedido', 'label': 'Situación detalle'}, {'col': 'SituacionPedido', 'label': 'Situación'},
                {'col': 'Ubicacion', 'label': 'Ubicación'}, {'col': 'EstadoLogico', 'label': 'Estado'},
            ]},
        ],
    ),
    _pagina(
        'compras-pendientes', 'Compras pendientes', 'Compras', 'Informe Susana · Compras Pendientes', 'compras_pendientes',
        descripcion='Pedidos de compra pendientes de los últimos 6 meses con la fecha prevista de entrega (56 días si no hay fecha) más 4 días.',
        filtros=[{'col': 'FECHA_MIN', 'label': 'Fecha pedido', 'tipo': 'fechas'}, {'col': 'CODART', 'label': 'Artículo'}, {'col': 'NUMDOC', 'label': 'Nº documento', 'tipo': 'texto'},
                 {'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'Estado entrega', 'label': 'Entrega'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Importe pendiente', 'medida': {'agg': 'sum', 'col': 'TOTAL_LINEA'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Unidades pendientes', 'medida': {'agg': 'sum', 'col': 'TOTAL_UNIDADES'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Pedidos', 'medida': {'agg': 'distinct', 'col': 'NUMDOC'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Líneas retrasadas', 'medida': {'agg': 'count', 'donde': {'Estado entrega': 'Retrasado'}}, 'formato': 'int', 'clase': 'rojo'},
            {'tipo': 'tabla', 'titulo': 'Compras pendientes', 'ancho': 'completo', 'orden': [('DIAS_HASTA_ENTREGA', False)], 'columnas': [
                {'col': 'CODART', 'label': 'Artículo'}, {'col': 'REFERENCIA_NUM', 'label': 'Ref. numerada'}, {'col': 'DIAS_DESDE_PEDIDO', 'label': 'Días desde pedido', 'formato': 'int'},
                {'col': 'DIAS_HASTA_ENTREGA', 'label': 'Días hasta entrega', 'formato': 'int', 'semaforo': [[0, 'rojo', 'menor'], [7, 'ambar', 'menor']]},
                {'col': 'FECHA_MIN', 'label': 'Fecha pedido', 'formato': 'fecha'}, {'col': 'FECENTREGA_MAX', 'label': 'Entrega prevista', 'formato': 'fecha'},
                {'col': 'NUMDOC', 'label': 'Nº doc.'}, {'col': 'CODPRO', 'label': 'Prov.'}, {'col': 'TOTAL_UNIDADES', 'label': 'Unidades', 'formato': 'int'},
                {'col': 'TOTAL_LINEA', 'label': 'Importe', 'formato': 'eur'},
            ]},
        ],
    ),

    # ----------------------------------------------------------------- ALMACÉN
    _pagina(
        'informe-almacen', 'Informe almacén', 'Almacén', 'Informe Almacén', 'stock_almacen',
        descripcion='Stock por artículo en Innertia: total (picking + almacenamiento), disponible y ubicaciones.',
        filtros=[{'col': 'idArticulo', 'label': 'Artículo'}, {'col': 'idArticulo', 'label': 'Buscar artículo', 'tipo': 'texto'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Stock total', 'medida': {'agg': 'sum', 'col': 'Stock Total'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Picking', 'medida': {'agg': 'sum', 'col': 'Picking'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Almacenamiento', 'medida': {'agg': 'sum', 'col': 'Almacenamiento'}, 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Stock por artículo', 'ancho': 'completo', 'orden': [('idArticulo', False)], 'columnas': [
                {'col': 'idArticulo', 'label': 'Artículo'}, {'col': 'Stock Total', 'formato': 'int'}, {'col': 'Stock Disponible', 'label': 'Disponible', 'formato': 'int'},
                {'col': 'Picking', 'formato': 'int'}, {'col': 'Almacenamiento', 'formato': 'int'},
                {'col': 'Etiquetas_Picking', 'label': 'Ubic. picking'}, {'col': 'Etiquetas_Almacenamiento', 'label': 'Ubic. almacenamiento'},
            ]},
        ],
    ),
    _pagina(
        'a3-vs-innertia', 'A3 frente a Innertia', 'Almacén', 'Informe Susana · A3 vs Innertia / Informe Cobros · Tabla Stock', 'stock_tabla',
        descripcion='Diferencias de stock entre el ERP (A3) y el almacén (Innertia) por artículo.',
        filtros=[{'col': 'Categoria_Proveedor', 'label': 'Categoría'}, {'col': 'CODDESCART', 'label': 'Artículo', 'tipo': 'texto'}, {'col': 'Familia', 'label': 'Familia'},
                 {'col': 'CODART', 'label': 'Código'}, {'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'Dif_A3_menos_Inn', 'label': 'Diferencia', 'tipo': 'rango'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Con diferencia', 'medida': {'agg': 'count', 'donde': {'Dif_A3_menos_Inn': {'distinto': 0}}}, 'formato': 'int', 'clase': 'ambar'},
            {'tipo': 'kpi', 'titulo': 'Stock A3', 'medida': {'agg': 'sum', 'col': 'Stock_Total'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Stock Innertia', 'medida': {'agg': 'sum', 'col': 'Stock_Total_Innertia'}, 'formato': 'int'},
            {'tipo': 'tabla', 'titulo': 'Stock A3 frente a Innertia', 'ancho': 'completo', 'orden': [('Dif_A3_menos_Inn', True)], 'columnas': [
                {'col': 'CODART', 'label': 'Artículo'}, {'col': 'Stock_Total', 'label': 'Stock A3', 'formato': 'int'},
                {'col': 'Stock_Total_Innertia', 'label': 'Stock Innertia', 'formato': 'int'},
                {'col': 'Dif_A3_menos_Inn', 'label': 'Dif. A3 - Inn.', 'formato': 'int', 'signo': True},
                {'col': 'Picking', 'formato': 'int'}, {'col': 'Almacenamiento', 'formato': 'int'},
                {'col': 'Etiquetas_Picking', 'label': 'Ubic. picking'}, {'col': 'Etiquetas_Almacenamiento', 'label': 'Ubic. almacenamiento'},
                {'col': 'Diferencial_Cantidad_Pedido_A3', 'label': 'Diferencial pedido', 'formato': 'int'},
                {'col': 'Diferencial_Cantidad_Pedido_Innertia', 'label': 'Diferencial pedido Inn.', 'formato': 'int'},
                {'col': 'Stock_Total_dividido_StockMin', 'label': 'Stock / mín.', 'formato': 'dec'},
                {'col': 'Stock_Innertia_dividido_StockMin', 'label': 'Stock Inn. / mín.', 'formato': 'dec'},
                {'col': 'Stock_mas_Reserva_A_mas_B', 'label': 'Stock + Res. A + B', 'formato': 'int'},
                {'col': 'Stock_Inn_mas_Reserva_A_mas_B', 'label': 'Stock Inn. + Res. A + B', 'formato': 'int'},
            ]},
        ],
    ),
    _pagina(
        'volumen-paquetes', 'Volumen y huecos A/B/C', 'Almacén', 'Informe Susana · Hoja Ventas', 'conteo_paquetes',
        descripcion='Paquetes vendidos este año por artículo (meses cerrados), volumen de caja y grupo de hueco A/B/C por semana, quincena y mes.',
        filtros=[{'col': 'CODPRO', 'label': 'Proveedor'}, {'col': 'Categoria_Proveedor', 'label': 'Categoría'}, {'col': 'MEGA_AGRUPACION', 'label': 'Agrupación'},
                 {'col': 'CODART', 'label': 'Artículo'}, {'col': 'FAMILIA', 'label': 'Familia'}, {'col': 'GRUPO Semanal', 'label': 'Grupo semanal'},
                 {'col': 'GRUPO Mensual', 'label': 'Grupo mensual'}, {'col': 'GRUPO Bisemanal', 'label': 'Grupo bisemanal'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Artículos', 'medida': {'agg': 'distinct', 'col': 'CODART'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Paquetes del año', 'medida': {'agg': 'sum', 'col': 'TOTAL_PAQUETES'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Grupo A (semanal)', 'medida': {'agg': 'count', 'donde': {'GRUPO Semanal': 'A'}}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Sin medidas de caja', 'medida': {'agg': 'count', 'donde': {'VOLUMEN CAJA': None}}, 'formato': 'int', 'clase': 'ambar'},
            {'tipo': 'tabla', 'titulo': 'Paquetes y volumen por artículo', 'ancho': 'completo', 'orden': [('MEDIA_MENSUAL_PAQUETES', True)], 'columnas': [
                {'col': 'MEGA_AGRUPACION', 'label': 'Agrupación'}, {'col': 'CODART', 'label': 'Artículo'}, {'col': 'DESCART', 'label': 'Descripción'},
                {'col': 'Etiquetas_Picking', 'label': 'Ubic. picking'}, {'col': 'Etiquetas_Almacenamiento', 'label': 'Ubic. almac.'},
                {'col': 'GRUPO Semanal', 'label': 'Grupo sem.'}, {'col': 'GRUPO Bisemanal', 'label': 'Grupo bisem.'}, {'col': 'GRUPO Mensual', 'label': 'Grupo mens.'},
                {'col': 'CODPRO', 'label': 'Prov.'}, {'col': 'UNIDADES/PAQUETES', 'label': 'Uds./paquete', 'formato': 'int'}, {'col': 'FAMILIA', 'label': 'Familia'},
                {'col': 'TOTAL_PAQUETES', 'label': 'Paquetes año', 'formato': 'int'}, {'col': 'MEDIA_MENSUAL_PAQUETES', 'label': 'Media mensual', 'formato': 'int'},
                {'col': 'MEDIA_SEMANAL_PAQUETE', 'label': 'Media semanal', 'formato': 'int'},
                {'col': 'Cajas Sobrantes A Semanal', 'label': 'Cajas sobrantes A', 'formato': 'int'}, {'col': 'VOLUMEN CAJA', 'label': 'Vol. caja (m³)', 'formato': 'dec4'},
                {'col': 'Volumen Total Semanal', 'label': 'Vol. semanal', 'formato': 'dec4'}, {'col': 'Volumen Total Bisemanal', 'label': 'Vol. bisemanal', 'formato': 'dec4'},
                {'col': 'Volumen Total Mensual', 'label': 'Vol. mensual', 'formato': 'dec4'}, {'col': 'ALTO', 'formato': 'dec'}, {'col': 'ANCHO', 'formato': 'dec'}, {'col': 'LARGO', 'formato': 'dec'},
            ]},
        ],
    ),

    # --------------------------------------------------------------- LOGÍSTICA
    _pagina(
        'coste-transporte', 'Coste de transporte', 'Logística', 'Informe Cobros · Coste Transporte', 'expediciones_transporte',
        datasets_extra=['cobro_transporte'],
        descripcion='Expediciones de ONTIME y portes facturados contra la tarifa teórica (provincia, rango de peso y número de bultos).',
        filtros=[{'col': 'Cliente', 'label': 'Cliente (expediciones)'}, {'col': 'CODCLI', 'label': 'Cliente (facturado)'},
                 {'col': 'Provincia Limpia', 'label': 'Provincia'}, {'col': 'Fecha', 'label': 'Fecha portes', 'tipo': 'fechas'},
                 {'col': 'Fecha pedido', 'label': 'Fecha pedido', 'tipo': 'fechas'}],
        visuales=[
            {'tipo': 'kpi', 'titulo': 'Expediciones', 'medida': {'agg': 'count'}, 'formato': 'int'},
            {'tipo': 'kpi', 'titulo': 'Precio teórico expediciones', 'medida': {'agg': 'sum', 'col': 'Precio Teorico Total'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Portes facturados', 'dataset': 'cobro_transporte', 'medida': {'agg': 'sum', 'col': 'Total'}, 'formato': 'eur'},
            {'tipo': 'kpi', 'titulo': 'Diferencia facturado - teórico', 'dataset': 'cobro_transporte', 'medida': {'agg': 'sum', 'col': 'Diferencia Precio Facturado / Teorico'}, 'formato': 'eur'},
            {'tipo': 'tabla', 'titulo': 'Expediciones', 'ancho': 'completo', 'orden': [('Fecha pedido', True)], 'columnas': [
                {'col': 'Cliente'}, {'col': 'C.P. Envío', 'label': 'C.P.'}, {'col': 'Id Expedición'}, {'col': 'Estado'}, {'col': 'Fecha pedido', 'formato': 'fecha'},
                {'col': 'Contenedores Logísticos', 'label': 'Contenedores', 'formato': 'int'}, {'col': 'Peso', 'formato': 'dec'}, {'col': 'Usuario Verif.'},
                {'col': 'Provincia Limpia', 'label': 'Provincia'}, {'col': 'Precio Teórico', 'formato': 'eur'}, {'col': 'Precio Teorico Total', 'label': 'Teórico total', 'formato': 'eur'},
                {'col': 'Rango Peso'}, {'col': 'Escalado Asignado', 'label': 'Escalado'},
            ]},
            {'tipo': 'tabla', 'titulo': 'Portes facturados frente a tarifa', 'dataset': 'cobro_transporte', 'ancho': 'completo', 'orden': [('Fecha', True)], 'columnas': [
                {'col': 'CODCLI'}, {'col': 'Fecha', 'formato': 'fecha'}, {'col': 'Total', 'formato': 'eur'}, {'col': 'Total Unitario', 'formato': 'eur'},
                {'col': 'Bultos/Palets', 'formato': 'int'}, {'col': 'Kilos', 'formato': 'dec'}, {'col': 'TIPOLOGÍA'},
                {'col': 'Diferencia Precio Facturado / Teorico', 'label': 'Dif. total', 'formato': 'eur', 'signo': True},
                {'col': 'Diferencia Precio Facturado / Teorico Unitario', 'label': 'Dif. unitaria', 'formato': 'eur', 'signo': True},
                {'col': 'Precio Teórico', 'formato': 'eur'}, {'col': 'Precio Teórico Total', 'formato': 'eur'}, {'col': 'CP Consignatario', 'label': 'C.P.'},
                {'col': 'Provincia Limpia', 'label': 'Provincia'}, {'col': 'Rango Peso'},
            ]},
        ],
    ),
]

PAGINAS_POR_SLUG = {p['slug']: p for p in PAGINAS}

# Grupo de Keycloak que da acceso a todas las páginas de una sección (o a todas).
GRUPO_TODOS = 'Informes'


def grupo_keycloak(seccion):
    return f'Informes {seccion}'


def page_slug(pagina):
    """Slug de la Page (permisos) de un informe."""
    return 'informe-' + pagina['slug']


def url_name(pagina):
    return 'informe_' + pagina['slug'].replace('-', '_')


def group_label(pagina):
    return f"Informes · {pagina['grupo']}"


def datasets_de(pagina):
    return [pagina['dataset'], *pagina['datasets_extra']]


SECCIONES = sorted({p['grupo'] for p in PAGINAS})

assert all(slugify(p['slug']) == p['slug'] for p in PAGINAS)
assert len(PAGINAS_POR_SLUG) == len(PAGINAS)
