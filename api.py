"""
API endpoint para Railway - LD Wealth Management
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
import threading
import os
import requests as req

app = Flask(__name__)
CORS(app)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path=''):
    response = app.make_default_options_response()
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

def ensure_credentials():
    creds_env = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_env:
        with open('credentials.json', 'w') as f:
            f.write(creds_env)
        return True
    return os.path.exists('credentials.json')

def run_async(coro):
    result = {}
    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result['value'] = loop.run_until_complete(coro)
            result['ok'] = True
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)
        finally:
            loop.close()
    t = threading.Thread(target=target)
    t.start()
    t.join()
    return result

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'ldwm-api'})

@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    try:
        if not ensure_credentials():
            return jsonify({'ok': False, 'msg': 'No se encontro GOOGLE_CREDENTIALS.'}), 500
        from borkse import main as scrape_main
        result = run_async(scrape_main())
        if result.get('ok'):
            return jsonify({'ok': True, 'msg': 'Scraper completado.'})
        return jsonify({'ok': False, 'msg': result.get('error', 'Error desconocido')}), 500
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500

@app.route('/api/bonds', methods=['GET'])
def api_bonds():
    try:
        if not ensure_credentials():
            return jsonify({'ok': False, 'msg': 'No se encontro GOOGLE_CREDENTIALS.'}), 500
        from dashboard import load_bonds, process_bonds, fetch_treasury_yields
        try:
            tsy = fetch_treasury_yields()
        except RuntimeError as e:
            return jsonify({
                'ok': False,
                'msg': f'No se pudieron obtener yields reales del Tesoro: {e}. '
                       'Configurar FMP_API_KEY en Railway.'
            }), 503
        raw = load_bonds()
        bonds = process_bonds(raw, tsy)
        return jsonify(bonds)
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500

@app.route('/api/market', methods=['GET'])
def api_market():
    from urllib.parse import unquote
    tickers_param = request.args.get('tickers', '')
    if not tickers_param:
        return jsonify({'ok': False, 'msg': 'No tickers provided'}), 400
    tickers_param = unquote(tickers_param)
    tickers = [t.strip() for t in tickers_param.split(',') if t.strip()]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
        'Accept': 'application/json',
    }
    results = {}
    for ticker in tickers:
        data = None
        urls = [
            f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d',
            f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d',
            f'https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}',
        ]
        for url in urls:
            try:
                r = req.get(url, headers=headers, timeout=12)
                if r.status_code != 200:
                    continue
                d = r.json()
                if 'chart' in d:
                    res = (d.get('chart') or {}).get('result') or []
                    if res:
                        meta   = res[0]['meta']
                        price  = meta.get('regularMarketPrice') or meta.get('previousClose')
                        prev   = meta.get('chartPreviousClose') or meta.get('previousClose') or price
                        chg    = ((price - prev) / prev * 100) if (prev and price) else 0
                        q0     = ((res[0].get('indicators') or {}).get('quote') or [{}])[0]
                        closes = [v for v in (q0.get('close') or []) if v is not None]
                        data   = {'price': round(float(price), 6), 'chg': round(float(chg), 4), 'closes': closes[-50:]}
                        break
                elif 'quoteResponse' in d:
                    qs = (d.get('quoteResponse') or {}).get('result') or []
                    if qs:
                        q = qs[0]
                        price = q.get('regularMarketPrice')
                        chg   = q.get('regularMarketChangePercent') or 0
                        data  = {'price': round(float(price), 6) if price else None, 'chg': round(float(chg), 4), 'closes': []}
                        break
            except Exception:
                continue
        results[ticker] = data
    return jsonify({'ok': True, 'data': results})

def fetch_market_snapshot():
    tickers = {
        'SP500': '^GSPC', 'NASDAQ': '^IXIC', 'DOW': '^DJI',
        'VIX': '^VIX', 'MERVAL': '^MERV',
        'BRENT': 'BZ=F', 'WTI': 'CL=F', 'GOLD': 'GC=F', 'NATGAS': 'NG=F',
        'DXY': 'DX-Y.NYB', 'UST2Y': '^IRX', 'UST10Y': '^TNX', 'BTC': 'BTC-USD',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = {}
    for name, ticker in tickers.items():
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d'
            r = req.get(url, headers=headers, timeout=8)
            meta  = r.json()['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
            prev  = meta.get('previousClose') or price
            chg   = ((price - prev) / prev * 100) if prev else 0
            results[name] = {'price': round(price, 2), 'chg': round(chg, 2)}
        except Exception:
            results[name] = {'price': 'N/D', 'chg': 0}
    return results

_PARTE_CACHE = {}  # {'date': str, 'genTime': str, 'data': dict}

def _parte_cache_today():
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    return _PARTE_CACHE if _PARTE_CACHE.get('date') == today else None

@app.route('/api/parte/status', methods=['GET'])
def api_parte_status():
    from datetime import datetime
    cached = _parte_cache_today()
    return jsonify({'ok': True, 'cached': cached is not None,
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'genTime': cached['genTime'] if cached else None})

@app.route('/api/parte', methods=['GET', 'POST'])
def api_parte():
    # Devolver cache del día si existe
    cached = _parte_cache_today()
    if cached:
        return jsonify({'ok': True, 'data': cached['data'],
                        'cached': True, 'genTime': cached['genTime']})
    try:
        import anthropic, json
        from datetime import datetime
        fecha = datetime.now().strftime('%A %d de %B de %Y')
        mkt   = fetch_market_snapshot()
        def fmt(k):
            v = mkt.get(k, {})
            p = v.get('price', 'N/D')
            c = v.get('chg', 0)
            return f"{p} ({'+' if c > 0 else ''}{c}%)"
        market_context = f"""
