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
# Fuente: https://api.pub.cafci.org.ar/pb_get  (Excel publico, sin auth)
#
# Estructura confirmada:
#   Filas 0-5: encabezados varios (vacías, título, dirección, reporte, vacías)
#   Fila 6:    headers — col0="Fondo", col5="Valor(mil cuotapartes)",
#              col9="Variación%", col14="Patrimonio", col20="Código CAFCI"(=fondoId),
#              col23="Sociedad Gerente", col36="Moneda Fondo"
#   Fila 7+:   datos
#
# Para rendimientos historicos: el endpoint acepta ?fecha=DD-MM-YYYY
# Comparamos VCPs entre fechas para calcular rendimientos acumulados.
# ──────────────────────────────────────────────────────────────────────────────

_PUB_H = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cafci.org.ar/'}

_CI = {
    'nombre': 0, 'tipo': 1, 'fecha': 4, 'vcp': 5,
    'rend_dia': 9, 'patrimonio': 14, 'cafci_id': 20,
    'gerente': 23, 'moneda': 36,
}

def _safe_float(v):
    try:
        return round(float(v), 4) if v not in (None, '', 'N/A') else None
    except Exception:
        return None

def _get_col(cols, key):
    idx = _CI.get(key)
    return cols[idx] if idx is not None and idx < len(cols) else None

def _parse_xls(content):
    """Parsea bytes del Excel CAFCI. Retorna dict nombre->fondo_dict."""
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    fondos = {}
    header_found = False
    for row in ws.iter_rows(values_only=True):
        if not header_found:
            if row[0] is not None and str(row[0]).strip().lower() == 'fondo':
                header_found = True
            continue
        cols = list(row)
        nombre = _get_col(cols, 'nombre')
        cafci_id = _get_col(cols, 'cafci_id')
        if not nombre or not cafci_id:
            continue
        try:
            fid = int(float(str(cafci_id).strip()))
        except Exception:
            continue
        nombre_str = str(nombre).strip()
        fondos[nombre_str] = {
            'fondoId':    fid,
            'nombre':     nombre_str,
            'gerente':    str(_get_col(cols, 'gerente') or '').strip(),
            'tipo':       str(_get_col(cols, 'tipo') or '').strip(),
            'moneda':     str(_get_col(cols, 'moneda') or 'ARS').strip(),
            'vcp':        _safe_float(_get_col(cols, 'vcp')),
            'patrimonio': _safe_float(_get_col(cols, 'patrimonio')),
            'rend_dia':   _safe_float(_get_col(cols, 'rend_dia')),
        }
    wb.close()
    return fondos

# Cache del Excel por fecha: fecha_str (DD-MM-YYYY o 'today') -> {nombre: vcp}
_XLS_VCP_CACHE = {}
_XLS_TODAY_CACHE = {'fondos': None, 'ts': 0}

def _load_today():
    """Descarga y cachea el Excel de hoy. Retorna dict nombre->fondo."""
    import time
    now = time.time()
    if _XLS_TODAY_CACHE['fondos'] and now - _XLS_TODAY_CACHE['ts'] < 4 * 3600:
        return _XLS_TODAY_CACHE['fondos']
    r = req.get('https://api.pub.cafci.org.ar/pb_get', timeout=25, headers=_PUB_H)
    if r.status_code != 200:
        raise Exception(f'CAFCI planilla HTTP {r.status_code}')
    fondos = _parse_xls(r.content)
    if not fondos:
        raise Exception('No se parseo ningun fondo')
    _XLS_TODAY_CACHE['fondos'] = fondos
    _XLS_TODAY_CACHE['ts'] = now
    return fondos

def _vcps_at(target_date):
    """
    VCPs de todos los fondos en target_date (o el dia habill anterior).
    Retorna dict nombre->vcp. Cachea indefinidamente.
    """
    from datetime import timedelta
    for delta in range(0, 6):
        d = target_date - timedelta(days=delta)
        dstr = d.strftime('%d-%m-%Y')
        if dstr in _XLS_VCP_CACHE:
            return _XLS_VCP_CACHE[dstr]
        try:
            url = f'https://api.pub.cafci.org.ar/pb_get?fecha={dstr}'
            r = req.get(url, timeout=20, headers=_PUB_H)
            if r.status_code != 200:
                continue
            ct = r.headers.get('content-type', '')
            if 'html' in ct or len(r.content) < 5000:
                continue
            fondos = _parse_xls(r.content)
            if not fondos:
                continue
            vcps = {n: f['vcp'] for n, f in fondos.items() if f['vcp']}
            _XLS_VCP_CACHE[dstr] = vcps
            return vcps
        except Exception:
            continue
    return {}

_REND_CACHE = {}  # nombre -> {'data': {...}, 'ts': float}

def _calc_rendimientos(nombre, vcp_hoy):
    """Calcula rendimientos comparando VCP de hoy vs fechas historicas."""
    import time
    from datetime import date, timedelta
    now = time.time()
    cached = _REND_CACHE.get(nombre)
    if cached and now - cached['ts'] < 4 * 3600:
        return cached['data']
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
        vcps = _vcps_at(target_date)
        base = vcps.get(nombre)
        result[period] = round((vcp_hoy / base - 1) * 100, 4) if base else None
    _REND_CACHE[nombre] = {'data': result, 'ts': now}
    return result


