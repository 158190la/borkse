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
_AD_CACHE_TS  = {}   # fecha_str -> timestamp (solo para 'ultimo')

def _load_fecha(fecha_str):
    """
    Descarga todos los tipos de FCI para una fecha dada.
    fecha_str: 'ultimo' | 'YYYY/MM/DD'
    Retorna dict: nombre_lower -> fondo_dict
    """
    import time
    now = time.time()
    # 'ultimo' se cachea 4h; fechas pasadas indefinidamente
    if fecha_str in _AD_CACHE:
        if fecha_str != 'ultimo' or now - _AD_CACHE_TS.get(fecha_str, 0) < 4 * 3600:
            return _AD_CACHE[fecha_str]

    fondos = {}
    for tipo in _AD_TIPOS:
        url = f'{_AD_BASE}/{tipo}/{fecha_str}'
        try:
            r = req.get(url, timeout=15, headers=_AD_H)
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue
            for it in items:
                nombre = str(it.get('fondo') or '').strip()
                if not nombre:
                    continue
                fondos[nombre.lower()] = {
                    'nombre':     nombre,
                    'tipo':       tipo,
                    'fecha':      str(it.get('fecha') or ''),
                    'vcp':        _safe_float(it.get('vcp')),
                    'ccp':        _safe_float(it.get('ccp')),
                    'patrimonio': _safe_float(it.get('patrimonio')),
                    'horizonte':  str(it.get('horizonte') or ''),
                }
        except Exception:
            continue

    _AD_CACHE[fecha_str] = fondos
    _AD_CACHE_TS[fecha_str] = now
    return fondos


def _find_fondo(fondos, query):
    """Busca un fondo por nombre exacto (case-insensitive) o parcial."""
    ql = query.strip().lower()
    # Exact match
    if ql in fondos:
        return fondos[ql]
    # Partial match - prefer startswith
    starts = [f for k, f in fondos.items() if k.startswith(ql)]
    if starts:
        return starts[0]
    contains = [f for k, f in fondos.items() if ql in k]
    if contains:
        return contains[0]
    return None


def _calc_rendimientos(nombre, vcp_hoy):
    """
    Calcula rendimientos semanal/mensual/YTD/anual comparando VCPs de
    distintas fechas usando la API de ArgentinaDatos.
    """
    import time
    from datetime import date, timedelta

    if not vcp_hoy:
        return {'week': None, 'month': None, 'ytd': None, 'year': None}

    today = date.today()
    targets = {
        'week':  today - timedelta(days=7),
        'month': today - timedelta(days=30),
        'ytd':   date(today.year, 1, 1),
        'year':  today - timedelta(days=365),
    }

    result = {}
    for period, target_date in targets.items():
        base_vcp = None
        # Buscar hasta 5 dias anteriores (feriados/findes)
        for delta in range(0, 6):
            d = target_date - timedelta(days=delta)
            fecha_str = d.strftime('%Y/%m/%d')
            fondos = _load_fecha(fecha_str)
            f = _find_fondo(fondos, nombre)
            if f and f.get('vcp'):
                base_vcp = f['vcp']
                break
        result[period] = round((vcp_hoy / base_vcp - 1) * 100, 4) if base_vcp else None

    return result


_REND_CACHE = {}   # nombre_lower -> {'data': {...}, 'ts': float}

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


@app.route('/api/fci/search', methods=['GET'])
def api_fci_search():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify({'ok': False, 'msg': 'q requerido (min 2 chars)'}), 400
    try:
        fondos = _load_fecha('ultimo')
        results = []
        for k, f in fondos.items():
            if q in k:
                results.append({
                    'fondoId':    abs(hash(f['nombre'])) % 1000000,
                    'claseId':    abs(hash(f['nombre'])) % 1000000,
                    'nombre':     f['nombre'],
                    'gerente':    '',
                    'tipo':       f['tipo'],
                    'moneda':     'ARS',
                    'vcp':        f['vcp'],
                    'patrimonio': f['patrimonio'],
                    'rendimientos': {
                        'day': None, 'week': None, 'month': None, 'ytd': None, 'year': None
                    },
                })
        results.sort(key=lambda x: (0 if x['nombre'].lower().startswith(q) else 1, x['nombre']))
        results = results[:40]
        return jsonify({'ok': True, 'data': results, 'total': len(fondos)})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/ficha', methods=['GET'])