DATOS DE MERCADO ({fecha}):
S&P 500: {fmt('SP500')} | Nasdaq: {fmt('NASDAQ')} | Dow: {fmt('DOW')} | VIX: {fmt('VIX')}
Merval: {fmt('MERVAL')} | Brent: {fmt('BRENT')} | WTI: {fmt('WTI')} | Oro: {fmt('GOLD')}
Gas: {fmt('NATGAS')} | DXY: {fmt('DXY')} | UST2Y: {fmt('UST2Y')} | UST10Y: {fmt('UST10Y')} | BTC: {fmt('BTC')}
"""
        prompt = f"""Sos el analista financiero senior de LD Wealth Management.
Genera el Parte Diario de hoy ({fecha}) usando SOLO estos datos reales:
{market_context}
Responde SOLO con JSON con estas 12 claves (array de 4-8 strings c/u):
claves, senales, flash, panorama, fed, fiscal, comercio, geo, usa, latam, argentina, ldwm
Sin texto extra, sin backticks."""
        client  = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model='claude-opus-4-5', max_tokens=4000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw   = message.content[0].text.strip().replace('```json','').replace('```','').strip()
        parte = json.loads(raw)
        # Guardar en cache del día
        gen_time = datetime.now().strftime('%H:%M')
        _PARTE_CACHE.clear()
        _PARTE_CACHE['date']    = datetime.now().strftime('%Y-%m-%d')
        _PARTE_CACHE['genTime'] = gen_time
        _PARTE_CACHE['data']    = parte
        return jsonify({'ok': True, 'data': parte, 'cached': False, 'genTime': gen_time})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


# ── /api/fci/* ─────────────────────────────────────────────────────────────────
# Fuente: api.argentinadatos.com (pública, sin auth, datos de CAFCI)
# Endpoints base: /v1/finanzas/fci/{tipo}/{fecha}  fecha = "ultimo" o "YYYY/MM/DD"
# Tipos: mercadoDinero, rentaFija, rentaVariable, rentaMixta, otros
# Respuesta: [{fondo, fecha, vcp, ccp, patrimonio, horizonte}]
# ──────────────────────────────────────────────────────────────────────────────

_AD_BASE  = 'https://api.argentinadatos.com/v1/finanzas/fci'
_AD_TIPOS = ['mercadoDinero', 'rentaFija', 'rentaVariable', 'rentaMixta', 'otros']
_AD_H     = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

def _safe_float(v):
    try:
        return round(float(v), 6) if v not in (None, '', 'N/A') else None
    except Exception:
        return None

# Cache: fecha_str -> {nombre_lower -> {fondo,fecha,vcp,patrimonio,horizonte}}
_AD_CACHE     = {}   # fecha_str -> fondos_dict
_AD_CACHE = {}   # 'ultimo'|'penultimo' -> {nombre_lower -> fondo_dict}
_AD_TS    = {}   # -> timestamp

def _load_ad(slot='ultimo'):
    """Carga todos los tipos de FCI para ultimo o penultimo. Cachea 4h."""
    import time
    now = time.time()
    if slot in _AD_CACHE and now - _AD_TS.get(slot, 0) < 4 * 3600:
        return _AD_CACHE[slot]
    fondos = {}
    for tipo in _AD_TIPOS:
        try:
            r = req.get(f'{_AD_BASE}/{tipo}/{slot}', timeout=15, headers=_AD_H)
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue
            for it in items:
                nombre = str(it.get('fondo') or '').strip()
                vcp    = _safe_float(it.get('vcp'))
                if not nombre or vcp is None:
                    continue
                fondos[nombre.lower()] = {
                    'nombre':     nombre,
                    'tipo':       tipo,
                    'fecha':      str(it.get('fecha') or ''),
                    'vcp':        vcp,
                    'patrimonio': _safe_float(it.get('patrimonio')),
                    'horizonte':  str(it.get('horizonte') or ''),
                }
        except Exception:
            continue
    _AD_CACHE[slot] = fondos
    _AD_TS[slot]    = now
    return fondos


def _find(fondos, query):
    """Busca fondo por nombre: exacto, prefijo, o contiene."""
    ql = query.strip().lower()
    if ql in fondos:
        return fondos[ql]
    starts = [f for k, f in fondos.items() if k.startswith(ql)]
    if starts:
        return starts[0]
    contains = [f for k, f in fondos.items() if ql in k]
    return contains[0] if contains else None

def _calc_rendimientos(nombre, vcp_hoy):
    """
    Rendimiento diario: ArgentinaDatos /ultimo vs /penultimo.
    Rendimientos semana/mes/YTD/año: desde Google Sheets.
    """
    from datetime import date, timedelta

    if not vcp_hoy:
        print(f'[rendimientos] "{nombre}" vcp_hoy es None/0 — no se puede calcular')
        return {'day': None, 'week': None, 'month': None, 'ytd': None, 'year': None}

    # Diario desde penultimo
    rend_day = None
    try:
        penult = _load_ad('penultimo')
        fp = _find(penult, nombre)
        if fp and fp.get('vcp'):
            rend_day = round((vcp_hoy / fp['vcp'] - 1) * 100, 4)
            print(f'[rendimientos] "{nombre}" day={rend_day}% (hoy={vcp_hoy} / ayer={fp["vcp"]})')
        else:
            print(f'[rendimientos] "{nombre}" no encontrado en penultimo — day=None')
    except Exception as e:
        print(f'[rendimientos] "{nombre}" error calculando day: {e}')

    # Historicos desde Google Sheets
    today_s = date.today().strftime('%Y-%m-%d')
    today_d = date.today()

    def rend_desde(target_str):
        try:
            series = _gs_read_series(nombre, target_str, today_s)
            if not series:
                return None
            base_vcp = series[0]['vcp']
            return round((vcp_hoy / base_vcp - 1) * 100, 4) if base_vcp else None
        except Exception:
            return None

    return {
        'day':   rend_day,
        'week':  rend_desde((today_d - timedelta(days=7)).strftime('%Y-%m-%d')),
        'month': rend_desde((today_d - timedelta(days=30)).strftime('%Y-%m-%d')),
        'ytd':   rend_desde(f'{today_d.year}-01-01'),
        'year':  rend_desde((today_d - timedelta(days=365)).strftime('%Y-%m-%d')),
    }


_REND_CACHE = {}

def _calc_rendimientos_from_sheet(nombre):
    """
    Calcula todos los rendimientos usando solo datos del sheet.
    El ultimo punto del sheet actua como valor de hoy.
    """
    from datetime import datetime, timedelta

    series = _gs_read_series(nombre, '1970-01-01', '9999-12-31')
    if not series:
        return {'day': None, 'week': None, 'month': None, 'ytd': None, 'year': None}

    last       = series[-1]
    vcp_ultimo = last['vcp']
    ultima_dt  = datetime.strptime(last['fecha'], '%Y-%m-%d')

    rend_day = None
    if len(series) >= 2:
        prev = series[-2]
        if prev['vcp']:
            rend_day = round((vcp_ultimo / prev['vcp'] - 1) * 100, 4)

    def rend_desde_fecha(target_str):
        candidates = [p for p in series if p['fecha'] <= target_str]
        if not candidates:
            return None
        base_vcp = candidates[-1]['vcp']
        return round((vcp_ultimo / base_vcp - 1) * 100, 4) if base_vcp else None

    return {
        'day':   rend_day,
        'week':  rend_desde_fecha((ultima_dt - timedelta(days=7)).strftime('%Y-%m-%d')),
        'month': rend_desde_fecha((ultima_dt - timedelta(days=30)).strftime('%Y-%m-%d')),
        'ytd':   rend_desde_fecha(f'{ultima_dt.year}-01-01'),
        'year':  rend_desde_fecha((ultima_dt - timedelta(days=365)).strftime('%Y-%m-%d')),
    }

def _calc_rendimientos_cached(nombre):
    import time
    key = nombre.lower()
    now = time.time()
    cached = _REND_CACHE.get(key)
    if cached and now - cached['ts'] < 4 * 3600:
        return cached['data']
    data = _calc_rendimientos_from_sheet(nombre)
    _REND_CACHE[key] = {'data': data, 'ts': now}
    return data



# ── Google Sheets histórico de VCPs ───────────────────────────────────────────
# Sheet: "FCI Historico" con columnas A=fecha, B=nombre, C=vcp
# Se crea automáticamente si no existe.

_GS_SHEET_NAME = 'FCI Historico'
_GS_WS_NAME    = 'vcps'
_GS_CLIENT_CACHE = {}   # {'client': ..., 'ws': ..., 'ts': float}
_GS_DATA_CACHE   = {}   # {'header': [...], 'rows': [...], 'ts': float}

def _gs_client():
    """Retorna gspread client autenticado, cacheado 1h."""
    import time
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    now = time.time()
    if _GS_CLIENT_CACHE.get('ts', 0) and now - _GS_CLIENT_CACHE['ts'] < 3600:
        return _GS_CLIENT_CACHE['client']
    ensure_credentials()
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    _GS_CLIENT_CACHE['client'] = client
    _GS_CLIENT_CACHE['ts'] = now
    return client

def _gs_get_ws():
    """Abre o crea el worksheet pivot (fechas x fondos)."""
    client = _gs_client()
    try:
        sh = client.open(_GS_SHEET_NAME)
    except Exception:
        sh = client.create(_GS_SHEET_NAME)
        # Compartir con cualquiera que tenga el link (lectura)
        sh.share('', perm_type='anyone', role='reader')
    try:
        ws = sh.worksheet(_GS_WS_NAME)
    except Exception:
        # Crear con suficientes filas/cols: 5000 dias x 4000 fondos
        ws = sh.add_worksheet(_GS_WS_NAME, rows=2500, cols=3500)
    return ws

def _gs_write_snapshot():
    """
    Escribe una nueva fila con los VCPs de hoy en el Sheet pivot.
    Fila 1 = header: [fecha, Fondo1, Fondo2, ...]
    Fila 2+ = datos: [YYYY-MM-DD, vcp1, vcp2, ...]
    Nunca sobreescribe filas existentes.
    """
    from datetime import date
    today = date.today().strftime('%Y-%m-%d')

    fondos = _load_ad('ultimo')
    if not fondos:
        return 0, 'No se pudo cargar fondos de ArgentinaDatos'

    nombres_hoy = {f['nombre']: f['vcp'] for f in fondos.values() if f.get('vcp') is not None}

    ws = _gs_get_ws()

    # Leer TODO el sheet de una sola vez para evitar multiples requests
    all_values = ws.get_all_values()

    # Extraer header (fila 1) — filtrar celdas vacias del final
    if all_values and any(c.strip() for c in all_values[0]):
        header_row = all_values[0]
        # Strip trailing empty cells
        while header_row and header_row[-1] == '':
            header_row = header_row[:-1]
    else:
        header_row = []

    # Chequear si ya existe la fecha de hoy en alguna fila de datos
    for row in all_values[1:]:
        if row and row[0] == today:
            return 0, f'Ya existe snapshot para {today}'

    if not header_row:
        # Primera vez: escribir header en fila 1
        header_row = ['fecha'] + sorted(nombres_hoy.keys())
        ws.update('A1', [header_row])
    else:
        # Detectar fondos nuevos y agregarlos al final del header
        fondos_en_header = set(header_row[1:])
        fondos_nuevos = [n for n in sorted(nombres_hoy.keys()) if n not in fondos_en_header]
        if fondos_nuevos:
            new_header = header_row + fondos_nuevos
            # Solo actualizar las celdas nuevas del header, no reescribir todo
            col_start = len(header_row) + 1  # 1-indexed
            import gspread.utils as gu
            col_letter = gu.rowcol_to_a1(1, col_start).rstrip('1')
            ws.update(f'{col_letter}1', [fondos_nuevos])
            header_row = new_header

    # Construir fila de hoy alineada con el header
    fila = [today] + [
        nombres_hoy.get(nombre, '') for nombre in header_row[1:]
    ]

    # Append como nueva fila al final
    ws.append_row(fila, value_input_option='RAW', insert_data_option='INSERT_ROWS')

    _GS_DATA_CACHE.clear()
    return len(nombres_hoy), 'ok'


def _parse_vcp(val):
    """
    Convierte string de VCP a float manejando separadores europeos/argentinos.
    '208749,292'  -> 208749.292  (coma como decimal)
    '1.208.749,29' -> 1208749.29  (punto miles, coma decimal)
    '208749.292'  -> 208749.292  (punto como decimal, pasa directo)
    """
    s = str(val).strip()
    if not s:
        return None
    if ',' in s and '.' not in s:
        # Solo comas: la coma ES el separador decimal
        s = s.replace(',', '.')
    elif ',' in s and '.' in s:
        # Ambos: punto = miles, coma = decimal (formato europeo)
        s = s.replace('.', '').replace(',', '.')
    # Si solo tiene punto o ninguno: float() lo maneja directo
    return float(s)


def _gs_read_series(nombre, desde, hasta):
    """
    Lee serie historica [{fecha, vcp}] para un fondo desde el Sheet pivot.
    Cachea todos los datos del sheet por 1h para no hacer multiples lecturas.
    """
    import time
    now = time.time()

    # Cache de todos los datos del sheet
    if not _GS_DATA_CACHE or now - _GS_DATA_CACHE.get('ts', 0) > 3600:
        try:
            ws = _gs_get_ws()
            all_data = ws.get_all_values()
            if not all_data or len(all_data) < 2:
                _GS_DATA_CACHE.update({'header': [], 'rows': [], 'ts': now})
            else:
                _GS_DATA_CACHE.update({
                    'header': all_data[0],
                    'rows':   all_data[1:],
                    'ts':     now,
                })
        except Exception as e:
            print(f'[_gs_read_series] ERROR cargando sheet: {e}')
            return []

    header = _GS_DATA_CACHE.get('header', [])
    rows   = _GS_DATA_CACHE.get('rows', [])

    if not header:
        print(f'[_gs_read_series] Header vacio — sheet sin datos')
        return []

    # Buscar columna tolerando espacios extra y case
    col_idx = None
    nombre_norm = nombre.strip().lower()
    for i, h in enumerate(header):
        if h.strip().lower() == nombre_norm:
            col_idx = i
            break

    if col_idx is None:
        # Log para debug: mostrar primeros headers disponibles
        sample = [h for h in header[:10] if h]
        print(f'[_gs_read_series] "{nombre}" no encontrado en header. Muestra: {sample}')
        return []

    seen_fechas = set()
    series = []
    parse_errors = 0
    for row in rows:
        if len(row) <= col_idx:
            continue
        fecha = row[0].strip()
        if not fecha or not (desde <= fecha <= hasta):
            continue
        if fecha in seen_fechas:
            continue  # deduplicar fines de semana/feriados
        val = row[col_idx]
        if val == '':
            continue
        try:
            vcp = _parse_vcp(val)
            if vcp is None:
                continue
            series.append({'fecha': fecha, 'vcp': vcp})
            seen_fechas.add(fecha)
        except Exception:
            parse_errors += 1
            continue

    print(f'[_gs_read_series] "{nombre}" | {desde}→{hasta} | {len(series)} puntos | {parse_errors} errores de parse')
    return series



@app.route('/api/fci/tick', methods=['GET', 'POST'])
def api_fci_tick():
    """Guarda snapshot diario de VCPs en Google Sheets. Llamar 1 vez por dia."""
    try:
        count, msg = _gs_write_snapshot()
        return jsonify({'ok': True, 'fondos_guardados': count, 'msg': msg})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/search', methods=['GET'])
def api_fci_search():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify({'ok': False, 'msg': 'q requerido (min 2 chars)'}), 400
    try:
        fondos = _load_ad('ultimo')
        results = []
        for k, f in fondos.items():
            if q in k:
                results.append({
                    'fondoId':    abs(hash(f['nombre'])) % 10000000,
                    'claseId':    abs(hash(f['nombre'])) % 10000000,
                    'nombre':     f['nombre'],
                    'gerente':    '',
                    'tipo':       f['horizonte'] or f['tipo'],
                    'moneda':     'ARS',
                    'vcp':        f['vcp'],
                    'patrimonio': f['patrimonio'],
                    'rendimientos': {'day': None, 'week': None, 'month': None, 'ytd': None, 'year': None},
                })
        results.sort(key=lambda x: (0 if x['nombre'].lower().startswith(q) else 1, x['nombre']))
        return jsonify({'ok': True, 'data': results[:40], 'total': len(fondos)})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/ficha', methods=['GET'])
def api_fci_ficha():
    nombre_q = request.args.get('nombre', '').strip()
    if not nombre_q:
        return jsonify({'ok': False, 'msg': 'Pasar ?nombre=<nombre del fondo>'}), 400
    try:
        # Resolver nombre exacto y metadata (tipo, patrimonio) desde ArgentinaDatos
        fondos = _load_ad('ultimo')
        f = _find(fondos, nombre_q)
        nombre_real = f['nombre'] if f else nombre_q

        # VCP y rendimientos: solo desde el sheet
        last_row = _gs_read_series(nombre_real, '1970-01-01', '9999-12-31')
        if not last_row:
            return jsonify({'ok': False, 'msg': 'Fondo no encontrado en el sheet historico'}), 404
        vcp_sheet = last_row[-1]['vcp']

        hist = _calc_rendimientos_cached(nombre_real)
        return jsonify({'ok': True, 'data': {
            'fondoId':    abs(hash(nombre_real)) % 10000000,
            'claseId':    abs(hash(nombre_real)) % 10000000,
            'nombre':     nombre_real,
            'gerente':    '',
            'tipo':       (f['horizonte'] or f['tipo']) if f else '',
            'moneda':     'ARS',
            'vcp':        vcp_sheet,
            'patrimonio': f['patrimonio'] if f else None,
            'rendimientos': hist,
        }})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/historico', methods=['GET'])
def api_fci_historico():
    """Serie historica de VCP desde Google Sheets."""
    nombre_q = request.args.get('nombre', '').strip()
    from_d   = request.args.get('desde', '').strip()
    to_d     = request.args.get('hasta', '').strip()
    if not nombre_q or not from_d or not to_d:
        return jsonify({'ok': False, 'msg': 'nombre, desde y hasta requeridos'}), 400
    try:
        fondos = _load_ad('ultimo')
        f = _find(fondos, nombre_q)
        nombre_real = f['nombre'] if f else nombre_q

        series = _gs_read_series(nombre_real, from_d, to_d)
        return jsonify({'ok': True, 'data': series})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/debug', methods=['GET'])
def api_fci_debug():
    try:
        fondos_u = _load_ad('ultimo')
        fondos_p = _load_ad('penultimo')
        sample   = list(fondos_u.values())[:3]
        rend_test = None
        if sample:
            fp = _find(fondos_p, sample[0]['nombre'])
            if fp and fp.get('vcp') and sample[0].get('vcp'):
                rend_test = round((sample[0]['vcp'] / fp['vcp'] - 1) * 100, 4)
        # Test sheets connection + leer header real
        gs_status = 'not tested'
        sheet_headers = []
        sheet_fechas  = []
        try:
            ws     = _gs_get_ws()
            all_v  = ws.get_all_values()
            n_rows = len(all_v)
            gs_status     = f'ok - {n_rows} filas en sheet'
            sheet_headers = all_v[0] if all_v else []
            # Primeras y últimas fechas de datos
            fechas = [r[0] for r in all_v[1:] if r and r[0].strip()]
            sheet_fechas = {
                'primera': fechas[0]  if fechas else None,
                'ultima':  fechas[-1] if fechas else None,
                'total':   len(fechas),
            }
        except Exception as e:
            gs_status = f'error: {e}'
        return jsonify({
            'ok': True,
            'fondos_ultimo':    len(fondos_u),
            'fondos_penultimo': len(fondos_p),
            'rend_diario_test': rend_test,
            'google_sheets':    gs_status,
            'sheet_fechas':     sheet_fechas,
            'sheet_headers_total': len(sheet_headers),
            'sheet_headers_muestra': sheet_headers[1:11],  # primeros 10 fondos (sin col fecha)
            'sample': [{'nombre': f['nombre'], 'vcp': f['vcp'], 'fecha': f['fecha']} for f in sample],
            'tip': 'Llamar POST /api/fci/tick una vez por dia para acumular historico en Google Sheets',
        })
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/debug/nombre', methods=['GET'])
def api_fci_debug_nombre():
    """
    Diagnostica por qué un nombre no matchea en el sheet.
    GET /api/fci/debug/nombre?q=Fima%20Ahorro%20Plus%20-%20Clase%20C
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': False, 'msg': 'Pasar ?q=nombre'}), 400
    try:
        # Invalidar cache para leer fresco
        _GS_DATA_CACHE.clear()
        ws       = _gs_get_ws()
        all_data = ws.get_all_values()
        if not all_data:
            return jsonify({'ok': False, 'msg': 'Sheet vacío'}), 404

        header = all_data[0]
        rows   = all_data[1:]

        # Búsqueda exacta
        exacto = q in header

        # Búsqueda normalizada
        q_norm = q.strip().lower()
        matches_norm = [h for h in header if h.strip().lower() == q_norm]

        # Búsqueda parcial
        matches_partial = [h for h in header if q_norm in h.strip().lower()]

        # Si hay match, contar puntos reales para el mes actual
        puntos = 0
        col_idx = None
        nombre_real = None
        if matches_norm:
            nombre_real = matches_norm[0]
            col_idx = next(i for i, h in enumerate(header) if h.strip().lower() == q_norm)
        elif exacto:
            col_idx = header.index(q)
            nombre_real = q

        if col_idx is not None:
            for row in rows:
                if len(row) > col_idx and row[col_idx].strip():
                    puntos += 1
            # Mostrar primeras 3 filas con valor
            muestra = []
            for row in rows:
                if len(row) > col_idx and row[col_idx].strip():
                    muestra.append({'fecha': row[0], 'vcp_raw': row[col_idx]})
                if len(muestra) >= 3:
                    break

        return jsonify({
            'ok': True,
            'buscado': q,
            'match_exacto': exacto,
            'match_normalizado': matches_norm,
            'match_parcial': matches_partial[:5],
            'nombre_real_en_sheet': nombre_real,
            'col_idx': col_idx,
            'puntos_con_valor': puntos,
            'muestra_valores': muestra if col_idx is not None else [],
        })
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/treasury', methods=['GET'])
def api_treasury():
    try:
        from dashboard import fetch_treasury_yields
        return jsonify({'ok': True, 'data': fetch_treasury_yields()})
    except RuntimeError as e:
        return jsonify({'ok': False, 'msg': str(e)}), 503
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