@app.route('/api/fci/search', methods=['GET'])
def api_fci_search():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify({'ok': False, 'msg': 'q requerido (min 2 chars)'}), 400
    try:
        fondos = _load_today()
        results = []
        for nombre, f in fondos.items():
            if q in nombre.lower():
                results.append({
                    'fondoId':    f['fondoId'],
                    'claseId':    f['fondoId'],
                    'nombre':     nombre,
                    'gerente':    f['gerente'],
                    'tipo':       f['tipo'],
                    'moneda':     f['moneda'],
                    'vcp':        f['vcp'],
                    'patrimonio': f['patrimonio'],
                    'rendimientos': {
                        'day': f['rend_dia'],
                        'week': None, 'month': None, 'ytd': None, 'year': None
                    },
                })
        results = results[:40]
        results.sort(key=lambda x: (0 if x['nombre'].lower().startswith(q) else 1, x['nombre']))
        return jsonify({'ok': True, 'data': results, 'total': len(fondos)})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/ficha', methods=['GET'])
def api_fci_ficha():
    """
    Devuelve datos + rendimientos completos para un fondo.
    Parametros: ?nombre=<nombre exacto>  o  ?fondo=<fondoId>  y  ?clase=<claseId>
    Los rendimientos historicos se calculan comparando VCPs entre fechas.
    """
    nombre_q = request.args.get('nombre', '').strip()
    fid_s    = request.args.get('fondo', '').strip()
    if not nombre_q and not fid_s:
        return jsonify({'ok': False, 'msg': 'nombre o fondo requerido'}), 400
    try:
        fondos = _load_today()
        f = None
        if nombre_q:
            f = fondos.get(nombre_q)
            if not f:
                ql = nombre_q.lower()
                for n, fd in fondos.items():
                    if ql in n.lower():
                        f = fd
                        break
        else:
            fid = int(fid_s)
            for fd in fondos.values():
                if fd['fondoId'] == fid:
                    f = fd
                    break
        if not f:
            return jsonify({'ok': False, 'msg': 'Fondo no encontrado'}), 404

        hist = _calc_rendimientos(f['nombre'], f['vcp'])
        return jsonify({'ok': True, 'data': {
            'fondoId':    f['fondoId'],
            'claseId':    f['fondoId'],
            'nombre':     f['nombre'],
            'gerente':    f['gerente'],
            'tipo':       f['tipo'],
            'moneda':     f['moneda'],
            'vcp':        f['vcp'],
            'patrimonio': f['patrimonio'],
            'rendimientos': {'day': f['rend_dia'], **hist},
        }})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


@app.route('/api/fci/historico', methods=['GET'])
def api_fci_historico():
    nombre_q = request.args.get("nombre", "").strip()
    fid_s    = request.args.get("fondo", "").strip()
    from_d   = request.args.get("desde", "").strip()
    to_d     = request.args.get("hasta", "").strip()
    if not from_d or not to_d:
        return jsonify({"ok": False, "msg": "desde y hasta requeridos"}), 400
    if not nombre_q and not fid_s:
        return jsonify({"ok": False, "msg": "nombre o fondo requerido"}), 400
    try:
        from datetime import date, timedelta
        if not nombre_q and fid_s:
            fid = int(fid_s)
            for fd in _load_today().values():
                if fd["fondoId"] == fid:
                    nombre_q = fd["nombre"]
                    break
        if not nombre_q:
            return jsonify({"ok": False, "msg": "Fondo no encontrado"}), 404
        y0,m0,d0 = from_d.split("-"); y1,m1,d1 = to_d.split("-")
        start = date(int(y0),int(m0),int(d0)); end = date(int(y1),int(m1),int(d1))
        step = max(1,(end-start).days//25)
        series=[]; d=start
        while d<=end:
            vcps=_vcps_at(d); vcp=vcps.get(nombre_q)
            if vcp: series.append({"fecha":d.strftime("%Y-%m-%d"),"vcp":vcp})
            d+=timedelta(days=step)
        return jsonify({"ok":True,"data":series})
    except Exception as e: return jsonify({"ok":False,"msg":str(e)}),500



@app.route('/api/fci/debug', methods=['GET'])
def api_fci_debug():
    """Diagnostico: prueba si el endpoint acepta parametro ?fecha=."""
    try:
        from datetime import date, timedelta
        results = {}
        test_dates = [
            ('sin_fecha',    'https://api.pub.cafci.org.ar/pb_get'),
            ('fecha_semana', f'https://api.pub.cafci.org.ar/pb_get?fecha={(date.today()-timedelta(days=7)).strftime("%d-%m-%Y")}'),
            ('fecha_mes',    f'https://api.pub.cafci.org.ar/pb_get?fecha={(date.today()-timedelta(days=30)).strftime("%d-%m-%Y")}'),
        ]
        for label, url in test_dates:
            r = req.get(url, timeout=15, headers=_PUB_H)
            info = {
                'status': r.status_code,
                'content_type': r.headers.get('content-type', ''),
                'size_kb': round(len(r.content) / 1024, 1),
            }
            if r.status_code == 200 and len(r.content) > 5000 and 'html' not in r.headers.get('content-type',''):
                try:
                    fondos = _parse_xls(r.content)
                    info['fondos_count'] = len(fondos)
                    sample = list(fondos.items())[:2]
                    info['sample'] = {n: f['vcp'] for n, f in sample}
                except Exception as e:
                    info['parse_error'] = str(e)
            else:
                info['response_preview'] = r.text[:200]
            results[label] = info
        return jsonify({'ok': True, 'results': results})
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