def api_fci_ficha():
    """
    Acepta: ?nombre=<nombre> o ?fondo=<id>&clase=<id> (id = hash del nombre, ignorado)
    Busca en ArgentinaDatos y calcula rendimientos históricos.
    """
    nombre_q = request.args.get('nombre', '').strip()
    # Si viene el nombre serializado en el fondo (desde search), úsalo directo
    # Si no, no podemos resolver por ID (el hash no es reversible) → error descriptivo
    if not nombre_q:
        return jsonify({'ok': False, 'msg': 'Usar ?nombre=<nombre del fondo>'}), 400
    try:
        fondos = _load_fecha('ultimo')
        f = _find_fondo(fondos, nombre_q)
        if not f:
            return jsonify({'ok': False, 'msg': f'Fondo "{nombre_q}" no encontrado'}), 404

        hist = _calc_rendimientos_cached(f['nombre'], f['vcp'])
        return jsonify({'ok': True, 'data': {
            'fondoId':    abs(hash(f['nombre'])) % 1000000,
            'claseId':    abs(hash(f['nombre'])) % 1000000,
            'nombre':     f['nombre'],
            'gerente':    '',
            'tipo':       f['tipo'],
            'moneda':     'ARS',
            'vcp':        f['vcp'],
            'patrimonio': f['patrimonio'],
            'rendimientos': {'day': None, **hist},
        }})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/historico', methods=['GET'])
def api_fci_historico():
    """
    Serie histórica de VCP entre dos fechas.
    Acepta: ?nombre=<nombre>&desde=YYYY-MM-DD&hasta=YYYY-MM-DD
    """
    nombre_q = request.args.get('nombre', '').strip()
    from_d   = request.args.get('desde', '').strip()
    to_d     = request.args.get('hasta', '').strip()
    if not nombre_q or not from_d or not to_d:
        return jsonify({'ok': False, 'msg': 'nombre, desde y hasta requeridos'}), 400
    try:
        from datetime import date, timedelta
        y0,m0,d0 = from_d.split('-'); y1,m1,d1 = to_d.split('-')
        start = date(int(y0), int(m0), int(d0))
        end   = date(int(y1), int(m1), int(d1))
        delta = (end - start).days
        step  = max(1, delta // 30)  # max ~30 puntos

        series = []
        d = start
        while d <= end:
            fecha_str = d.strftime('%Y/%m/%d')
            fondos = _load_fecha(fecha_str)
            f = _find_fondo(fondos, nombre_q)
            if f and f.get('vcp'):
                series.append({'fecha': d.strftime('%Y-%m-%d'), 'vcp': f['vcp']})
            d += timedelta(days=step)

        return jsonify({'ok': True, 'data': series})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/debug', methods=['GET'])
def api_fci_debug():
    """Test rápido de ArgentinaDatos FCI API."""
    from datetime import date, timedelta
    results = {}
    tests = [
        ('ultimo',     f'{_AD_BASE}/mercadoDinero/ultimo'),
        ('rentaFija',  f'{_AD_BASE}/rentaFija/ultimo'),
        ('fecha_mes',  f'{_AD_BASE}/mercadoDinero/{(date.today()-timedelta(days=30)).strftime("%Y/%m/%d")}'),
    ]
    for label, url in tests:
        try:
            r = req.get(url, timeout=10, headers=_AD_H)
            items = r.json() if r.status_code == 200 else []
            results[label] = {
                'status': r.status_code,
                'count': len(items) if isinstance(items, list) else 0,
                'sample': items[:2] if isinstance(items, list) else items,
            }
        except Exception as e:
            results[label] = {'error': str(e)}
    return jsonify({'ok': True, 'results': results})



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