# ── /api/fred ──────────────────────────────────────────────────────────────────
# Proxy para FRED (Federal Reserve Bank of St. Louis).
# La API key se configura como env var FRED_API_KEY en Railway.
# GET /api/fred?series=GDPC1&start=2010-01-01
# Respuesta: { ok: true, data: [{date, value}, ...] }
# ──────────────────────────────────────────────────────────────────────────────

_FRED_CACHE = {}   # cache_key -> {'data': [...], 'ts': float}
_FRED_TTL   = 3600  # 1 hora

@app.route('/api/fred', methods=['GET'])
def api_fred():
    import time
    series_id  = request.args.get('series', '').strip().upper()
    start_date = request.args.get('start', '2010-01-01').strip()

    if not series_id:
        return jsonify({'ok': False, 'msg': 'Parámetro series requerido'}), 400

    fred_key = os.environ.get('FRED_API_KEY', '').strip()
    if not fred_key:
        return jsonify({'ok': False, 'msg': 'FRED_API_KEY no configurada en el servidor'}), 503

    cache_key = f'{series_id}_{start_date}'
    now = time.time()
    cached = _FRED_CACHE.get(cache_key)
    if cached and now - cached['ts'] < _FRED_TTL:
        return jsonify({'ok': True, 'data': cached['data'], 'cached': True})

    url = (
        f'https://api.stlouisfed.org/fred/series/observations'
        f'?series_id={series_id}&api_key={fred_key}'
        f'&file_type=json&sort_order=asc&observation_start={start_date}&limit=500'
    )
    try:
        r = req.get(url, timeout=15, headers={'Accept': 'application/json'})
        if r.status_code == 400:
            return jsonify({'ok': False, 'msg': f'FRED: serie no encontrada o parámetros inválidos ({series_id})'}), 400
        if r.status_code == 403:
            return jsonify({'ok': False, 'msg': 'FRED: API key inválida o sin permisos'}), 403
        if not r.ok:
            return jsonify({'ok': False, 'msg': f'FRED HTTP {r.status_code}'}), 502
        j = r.json()
        if j.get('error_message'):
            return jsonify({'ok': False, 'msg': f'FRED: {j["error_message"]}'}), 400
        obs = [
            {'date': o['date'], 'value': float(o['value'])}
            for o in j.get('observations', [])
            if o.get('value') not in ('.', '', None)
        ]
        _FRED_CACHE[cache_key] = {'data': obs, 'ts': now}
        return jsonify({'ok': True, 'data': obs, 'cached': False})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


