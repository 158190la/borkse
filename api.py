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
        tsy = fetch_treasury_yields()
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

@app.route('/api/parte', methods=['GET', 'POST'])
def api_parte():
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
        return jsonify({'ok': True, 'data': parte})
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


    """
    Rendimiento diario: /ultimo vs /penultimo.
    Rendimientos semana/mes/YTD/año: desde Google Sheets (acumulado con /tick).
    """
    from datetime import date, timedelta

    if not vcp_hoy:
        return {'day': None, 'week': None, 'month': None, 'ytd': None, 'year': None}

    # Diario desde penultimo
    rend_day = None
    try:
        penult = _load_ad('penultimo')
        fp = _find(penult, nombre)
        if fp and fp.get('vcp'):
            rend_day = round((vcp_hoy / fp['vcp'] - 1) * 100, 4)
    except Exception:
        pass

    # Históricos desde Google Sheets
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

def _calc_rendimientos_cached(nombre, vcp_hoy):
    import time
    key = nombre.lower()
    now = time.time()
    cached = _REND_CACHE.get(key)
    if cached and now - cached['ts'] < 4 * 3600:
        return cached['data']
    data = _calc_rendimientos(nombre, vcp_hoy)
    _REND_CACHE[key] = {'data': data, 'ts': now}
    return data



# ── Google Sheets histórico de VCPs ───────────────────────────────────────────
# Sheet: "FCI Historico" con columnas A=fecha, B=nombre, C=vcp
# Se crea automáticamente si no existe.

_GS_SHEET_NAME = 'FCI Historico'
_GS_WS_NAME    = 'vcps'
_GS_CACHE      = {}   # {'rows': [...], 'ts': float}

def _gs_get_ws():
    """Abre o crea el worksheet de VCPs en el Google Sheet principal."""
    ensure_credentials()
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    # Abrir spreadsheet existente (el mismo que usa dashboard.py)
    import json
    creds_data = json.loads(open('credentials.json').read())
    # Buscar spreadsheet por nombre
    try:
        sh = client.open(_GS_SHEET_NAME)
    except Exception:
        sh = client.create(_GS_SHEET_NAME)
        sh.share('', perm_type='anyone', role='reader')
    # Abrir o crear worksheet
    try:
        ws = sh.worksheet(_GS_WS_NAME)
    except Exception:
        ws = sh.add_worksheet(_GS_WS_NAME, rows=50000, cols=3)
        ws.append_row(['fecha', 'nombre', 'vcp'])
    return ws

def _gs_write_snapshot():
    """
    Escribe el VCP de hoy para todos los fondos en Google Sheets.
    Solo escribe fechas nuevas (no duplica).
    """
    from datetime import date
    today = date.today().strftime('%Y-%m-%d')
    fondos = _load_ad('ultimo')
    if not fondos:
        return 0, 'No se pudo cargar fondos'
    try:
        ws = _gs_get_ws()
        # Verificar si ya existe hoy
        all_vals = ws.col_values(1)  # columna fecha
        if today in all_vals:
            return 0, f'Ya existe snapshot para {today}'
        # Preparar batch de filas
        rows = [[today, f['nombre'], f['vcp']] for f in fondos.values() if f.get('vcp')]
        # Escribir en batches de 500
        for i in range(0, len(rows), 500):
            ws.append_rows(rows[i:i+500], value_input_option='RAW')
        return len(rows), 'ok'
    except Exception as e:
        return 0, str(e)

def _gs_read_series(nombre, desde, hasta):
    """
    Lee la serie histórica de VCP para un fondo desde Google Sheets.
    Cachea 1h.
    """
    import time
    now = time.time()
    cache_key = nombre.lower()
    cached = _GS_CACHE.get(cache_key)
    if cached and now - cached['ts'] < 3600:
        return cached['rows']
    try:
        ws = _gs_get_ws()
        # Leer todas las filas de este fondo en el rango de fechas
        # Para eficiencia: leer todo y filtrar en Python
        all_rows = ws.get_all_values()
        nl = nombre.lower()
        series = [
            {'fecha': r[0], 'vcp': float(r[2])}
            for r in all_rows[1:]  # skip header
            if len(r) >= 3 and r[1].lower() == nl and desde <= r[0] <= hasta
        ]
        series.sort(key=lambda x: x['fecha'])
        _GS_CACHE[cache_key] = {'rows': series, 'ts': now}
        return series
    except Exception as e:
        return []



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
        fondos = _load_ad('ultimo')
        f = _find(fondos, nombre_q)
        if not f:
            return jsonify({'ok': False, 'msg': f'Fondo no encontrado'}), 404
        hist = _calc_rendimientos(f['nombre'], f['vcp'])
        return jsonify({'ok': True, 'data': {
            'fondoId':    abs(hash(f['nombre'])) % 10000000,
            'claseId':    abs(hash(f['nombre'])) % 10000000,
            'nombre':     f['nombre'],
            'gerente':    '',
            'tipo':       f['horizonte'] or f['tipo'],
            'moneda':     'ARS',
            'vcp':        f['vcp'],
            'patrimonio': f['patrimonio'],
            'rendimientos': hist,
        }})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/historico', methods=['GET'])
def api_fci_historico():
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
        # Test sheets connection
        gs_status = 'not tested'
        try:
            ws = _gs_get_ws()
            n_rows = len(ws.col_values(1))
            gs_status = f'ok - {n_rows} filas en sheet'
        except Exception as e:
            gs_status = f'error: {e}'
        return jsonify({
            'ok': True,
            'fondos_ultimo':    len(fondos_u),
            'fondos_penultimo': len(fondos_p),
            'rend_diario_test': rend_test,
            'google_sheets':    gs_status,
            'sample': [{'nombre': f['nombre'], 'vcp': f['vcp'], 'fecha': f['fecha']} for f in sample],
            'tip': 'Llamar POST /api/fci/tick una vez por dia para acumular historico en Google Sheets',
        })
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/treasury', methods=['GET'])
def api_treasury():
    try:
        from dashboard import fetch_treasury_yields
        return jsonify(fetch_treasury_yields())
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
