/* Motor de las páginas de informes (réplica web de los Power BI de SPSIL).
 *
 * La página trae su descripción (gateway/informes.py) en #inf-spec y pide
 * las filas al portal (que a su vez las pide al agente del almacén). Todo lo
 * que en Power BI eran segmentaciones, medidas DAX y visuales se hace aquí,
 * en el navegador, sobre las filas ya cargadas: filtrar no vuelve a la BD.
 *
 * Sin librerías externas, igual que el resto del portal: los gráficos son
 * SVG/HTML generados a mano.
 */
(function () {
    'use strict';

    var SPEC = JSON.parse(document.getElementById('inf-spec').textContent);
    var CFG = window.INFORME_CONFIG;
    var T = CFG.textos;

    var DATOS = {};          // nombre -> {columnas: [...], filas: [{...}], actualizado}
    var FILTROS = [];        // estado de cada segmentación de SPEC.filtros
    var SELECCION = [];      // filtros cruzados al pulsar un gráfico: {col, gran, valor, etiqueta}
    var COLORES = ['#f5821f', '#1a1a1a', '#f7c600', '#6b7280', '#16a34a', '#2563eb', '#dc2626', '#9333ea', '#0d9488', '#d97706'];

    // ---------------------------------------------------------------- utilidades

    function el(tag, attrs, hijos) {
        var nodo = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                if (k === 'class') nodo.className = attrs[k];
                else if (k === 'text') nodo.textContent = attrs[k];
                else if (k.slice(0, 2) === 'on') nodo.addEventListener(k.slice(2), attrs[k]);
                else nodo.setAttribute(k, attrs[k]);
            });
        }
        (hijos || []).forEach(function (h) { if (h) nodo.appendChild(typeof h === 'string' ? document.createTextNode(h) : h); });
        return nodo;
    }

    function svgEl(tag, attrs) {
        var nodo = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.keys(attrs || {}).forEach(function (k) { nodo.setAttribute(k, attrs[k]); });
        return nodo;
    }

    function esNum(v) { return typeof v === 'number' && !isNaN(v); }
    function num(v) { if (esNum(v)) return v; var n = parseFloat(v); return isNaN(n) ? 0 : n; }
    function hoyISO() { var d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function isoDe(fecha) { return fecha.getFullYear() + '-' + pad(fecha.getMonth() + 1) + '-' + pad(fecha.getDate()); }
    function sumarDias(iso, dias) { var d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + dias); return isoDe(d); }
    function difDias(a, b) { return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000); }
    var MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

    var fmtEur = new Intl.NumberFormat('es-ES', {style: 'currency', currency: 'EUR', maximumFractionDigits: 2});
    var fmtEur0 = new Intl.NumberFormat('es-ES', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0});
    var fmtInt = new Intl.NumberFormat('es-ES', {maximumFractionDigits: 0});
    var fmtDec = new Intl.NumberFormat('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    var fmtDec4 = new Intl.NumberFormat('es-ES', {minimumFractionDigits: 4, maximumFractionDigits: 4});
    var fmtPct = new Intl.NumberFormat('es-ES', {style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1});

    function formatear(valor, formato, compacto) {
        if (valor === null || valor === undefined || valor === '') return '';
        switch (formato) {
            case 'eur': return esNum(valor) ? (compacto && Math.abs(valor) >= 10000 ? fmtEur0 : fmtEur).format(valor) : valor;
            case 'int': return esNum(valor) ? fmtInt.format(valor) : valor;
            case 'dec': return esNum(valor) ? fmtDec.format(valor) : valor;
            case 'dec4': return esNum(valor) ? fmtDec4.format(valor) : valor;
            case 'pct': return esNum(valor) ? fmtPct.format(valor) : valor;
            case 'fecha': return fechaCorta(valor);
            default: return String(valor);
        }
    }

    function fechaCorta(v) {
        var s = String(v);
        var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
        return m ? m[3] + '/' + m[2] + '/' + m[1] : s;
    }

    function etiquetaPeriodo(clave, gran) {
        if (!clave) return '(vacío)';
        if (gran === 'mes') { var p = clave.split('-'); return MESES[parseInt(p[1], 10) - 1] + ' ' + p[0].slice(2); }
        if (gran === 'dia') { var q = clave.split('-'); return q[2] + '/' + q[1]; }
        if (gran === 'anio') return clave;
        return clave;
    }

    function clavePeriodo(valor, gran) {
        if (valor === null || valor === undefined) return '';
        var s = String(valor);
        if (gran === 'mes') return s.slice(0, 7);
        if (gran === 'anio') return s.slice(0, 4);
        if (gran === 'dia') return s.slice(0, 10);
        return s;
    }

    function valorDim(fila, col, gran) {
        var v = fila[col];
        if (gran) return clavePeriodo(v, gran);
        return (v === null || v === undefined || v === '') ? '(vacío)' : String(v);
    }

    // ------------------------------------------------------- filtros de filas

    function cumple(valor, condicion) {
        if (condicion === null) return valor === null || valor === undefined || valor === '';
        if (Array.isArray(condicion)) return condicion.indexOf(valor) !== -1;
        if (typeof condicion === 'object') {
            if ('distinto' in condicion) return valor !== condicion.distinto;
            if ('fuera' in condicion) return condicion.fuera.indexOf(valor) === -1;
            if ('mayor' in condicion) return num(valor) > condicion.mayor;
            if ('menor' in condicion) return num(valor) < condicion.menor;
            if ('menor_igual' in condicion) return num(valor) <= condicion.menor_igual;
            if ('mayor_igual' in condicion) return num(valor) >= condicion.mayor_igual;
            return true;
        }
        return valor === condicion;
    }

    function aplicarDonde(filas, donde) {
        if (!donde) return filas;
        var claves = Object.keys(donde);
        return filas.filter(function (f) {
            for (var i = 0; i < claves.length; i++) if (!cumple(f[claves[i]], donde[claves[i]])) return false;
            return true;
        });
    }

    function tieneColumna(nombreDs, col) {
        return DATOS[nombreDs] && DATOS[nombreDs].columnas.indexOf(col) !== -1;
    }

    function filasFiltradas(nombreDs) {
        var ds = DATOS[nombreDs];
        if (!ds) return [];
        var activos = FILTROS.filter(function (f) { return f.activo() && tieneColumna(nombreDs, f.spec.col); });
        var selecciones = SELECCION.filter(function (s) { return tieneColumna(nombreDs, s.col); });
        if (!activos.length && !selecciones.length) return ds.filas;
        return ds.filas.filter(function (fila) {
            for (var i = 0; i < activos.length; i++) if (!activos[i].pasa(fila)) return false;
            for (var j = 0; j < selecciones.length; j++) {
                if (valorDim(fila, selecciones[j].col, selecciones[j].gran) !== selecciones[j].valor) return false;
            }
            return true;
        });
    }

    // --------------------------------------------------------------- medidas

    function agrupar(filas, dims, gran) {
        var grupos = new Map();
        filas.forEach(function (f) {
            var clave = dims.map(function (d, i) { return valorDim(f, d, i === 0 ? gran : null); }).join('\u0001');
            var g = grupos.get(clave);
            if (!g) { g = {clave: clave, valores: clave.split('\u0001'), filas: []}; grupos.set(clave, g); }
            g.filas.push(f);
        });
        return Array.from(grupos.values());
    }

    function pedidosValidos(filasContexto, filasObjetivo, colCliente, colFecha) {
        // Fechas de pedido de cada cliente en el contexto (cualquier tipo),
        // para saber cuál fue su pedido anterior.
        var porCliente = new Map();
        filasContexto.forEach(function (f) {
            var c = f[colCliente], d = f[colFecha];
            if (c === null || c === undefined || !d) return;
            var lista = porCliente.get(c);
            if (!lista) { lista = new Set(); porCliente.set(c, lista); }
            lista.add(String(d).slice(0, 10));
        });
        var ordenadas = new Map();
        porCliente.forEach(function (s, c) { ordenadas.set(c, Array.from(s).sort()); });
        var pares = new Set();
        filasObjetivo.forEach(function (f) {
            var c = f[colCliente], d = f[colFecha];
            if (c === null || c === undefined || !d) return;
            pares.add(c + '\u0001' + String(d).slice(0, 10));
        });
        var total = 0;
        pares.forEach(function (par) {
            var partes = par.split('\u0001');
            var fechas = ordenadas.get(partes[0]) || [];
            var idx = fechas.indexOf(partes[1]);
            var anterior = idx > 0 ? fechas[idx - 1] : null;
            if (!anterior || difDias(anterior, partes[1]) > 15) total += 1;
        });
        return total;
    }

    function medir(filas, m, ctx) {
        ctx = ctx || {};
        var base = filas;
        var sel = aplicarDonde(filas, m.donde);
        var i, v, n;
        switch (m.agg) {
            case 'count': return sel.length;
            case 'sum': v = 0; for (i = 0; i < sel.length; i++) v += num(sel[i][m.col]); return v;
            case 'avg':
                v = 0; n = 0;
                for (i = 0; i < sel.length; i++) { if (sel[i][m.col] !== null && sel[i][m.col] !== '') { v += num(sel[i][m.col]); n++; } }
                return n ? v / n : null;
            case 'min': case 'max':
                var vals = sel.map(function (f) { return f[m.col]; }).filter(function (x) { return x !== null && x !== undefined && x !== ''; });
                if (!vals.length) return null;
                vals.sort(); return m.agg === 'min' ? vals[0] : vals[vals.length - 1];
            case 'distinct':
                var s = new Set();
                for (i = 0; i < sel.length; i++) { v = sel[i][m.col]; if (v !== null && v !== undefined && v !== '') s.add(v); }
                return s.size;
            case 'distinct_por_mes':
                var meses = new Map();
                sel.forEach(function (f) {
                    var mes = String(f[m.fecha] || '').slice(0, 7);
                    if (!meses.has(mes)) meses.set(mes, new Set());
                    meses.get(mes).add(f[m.col]);
                });
                v = 0; meses.forEach(function (st) { v += st.size; }); return v;
            case 'pedidos_validos': return pedidosValidos(base, sel, m.cliente, m.fecha);
            case 'ratio':
                var den = medir(filas, m.den, ctx);
                return den ? medir(filas, m.num, ctx) / den : 0;
            case 'suma':
                return m.medidas.reduce(function (acc, x) { return acc + num(medir(filas, x, ctx)); }, 0);
            case 'participacion':
                var totalFilas = ctx.total || filas;
                if (m.respecto && filas.length) {
                    var ref = filas[0];
                    totalFilas = totalFilas.filter(function (f) {
                        return m.respecto.every(function (c) { return f[c] === ref[c]; });
                    });
                }
                var tot = medir(totalFilas, m.medida, ctx);
                return tot ? medir(filas, m.medida, ctx) / tot : 0;
            case 'top':
                var mejor = null, mejorValor = -Infinity;
                agrupar(sel, [m.dim]).forEach(function (g) {
                    var x = num(medir(g.filas, m.medida, ctx));
                    if (x > mejorValor) { mejorValor = x; mejor = g.valores[0]; }
                });
                return mejor;
            case 'rango_fechas':
                var fechas = sel.map(function (f) { return f[m.col]; }).filter(Boolean).sort();
                if (!fechas.length) return '';
                return fechas[0].slice(0, 10).replace(/-/g, '/') + ' a ' + fechas[fechas.length - 1].slice(0, 10).replace(/-/g, '/');
            case 'objetivo_pedidos':
                var dias = new Set(), reps = new Set();
                sel.forEach(function (f) { if (f[m.fecha]) dias.add(String(f[m.fecha]).slice(0, 10)); if (f[m.rep]) reps.add(f[m.rep]); });
                return dias.size * reps.size * (m.por || 1);
            default:
                return null;
        }
    }

    // ------------------------------------------------------------ segmentaciones

    function opcionesDe(col) {
        var valores = new Set();
        Object.keys(DATOS).forEach(function (nombre) {
            if (!tieneColumna(nombre, col)) return;
            DATOS[nombre].filas.forEach(function (f) {
                var v = f[col];
                valores.add(v === null || v === undefined || v === '' ? '(vacío)' : String(v));
            });
        });
        return Array.from(valores).sort(function (a, b) { return a.localeCompare(b, 'es', {numeric: true}); });
    }

    function presetFechas(clave) {
        var hoy = hoyISO();
        var d = new Date();
        switch (clave) {
            case 'hoy': return [hoy, hoy];
            case '7d': return [sumarDias(hoy, -6), hoy];
            case '30d': return [sumarDias(hoy, -29), hoy];
            case 'mes': return [hoy.slice(0, 8) + '01', hoy];
            case 'mes_ant':
                var ini = new Date(d.getFullYear(), d.getMonth() - 1, 1), fin = new Date(d.getFullYear(), d.getMonth(), 0);
                return [isoDe(ini), isoDe(fin)];
            case 'anio': return [hoy.slice(0, 4) + '-01-01', hoy];
            case 'anio_ant': var y = d.getFullYear() - 1; return [y + '-01-01', y + '-12-31'];
            default: return ['', ''];
        }
    }

    function crearFiltroLista(spec) {
        var seleccion = new Set(spec.defecto || []);
        var opciones = [];
        var boton = el('button', {type: 'button', class: 'inf-filtro__boton'});
        var panel = el('div', {class: 'inf-filtro__panel'});
        var buscador = el('input', {type: 'search', placeholder: T.buscar, class: 'inf-filtro__buscar'});
        var lista = el('div', {class: 'inf-filtro__lista'});
        panel.appendChild(buscador);
        panel.appendChild(el('div', {class: 'inf-filtro__atajos'}, [
            el('a', {href: '#', text: T.todos, onclick: function (e) { e.preventDefault(); seleccion.clear(); pintarLista(); actualizarBoton(); render(); }}),
        ]));
        panel.appendChild(lista);

        function actualizarBoton() {
            boton.textContent = spec.label + ': ' + (seleccion.size === 0 ? T.todos : (seleccion.size === 1 ? Array.from(seleccion)[0] : seleccion.size + ' ✓'));
            boton.classList.toggle('activo', seleccion.size > 0);
        }

        function pintarLista() {
            lista.innerHTML = '';
            var q = buscador.value.trim().toLowerCase();
            var visibles = opciones.filter(function (o) { return !q || o.toLowerCase().indexOf(q) !== -1; }).slice(0, 400);
            visibles.forEach(function (o) {
                var check = el('input', {type: 'checkbox'});
                check.checked = seleccion.has(o);
                check.addEventListener('change', function () {
                    if (check.checked) seleccion.add(o); else seleccion.delete(o);
                    actualizarBoton(); render();
                });
                lista.appendChild(el('label', {class: 'inf-filtro__opcion'}, [check, ' ' + o]));
            });
        }

        buscador.addEventListener('input', pintarLista);
        boton.addEventListener('click', function (e) {
            e.stopPropagation();
            document.querySelectorAll('.inf-filtro__panel.abierto').forEach(function (p) { if (p !== panel) p.classList.remove('abierto'); });
            panel.classList.toggle('abierto');
            if (panel.classList.contains('abierto')) { pintarLista(); buscador.focus(); }
        });
        panel.addEventListener('click', function (e) { e.stopPropagation(); });

        return {
            spec: spec,
            nodo: el('div', {class: 'inf-filtro'}, [boton, panel]),
            activo: function () { return seleccion.size > 0; },
            pasa: function (fila) {
                var v = fila[spec.col];
                return seleccion.has(v === null || v === undefined || v === '' ? '(vacío)' : String(v));
            },
            cargar: function () { opciones = opcionesDe(spec.col); actualizarBoton(); },
            limpiar: function () { seleccion.clear(); actualizarBoton(); },
        };
    }

    function crearFiltroFechas(spec) {
        var desde = el('input', {type: 'date'});
        var hasta = el('input', {type: 'date'});
        var presets = el('select', {class: 'inf-filtro__preset'});
        [['', 'Todo'], ['hoy', 'Hoy'], ['7d', 'Últimos 7 días'], ['30d', 'Últimos 30 días'], ['mes', 'Este mes'],
         ['mes_ant', 'Mes anterior'], ['anio', 'Este año'], ['anio_ant', 'Año anterior']].forEach(function (p) {
            presets.appendChild(el('option', {value: p[0], text: p[1]}));
        });
        function aplicarPreset(clave) {
            var r = presetFechas(clave);
            desde.value = r[0]; hasta.value = r[1]; presets.value = clave;
        }
        presets.addEventListener('change', function () { aplicarPreset(presets.value); render(); });
        [desde, hasta].forEach(function (i) { i.addEventListener('change', function () { presets.value = ''; render(); }); });
        aplicarPreset(spec.defecto || '');
        return {
            spec: spec,
            nodo: el('div', {class: 'inf-filtro inf-filtro--fechas'}, [el('span', {class: 'inf-filtro__label', text: spec.label}), presets, desde, hasta]),
            activo: function () { return !!(desde.value || hasta.value); },
            pasa: function (fila) {
                var v = fila[spec.col];
                if (!v) return false;
                v = String(v).slice(0, 10);
                return (!desde.value || v >= desde.value) && (!hasta.value || v <= hasta.value);
            },
            cargar: function () {},
            limpiar: function () { aplicarPreset(''); },
        };
    }

    function crearFiltroTexto(spec) {
        var input = el('input', {type: 'search', placeholder: spec.label + '…', class: 'inf-filtro__texto'});
        var temporizador;
        input.addEventListener('input', function () { clearTimeout(temporizador); temporizador = setTimeout(render, 250); });
        return {
            spec: spec,
            nodo: el('div', {class: 'inf-filtro'}, [input]),
            activo: function () { return input.value.trim() !== ''; },
            pasa: function (fila) { return String(fila[spec.col] || '').toLowerCase().indexOf(input.value.trim().toLowerCase()) !== -1; },
            cargar: function () {},
            limpiar: function () { input.value = ''; },
        };
    }

    function crearFiltroRango(spec) {
        var min = el('input', {type: 'number', step: 'any', placeholder: 'mín.'});
        var max = el('input', {type: 'number', step: 'any', placeholder: 'máx.'});
        var defecto = spec.defecto || [null, null];
        function poner() { min.value = defecto[0] === null ? '' : defecto[0]; max.value = defecto[1] === null ? '' : defecto[1]; }
        poner();
        [min, max].forEach(function (i) { i.addEventListener('change', render); });
        return {
            spec: spec,
            nodo: el('div', {class: 'inf-filtro inf-filtro--rango'}, [el('span', {class: 'inf-filtro__label', text: spec.label}), min, max]),
            activo: function () { return min.value !== '' || max.value !== ''; },
            pasa: function (fila) {
                var v = num(fila[spec.col]);
                return (min.value === '' || v >= parseFloat(min.value)) && (max.value === '' || v <= parseFloat(max.value));
            },
            cargar: function () {},
            limpiar: function () { defecto = [null, null]; poner(); },
        };
    }

    function montarFiltros() {
        var cont = document.getElementById('inf-filtros');
        SPEC.filtros.forEach(function (spec) {
            var f = spec.tipo === 'fechas' ? crearFiltroFechas(spec)
                : spec.tipo === 'texto' ? crearFiltroTexto(spec)
                : spec.tipo === 'rango' ? crearFiltroRango(spec)
                : crearFiltroLista(spec);
            FILTROS.push(f);
            cont.appendChild(f.nodo);
        });
        document.addEventListener('click', function () {
            document.querySelectorAll('.inf-filtro__panel.abierto').forEach(function (p) { p.classList.remove('abierto'); });
        });
    }

    function alternarSeleccion(col, gran, valor, etiqueta) {
        var idx = SELECCION.findIndex(function (s) { return s.col === col && s.gran === gran; });
        if (idx !== -1 && SELECCION[idx].valor === valor) SELECCION.splice(idx, 1);
        else if (idx !== -1) SELECCION[idx] = {col: col, gran: gran, valor: valor, etiqueta: etiqueta};
        else SELECCION.push({col: col, gran: gran, valor: valor, etiqueta: etiqueta});
        render();
    }

    function pintarChips() {
        var cont = document.getElementById('inf-chips');
        cont.innerHTML = '';
        SELECCION.forEach(function (s, i) {
            cont.appendChild(el('span', {class: 'inf-chip'}, [
                s.col + ': ' + s.etiqueta,
                el('button', {type: 'button', text: '×', title: 'Quitar', onclick: function () { SELECCION.splice(i, 1); render(); }}),
            ]));
        });
    }

    // ---------------------------------------------------------------- visuales

    function marco(v, clase) {
        var caja = el('section', {class: 'inf-visual inf-visual--' + v.tipo + (v.ancho === 'completo' ? ' inf-visual--completo' : '') + (clase ? ' ' + clase : '')});
        if (v.titulo && v.tipo !== 'kpi') caja.appendChild(el('h3', {class: 'inf-visual__titulo', text: v.titulo}));
        return caja;
    }

    function vacio() { return el('p', {class: 'text-muted inf-vacio', text: T.sinDatos}); }

    function filasVisual(v) {
        var filas = filasFiltradas(v.dataset || SPEC.dataset);
        return v.donde ? aplicarDonde(filas, v.donde) : filas;
    }

    function pintarKpi(v) {
        var filas = filasVisual(v);
        var valor = medir(filas, v.medida, {total: filas});
        var caja = el('section', {class: 'inf-visual inf-kpi' + (v.clase ? ' inf-kpi--' + v.clase : '')});
        caja.appendChild(el('div', {class: 'inf-kpi__valor', text: (valor === null || valor === '') ? '—' : formatear(valor, v.formato || 'int', true)}));
        caja.appendChild(el('div', {class: 'inf-kpi__titulo', text: v.titulo}));
        return caja;
    }

    function serieDe(v, filas) {
        // Devuelve {categorias: [{clave, etiqueta, valores:[...]}], series: [nombres]}
        var gran = v.granularidad;
        var grupos = agrupar(filas, [v.dim], gran);
        var series, categorias;
        if (v.series) {
            var nombresSerie = opcionesDeFilas(filas, v.series);
            series = nombresSerie;
            categorias = grupos.map(function (g) {
                return {
                    clave: g.valores[0],
                    etiqueta: gran ? etiquetaPeriodo(g.valores[0], gran) : g.valores[0],
                    valores: nombresSerie.map(function (s) {
                        var sub = g.filas.filter(function (f) { return valorDim(f, v.series) === s; });
                        return num(medir(sub, v.medidas[0], {total: filas}));
                    }),
                };
            });
        } else {
            series = v.medidas.map(function (m) { return m.label || ''; });
            categorias = grupos.map(function (g) {
                return {
                    clave: g.valores[0],
                    etiqueta: gran ? etiquetaPeriodo(g.valores[0], gran) : g.valores[0],
                    valores: v.medidas.map(function (m) { return num(medir(g.filas, m, {total: filas})); }),
                };
            });
        }
        if (gran) categorias.sort(function (a, b) { return a.clave < b.clave ? -1 : 1; });
        else categorias.sort(function (a, b) { return sumaArr(b.valores) - sumaArr(a.valores); });
        if (v.top && categorias.length > v.top) categorias = categorias.slice(0, v.top);
        return {categorias: categorias, series: series};
    }

    function opcionesDeFilas(filas, col) {
        var s = new Set();
        filas.forEach(function (f) { s.add(valorDim(f, col)); });
        return Array.from(s).sort();
    }

    function sumaArr(a) { return a.reduce(function (x, y) { return x + y; }, 0); }

    function leyenda(series) {
        if (series.length < 2) return null;
        return el('div', {class: 'inf-leyenda'}, series.map(function (s, i) {
            return el('span', {class: 'inf-leyenda__item'}, [el('i', {style: 'background:' + COLORES[i % COLORES.length]}), s]);
        }));
    }

    function pintarBarras(v) {
        var caja = marco(v);
        var datos = serieDe(v, filasVisual(v));
        if (!datos.categorias.length) { caja.appendChild(vacio()); return caja; }
        var max = 0;
        datos.categorias.forEach(function (c) { c.valores.forEach(function (x) { if (Math.abs(x) > max) max = Math.abs(x); }); });
        var lista = el('div', {class: 'inf-barras'});
        datos.categorias.forEach(function (c) {
            var fila = el('div', {class: 'inf-barras__fila', title: c.etiqueta});
            fila.appendChild(el('div', {class: 'inf-barras__etiqueta', text: c.etiqueta}));
            var barras = el('div', {class: 'inf-barras__barras'});
            c.valores.forEach(function (x, i) {
                var ancho = max ? Math.max(1, Math.abs(x) / max * 100) : 0;
                barras.appendChild(el('div', {class: 'inf-barras__linea'}, [
                    el('div', {class: 'inf-barras__barra', style: 'width:' + ancho + '%;background:' + COLORES[i % COLORES.length]}),
                    el('span', {class: 'inf-barras__valor', text: formatear(x, v.formato, true)}),
                ]));
            });
            fila.appendChild(barras);
            fila.addEventListener('click', function () { alternarSeleccion(v.dim, v.granularidad || null, c.clave, c.etiqueta); });
            lista.appendChild(fila);
        });
        caja.appendChild(leyenda(datos.series) || el('span'));
        caja.appendChild(lista);
        return caja;
    }

    function pintarColumnas(v) {
        var caja = marco(v);
        var datos = serieDe(v, filasVisual(v));
        if (!datos.categorias.length) { caja.appendChild(vacio()); return caja; }
        var apilado = !!v.apilado;
        var n = datos.categorias.length;
        var ancho = Math.max(560, n * (apilado ? 26 : 14 * datos.series.length + 10));
        var alto = 240, margenIzq = 58, margenAbajo = 54, margenArriba = 18;
        var max = 0;
        datos.categorias.forEach(function (c) {
            var t = apilado ? sumaArr(c.valores) : Math.max.apply(null, c.valores);
            if (t > max) max = t;
        });
        max = max || 1;
        var svg = svgEl('svg', {viewBox: '0 0 ' + (ancho + margenIzq) + ' ' + (alto + margenAbajo + margenArriba), class: 'inf-columnas', preserveAspectRatio: 'xMinYMin meet'});
        svg.style.minWidth = Math.min(ancho + margenIzq, 1400) + 'px';
        for (var k = 0; k <= 4; k++) {
            var y = margenArriba + alto - alto * k / 4;
            svg.appendChild(svgEl('line', {x1: margenIzq, x2: margenIzq + ancho, y1: y, y2: y, class: 'inf-eje__linea'}));
            var txt = svgEl('text', {x: margenIzq - 6, y: y + 4, 'text-anchor': 'end', class: 'inf-eje__texto'});
            txt.textContent = formatear(max * k / 4, v.formato === 'pct' ? 'pct' : (v.formato === 'eur' ? 'eur' : 'int'), true);
            svg.appendChild(txt);
        }
        var paso = ancho / n;
        var cada = Math.ceil(n / 40);
        datos.categorias.forEach(function (c, i) {
            var x0 = margenIzq + i * paso;
            var g = svgEl('g', {class: 'inf-columnas__grupo'});
            var titulo = svgEl('title', {});
            titulo.textContent = c.etiqueta + '\n' + datos.series.map(function (s, j) { return (s ? s + ': ' : '') + formatear(c.valores[j], v.formato); }).join('\n');
            g.appendChild(titulo);
            if (apilado) {
                var acumulado = 0;
                c.valores.forEach(function (x, j) {
                    var h = alto * x / max;
                    g.appendChild(svgEl('rect', {x: x0 + paso * 0.15, width: paso * 0.7, y: margenArriba + alto - acumulado - h, height: Math.max(0, h), fill: COLORES[j % COLORES.length]}));
                    acumulado += h;
                });
            } else {
                var w = paso * 0.8 / c.valores.length;
                c.valores.forEach(function (x, j) {
                    var h = alto * x / max;
                    g.appendChild(svgEl('rect', {x: x0 + paso * 0.1 + j * w, width: w * 0.92, y: margenArriba + alto - h, height: Math.max(0, h), fill: COLORES[j % COLORES.length]}));
                });
            }
            if (i % cada === 0) {
                var et = svgEl('text', {x: x0 + paso / 2, y: margenArriba + alto + 14, 'text-anchor': 'end', class: 'inf-eje__texto', transform: 'rotate(-40 ' + (x0 + paso / 2) + ' ' + (margenArriba + alto + 14) + ')'});
                et.textContent = c.etiqueta.length > 18 ? c.etiqueta.slice(0, 17) + '…' : c.etiqueta;
                g.appendChild(et);
            }
            g.addEventListener('click', function () { alternarSeleccion(v.dim, v.granularidad || null, c.clave, c.etiqueta); });
            svg.appendChild(g);
        });
        caja.appendChild(leyenda(datos.series) || el('span'));
        caja.appendChild(el('div', {class: 'inf-scroll-x'}, [svg]));
        return caja;
    }

    function pintarTarta(v) {
        var caja = marco(v);
        var filas = filasVisual(v);
        var grupos = agrupar(filas, [v.dim]).map(function (g) { return {clave: g.valores[0], valor: num(medir(g.filas, v.medida, {total: filas}))}; })
            .filter(function (g) { return g.valor > 0; })
            .sort(function (a, b) { return b.valor - a.valor; });
        if (!grupos.length) { caja.appendChild(vacio()); return caja; }
        if (grupos.length > 9) {
            var resto = grupos.slice(8).reduce(function (a, g) { return a + g.valor; }, 0);
            grupos = grupos.slice(0, 8).concat([{clave: 'Otros', valor: resto, otros: true}]);
        }
        var total = grupos.reduce(function (a, g) { return a + g.valor; }, 0);
        var svg = svgEl('svg', {viewBox: '-110 -110 220 220', class: 'inf-tarta'});
        var angulo = -Math.PI / 2;
        grupos.forEach(function (g, i) {
            var frac = g.valor / total;
            var fin = angulo + frac * Math.PI * 2;
            var grande = frac > 0.5 ? 1 : 0;
            var r = 100, ri = 58;
            var d = frac >= 0.9999
                ? 'M 0 -100 A 100 100 0 1 1 -0.01 -100 L -0.01 -58 A 58 58 0 1 0 0 -58 Z'
                : ['M', r * Math.cos(angulo), r * Math.sin(angulo), 'A', r, r, 0, grande, 1, r * Math.cos(fin), r * Math.sin(fin),
                   'L', ri * Math.cos(fin), ri * Math.sin(fin), 'A', ri, ri, 0, grande, 0, ri * Math.cos(angulo), ri * Math.sin(angulo), 'Z'].join(' ');
            var path = svgEl('path', {d: d, fill: COLORES[i % COLORES.length], class: 'inf-tarta__sector'});
            var t = svgEl('title', {}); t.textContent = g.clave + ': ' + formatear(g.valor, v.formato) + ' (' + fmtPct.format(frac) + ')';
            path.appendChild(t);
            if (!g.otros) path.addEventListener('click', function () { alternarSeleccion(v.dim, null, g.clave, g.clave); });
            svg.appendChild(path);
            angulo = fin;
        });
        var centro = svgEl('text', {x: 0, y: 6, 'text-anchor': 'middle', class: 'inf-tarta__total'});
        centro.textContent = formatear(total, v.formato, true);
        svg.appendChild(centro);
        var ley = el('div', {class: 'inf-leyenda inf-leyenda--vertical'}, grupos.map(function (g, i) {
            return el('span', {class: 'inf-leyenda__item', onclick: function () { if (!g.otros) alternarSeleccion(v.dim, null, g.clave, g.clave); }}, [
                el('i', {style: 'background:' + COLORES[i % COLORES.length]}),
                g.clave + ' · ' + formatear(g.valor, v.formato, true) + ' (' + fmtPct.format(g.valor / total) + ')',
            ]);
        }));
        caja.appendChild(el('div', {class: 'inf-tarta__cont'}, [svg, ley]));
        return caja;
    }

    function claseSemaforo(valor, reglas) {
        if (!reglas || valor === null || valor === undefined || valor === '') return '';
        var x = num(valor);
        for (var i = 0; i < reglas.length; i++) {
            var umbral = reglas[i][0], clase = reglas[i][1], op = reglas[i][2] || 'mayor_igual';
            if ((op === 'mayor_igual' && x >= umbral) || (op === 'mayor' && x > umbral) ||
                (op === 'menor' && x < umbral) || (op === 'menor_igual' && x <= umbral)) return 'inf-celda--' + clase;
        }
        return '';
    }

    function tablaInteractiva(caja, columnas, filas, ordenInicial, nombreExport) {
        // columnas: [{col, label, formato, semaforo, signo, marca_vencido}], filas: [{...}]
        var orden = (ordenInicial || []).map(function (o) { return {col: o[0], desc: !!o[1]}; });
        var limite = 200;
        var busqueda = el('input', {type: 'search', placeholder: T.buscar, class: 'inf-tabla__buscar'});
        var contador = el('span', {class: 'text-muted inf-tabla__contador'});
        var exportar = el('button', {type: 'button', class: 'button button--secundario button--peq', text: T.exportar});
        var cont = el('div', {class: 'inf-tabla__cont'});
        var mas = el('button', {type: 'button', class: 'button button--secundario button--peq inf-tabla__mas'});
        var hoy = hoyISO();
        caja.appendChild(el('div', {class: 'inf-tabla__barra'}, [busqueda, contador, exportar]));
        caja.appendChild(cont);
        caja.appendChild(mas);

        function filasVisibles() {
            var q = busqueda.value.trim().toLowerCase();
            var res = q ? filas.filter(function (f) {
                return columnas.some(function (c) { return String(f[c.col] === null || f[c.col] === undefined ? '' : f[c.col]).toLowerCase().indexOf(q) !== -1; });
            }) : filas.slice();
            if (orden.length) {
                res.sort(function (a, b) {
                    for (var i = 0; i < orden.length; i++) {
                        var x = a[orden[i].col], y = b[orden[i].col];
                        if (x === y) continue;
                        if (x === null || x === undefined || x === '') return 1;
                        if (y === null || y === undefined || y === '') return -1;
                        var r = (esNum(x) && esNum(y)) ? x - y : String(x).localeCompare(String(y), 'es', {numeric: true});
                        if (r !== 0) return orden[i].desc ? -r : r;
                    }
                    return 0;
                });
            }
            return res;
        }

        function pintar() {
            var res = filasVisibles();
            contador.textContent = fmtInt.format(res.length) + ' ' + T.filas;
            var tabla = el('table', {class: 'inf-tabla'});
            var thead = el('thead');
            var tr = el('tr');
            columnas.forEach(function (c) {
                var o = orden.length && orden[0].col === c.col ? (orden[0].desc ? ' ▼' : ' ▲') : '';
                var th = el('th', {text: (c.label || c.col) + o, class: c.formato && c.formato !== 'texto' && c.formato !== 'fecha' ? 'num' : ''});
                th.addEventListener('click', function () {
                    if (orden.length && orden[0].col === c.col) orden[0].desc = !orden[0].desc;
                    else orden = [{col: c.col, desc: !!(c.formato && c.formato !== 'texto' && c.formato !== 'fecha')}];
                    pintar();
                });
                tr.appendChild(th);
            });
            thead.appendChild(tr);
            tabla.appendChild(thead);
            var tbody = el('tbody');
            res.slice(0, limite).forEach(function (f) {
                var fila = el('tr');
                columnas.forEach(function (c) {
                    var v = f[c.col];
                    var clase = (c.formato && c.formato !== 'texto' && c.formato !== 'fecha' ? 'num ' : '') + claseSemaforo(v, c.semaforo);
                    if (c.signo && esNum(v)) clase += v < 0 ? ' inf-celda--rojo' : (v > 0 ? ' inf-celda--verde' : '');
                    if (c.marca_vencido && v) clase += String(v).slice(0, 10) < hoy ? ' inf-celda--rojo' : ' inf-celda--verde';
                    fila.appendChild(el('td', {class: clase, text: formatear(v, c.formato), title: v === null || v === undefined ? '' : String(v)}));
                });
                tbody.appendChild(fila);
            });
            tabla.appendChild(tbody);
            cont.innerHTML = '';
            cont.appendChild(res.length ? tabla : vacio());
            mas.style.display = res.length > limite ? '' : 'none';
            mas.textContent = '+ ' + fmtInt.format(Math.min(500, res.length - limite)) + ' (' + fmtInt.format(res.length - limite) + ')';
        }

        var temporizador;
        busqueda.addEventListener('input', function () { clearTimeout(temporizador); temporizador = setTimeout(pintar, 200); });
        mas.addEventListener('click', function () { limite += 500; pintar(); });
        exportar.addEventListener('click', function () { exportarCsv(columnas, filasVisibles(), nombreExport); });
        pintar();
    }

    function exportarCsv(columnas, filas, nombre) {
        var sep = ';';
        function celda(v) {
            if (v === null || v === undefined) return '';
            if (esNum(v)) return String(v).replace('.', ',');
            var s = String(v);
            return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        }
        var lineas = [columnas.map(function (c) { return celda(c.label || c.col); }).join(sep)];
        filas.forEach(function (f) { lineas.push(columnas.map(function (c) { return celda(f[c.col]); }).join(sep)); });
        var blob = new Blob(['﻿' + lineas.join('\r\n')], {type: 'text/csv;charset=utf-8'});
        var a = el('a', {href: URL.createObjectURL(blob), download: (nombre || 'informe') + '.csv'});
        document.body.appendChild(a); a.click(); a.remove();
    }

    function pintarTabla(v) {
        var caja = marco(v);
        tablaInteractiva(caja, v.columnas, filasVisual(v), v.orden, SPEC.slug);
        return caja;
    }

    function pintarResumen(v) {
        var caja = marco(v);
        var filas = filasVisual(v);
        var grupos = agrupar(filas, v.dims);
        var columnas = v.dims.map(function (d) { return {col: d, label: d === 'FECHA' ? 'Fecha' : d, formato: d.toUpperCase().indexOf('FECHA') !== -1 ? 'fecha' : 'texto'}; });
        v.medidas.forEach(function (m) { columnas.push({col: m.label, label: m.label, formato: m.formato || v.formato || 'int'}); });
        var res = grupos.map(function (g) {
            var o = {};
            v.dims.forEach(function (d, i) { o[d] = g.valores[i]; });
            v.medidas.forEach(function (m) { o[m.label] = medir(g.filas, m, {total: filas}); });
            return o;
        });
        if (v.ranking && v.medidas.length) {
            var clave = v.medidas[0].label;
            var valores = Array.from(new Set(res.map(function (r) { return num(r[clave]); }))).sort(function (a, b) { return b - a; });
            res.forEach(function (r) { r['Ranking'] = valores.indexOf(num(r[clave])) + 1; });
            columnas.unshift({col: 'Ranking', label: '#', formato: 'int'});
        }
        tablaInteractiva(caja, columnas, res, v.orden || [[v.medidas[0].label, true]], SPEC.slug + '_' + slugTexto(v.titulo));
        return caja;
    }

    function slugTexto(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g, '_'); }

    function pintarMatriz(v) {
        var caja = marco(v);
        var filas = filasVisual(v);
        if (!filas.length) { caja.appendChild(vacio()); return caja; }
        var gran = v.granularidad;
        var columnasClaves = Array.from(new Set(filas.map(function (f) { return valorDim(f, v.columnas, gran); }))).sort();
        if (columnasClaves.length > 40) columnasClaves = columnasClaves.slice(-40);
        var grupos = agrupar(filas, [v.filas]);
        var res = grupos.map(function (g) {
            var o = {};
            o[v.filas] = g.valores[0];
            columnasClaves.forEach(function (c) {
                var sub = g.filas.filter(function (f) { return valorDim(f, v.columnas, gran) === c; });
                o[c] = sub.length ? num(medir(sub, v.medida, {total: filas})) : null;
            });
            o.__total = num(medir(g.filas, v.medida, {total: filas}));
            return o;
        });
        var columnas = [{col: v.filas, label: v.filas, formato: 'texto'}].concat(columnasClaves.map(function (c) {
            return {col: c, label: gran ? etiquetaPeriodo(c, gran) : c, formato: v.formato};
        })).concat([{col: '__total', label: 'Total', formato: v.formato}]);
        tablaInteractiva(caja, columnas, res, [['__total', true]], SPEC.slug + '_' + slugTexto(v.titulo));
        return caja;
    }

    var PINTORES = {
        kpi: pintarKpi, barras: pintarBarras, columnas: pintarColumnas, tarta: pintarTarta,
        tabla: pintarTabla, resumen: pintarResumen, matriz: pintarMatriz,
    };

    function render() {
        if (!Object.keys(DATOS).length) return;
        pintarChips();
        var cont = document.getElementById('inf-visuales');
        cont.innerHTML = '';
        var filaKpis = null;
        SPEC.visuales.forEach(function (v) {
            if (v.dataset && !DATOS[v.dataset]) return;
            var nodo;
            try {
                nodo = PINTORES[v.tipo](v);
            } catch (err) {
                console.error(v, err);
                nodo = marco(v);
                nodo.appendChild(el('p', {class: 'inf-error', text: String(err)}));
            }
            if (v.tipo === 'kpi') {
                if (!filaKpis) { filaKpis = el('div', {class: 'inf-kpis'}); cont.appendChild(filaKpis); }
                filaKpis.appendChild(nodo);
            } else {
                filaKpis = null;
                cont.appendChild(nodo);
            }
        });
    }

    // ------------------------------------------------------------------ carga

    function decodificar(ds) {
        var cols = ds.columns || [];
        var dicts = ds.dicts || {};
        var indices = Object.keys(dicts).map(Number);
        var filas = (ds.rows || []).map(function (r) {
            var o = {};
            for (var i = 0; i < cols.length; i++) o[cols[i]] = r[i];
            for (var j = 0; j < indices.length; j++) {
                var k = indices[j];
                o[cols[k]] = dicts[k][r[k]];
            }
            return o;
        });
        return {columnas: cols, filas: filas, actualizado: ds.updated_at};
    }

    function cargar(refrescar) {
        var estado = document.getElementById('inf-estado');
        estado.textContent = T.cargando;
        estado.className = 'informe__estado';
        estado.style.display = '';
        var botones = document.querySelectorAll('.informe__acciones button');
        botones.forEach(function (b) { b.disabled = true; });
        fetch(CFG.datosUrl + (refrescar ? '?refrescar=1' : ''), {credentials: 'same-origin'})
            .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, status: r.status, json: j}; }); })
            .then(function (res) {
                if (!res.ok) {
                    var e = res.json.error || '';
                    throw new Error(e === 'node_offline' || e === 'no_node_configured' ? T.errorOffline : T.error + ' (' + e + ')');
                }
                DATOS = {};
                var fechas = [];
                Object.keys(res.json.datasets).forEach(function (nombre) {
                    DATOS[nombre] = decodificar(res.json.datasets[nombre]);
                    if (DATOS[nombre].actualizado) fechas.push(DATOS[nombre].actualizado);
                });
                document.getElementById('inf-actualizado').textContent = fechas.length ? fechas.sort()[0] : new Date().toLocaleString('es-ES');
                var errores = res.json.errores || {};
                if (Object.keys(errores).length) {
                    estado.textContent = T.error + ': ' + Object.keys(errores).map(function (k) { return k + ' (' + errores[k] + ')'; }).join(', ');
                    estado.className = 'informe__estado informe__estado--error';
                } else {
                    estado.style.display = 'none';
                }
                FILTROS.forEach(function (f) { f.cargar(); });
                render();
            })
            .catch(function (err) {
                estado.textContent = err.message;
                estado.className = 'informe__estado informe__estado--error';
            })
            .finally(function () { botones.forEach(function (b) { b.disabled = false; }); });
    }

    montarFiltros();
    document.getElementById('inf-actualizar').addEventListener('click', function () { cargar(false); });
    document.getElementById('inf-recargar').addEventListener('click', function () { cargar(true); });
    document.getElementById('inf-limpiar').addEventListener('click', function () {
        FILTROS.forEach(function (f) { f.limpiar(); });
        SELECCION = [];
        render();
    });
    cargar(false);
})();