# ── /api/insider ───────────────────────────────────────────────────────────────
# Fuente: SEC EDGAR Form 4 filings (público, sin auth)
# GET /api/insider?days=30
# Respuesta: {ok: true, data: [{date, ticker, issuer_name, insider_name, title,
#             relationship, type, shares, price, value, sector}]}
# ──────────────────────────────────────────────────────────────────────────────

_INSIDER_CACHE   = {}   # {'data': [...], 'ts': float, 'days': int}
_CIK_INFO_CACHE  = {}   # cik_str -> {'sector': str}

_SEC_HEADERS = {'User-Agent': 'LDWM Research admin@ldwm.com', 'Accept': 'application/json'}
_SEC_HEADERS_XML = {'User-Agent': 'LDWM Research admin@ldwm.com'}

_SIC_SECTORS = {
    range(7300, 7400): 'Technology',
    range(2800, 2900): 'Healthcare',
    range(3800, 3900): 'Healthcare',
    range(8000, 8100): 'Healthcare',
    range(6000, 6100): 'Finance',
    range(6100, 6200): 'Finance',
    range(6200, 6300): 'Finance',
    range(6300, 6400): 'Finance',
    range(1300, 1400): 'Energy',
    range(2900, 3000): 'Energy',
    range(5200, 6000): 'Consumer',
    range(2000, 2200): 'Consumer',
    range(3500, 3600): 'Industrial',
    range(3400, 3500): 'Industrial',
    range(3700, 3800): 'Industrial',
    range(4400, 4600): 'Industrial',
    range(6500, 6600): 'Real Estate',
    range(6700, 6800): 'Real Estate',
    range(1000, 1100): 'Materials',
    range(3300, 3400): 'Materials',
    range(4900, 5000): 'Utilities',
    range(4800, 4900): 'Communications',
    range(7800, 7900): 'Communications',
}

def _sic_to_sector(sic_str):
    """Convierte código SIC a sector."""
    try:
        sic = int(str(sic_str).strip())
        for r, sector in _SIC_SECTORS.items():
            if sic in r:
                return sector
    except Exception:
        pass
    return 'Other'

def _get_cik_sector(cik_str):
    """Obtiene el sector de un CIK desde SEC submissions JSON. Cachea."""
    import time
    cik_key = cik_str.lstrip('0') or '0'
    cached = _CIK_INFO_CACHE.get(cik_key)
    if cached:
        return cached.get('sector', 'Other')
    try:
        cik_10 = cik_str.zfill(10)
        url = f'https://data.sec.gov/submissions/CIK{cik_10}.json'
        r = req.get(url, headers=_SEC_HEADERS, timeout=10)
        if r.status_code == 200:
            d = r.json()
            sic = d.get('sic') or d.get('sicDescription', '')
            sector = _sic_to_sector(sic)
            _CIK_INFO_CACHE[cik_key] = {'sector': sector}
            return sector
    except Exception:
        pass
    _CIK_INFO_CACHE[cik_key] = {'sector': 'Other'}
    return 'Other'

def _parse_form4_xml(xml_bytes):
    """Parsea XML de Form 4 y devuelve lista de trades."""
    import xml.etree.ElementTree as ET
    # Evitar problemas de namespace
    xml_clean = xml_bytes.replace(b' xmlns=', b' xmlnsIgnore=')
    try:
        root = ET.fromstring(xml_clean)
    except Exception:
        return []

    def txt(el, tag):
        """Extrae texto de un sub-elemento."""
        node = el.find(tag)
        if node is not None and node.text:
            return node.text.strip()
        return ''

    def safe_float(s):
        try:
            return float(str(s).replace(',', '').strip())
        except Exception:
            return None

    issuer_ticker = txt(root, 'issuer/issuerTradingSymbol')
    issuer_name   = txt(root, 'issuer/issuerName')
    issuer_cik    = txt(root, 'issuer/issuerCik')

    owner_name  = txt(root, 'reportingOwner/reportingOwnerId/rptOwnerName')
    officer_title = txt(root, 'reportingOwner/reportingOwnerRelationship/officerTitle')
    is_director = txt(root, 'reportingOwner/reportingOwnerRelationship/isDirector') == '1'
    is_officer  = txt(root, 'reportingOwner/reportingOwnerRelationship/isOfficer') == '1'
    is_10pct    = txt(root, 'reportingOwner/reportingOwnerRelationship/isTenPercentOwner') == '1'

    if is_officer:
        relationship = 'Officer'
    elif is_director:
        relationship = 'Director'
    elif is_10pct:
        relationship = '10%+ Owner'
    else:
        relationship = 'Other'

    trades = []
    nd_table = root.find('nonDerivativeTable')
    if nd_table is None:
        return trades

    for txn in nd_table.findall('nonDerivativeTransaction'):
        code = txt(txn, 'transactionAmounts/transactionCode')
        if code not in ('P', 'S'):
            continue
        date_str = txt(txn, 'transactionDate/value')
        shares_v = safe_float(txt(txn, 'transactionAmounts/transactionShares/value'))
        price_v  = safe_float(txt(txn, 'transactionAmounts/transactionPricePerShare/value'))

        if shares_v is None or price_v is None:
            continue

        value = round(shares_v * price_v, 2)
        trades.append({
            'date':         date_str,
            'ticker':       issuer_ticker,
            'issuer_name':  issuer_name,
            'issuer_cik':   issuer_cik,
            'insider_name': owner_name,
            'title':        officer_title,
            'relationship': relationship,
            'type':         'B' if code == 'P' else 'S',
            'shares':       shares_v,
            'price':        price_v,
            'value':        value,
        })
    return trades

def _process_filing(hit):
    """Procesa un hit de EFTS: _id tiene formato {accession}:{xml_file}."""
    try:
        raw_id = hit.get('_id', '')
        # Formato real: "0001493152-26-015387:ownership.xml"
        if ':' in raw_id:
            accession, xml_doc = raw_id.split(':', 1)
        else:
            return []  # sin xml_doc no podemos hacer nada

        parts = accession.split('-')
        if len(parts) < 3:
            return []
        cik     = parts[0]          # "0001493152"
        nodash  = accession.replace('-', '')  # "000149315226015387"
        cik_int = int(cik)

        xml_url = f'https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/{xml_doc}'
        xr = req.get(xml_url, headers=_SEC_HEADERS_XML, timeout=10)
        if xr.status_code != 200:
            return []

        trades = _parse_form4_xml(xr.content)
        if not trades:
            return []

        sector = _get_cik_sector(str(trades[0].get('issuer_cik') or cik).zfill(10))
        for t in trades:
            t['sector'] = sector
            t.pop('issuer_cik', None)
        return trades
    except Exception:
        return []


def _fetch_insider_data(days):
    """Descarga Form 4 filings de SEC EDGAR con 6 workers concurrentes."""
    import concurrent.futures
    from datetime import datetime, timedelta

    end_dt   = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    start_s  = start_dt.strftime('%Y-%m-%d')
    end_s    = end_dt.strftime('%Y-%m-%d')

    # ── 1. EFTS: obtener hasta 20 hits recientes ──────────────────────────────
    url = (
        f'https://efts.sec.gov/LATEST/search-index?q=&forms=4'
        f'&dateRange=custom&startdt={start_s}&enddt={end_s}&from=0&size=20'
    )
    try:
        r = req.get(url, headers=_SEC_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        hits = r.json().get('hits', {}).get('hits', [])
    except Exception:
        return []

    if not hits:
        return []

    # ── 2. Procesar en paralelo (6 workers, sin sleep artificial) ─────────────
    all_trades = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_process_filing, h) for h in hits]
        for fut in concurrent.futures.as_completed(futures, timeout=25):
            try:
                all_trades.extend(fut.result())
            except Exception:
                pass

    return all_trades


@app.route('/api/insider/ping', methods=['GET'])
def api_insider_ping():
    """Diagnóstico: verifica EFTS + descarga primer filing completo."""
    import time
    t0 = time.time()
    try:
        from datetime import datetime, timedelta
        end_s   = datetime.utcnow().strftime('%Y-%m-%d')
        start_s = (datetime.utcnow() - timedelta(days=14)).strftime('%Y-%m-%d')
        url = (f'https://efts.sec.gov/LATEST/search-index?q=&forms=4'
               f'&dateRange=custom&startdt={start_s}&enddt={end_s}&from=0&size=3')
        r = req.get(url, headers=_SEC_HEADERS, timeout=10)
        d = r.json()
        hits = d.get('hits', {}).get('hits', [])
        sample_trades = []
        filings_with_trades = 0
        for h in hits[:10]:
            t = _process_filing(h)
            if t:
                filings_with_trades += 1
                if not sample_trades:
                    sample_trades = t[:3]
        return jsonify({
            'ok': True,
            'efts_status': r.status_code,
            'total': d.get('hits', {}).get('total', {}),
            'filings_checked': min(10, len(hits)),
            'filings_with_trades': filings_with_trades,
            'sample_trades': sample_trades,
            'elapsed_s': round(time.time() - t0, 2),
        })
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e), 'elapsed_s': round(time.time() - t0, 2)}), 500


@app.route('/api/insider', methods=['GET'])
def api_insider():
    import time
    try:
        days = int(request.args.get('days', 30))
        if days < 1 or days > 365:
            days = 30
    except Exception:
        days = 30

    now = time.time()
    cached = _INSIDER_CACHE
    if cached.get('data') is not None and cached.get('days') == days and now - cached.get('ts', 0) < 4 * 3600:
        return jsonify({'ok': True, 'data': cached['data'], 'cached': True})

    try:
        data = _fetch_insider_data(days)
        _INSIDER_CACHE.clear()
        _INSIDER_CACHE['data'] = data
        _INSIDER_CACHE['ts']   = time.time()
        _INSIDER_CACHE['days'] = days
        return jsonify({'ok': True, 'data': data, 'cached': False})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
