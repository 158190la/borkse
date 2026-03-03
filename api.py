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



# ── /api/fci/* ────────────────────────────────────────────

from urllib.parse import quote as _url_quote

def _safe_float(v):
    try: return round(float(v), 4) if v not in (None, '', 'N/A') else None
    except: return None

CAFCI_H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-AR,es;q=0.9',
    'Origin': 'https://www.cafci.org.ar',
    'Referer': 'https://www.cafci.org.ar/',
}

def _cafci_get(url, timeout=15):
    """GET a CAFCI URL. Raises descriptive Exception if response is not valid JSON."""
    r = req.get(url, timeout=timeout, headers=CAFCI_H)
    if r.status_code != 200:
        raise Exception('CAFCI HTTP ' + str(r.status_code) + ': ' + r.text[:200])
    text = r.text.strip()
    if not text or text[0] not in ('{', '['):
        raise Exception('CAFCI no-JSON (HTTP ' + str(r.status_code) + '): ' + text[:200])
    return r.json()


@app.route("/api/fci/search", methods=["GET"])
def api_fci_search():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify({"ok": False, "msg": "q requerido (min 2 chars)"}), 400
    try:
        j = _cafci_get("https://api.cafci.org.ar/fondo?nombre=" + _url_quote(q) + "&limit=40&estado=1")
        results = []
        for f in (j.get("data") or []):
            gest = f.get("gestora") or {}
            tipo = f.get("tipoFondo") or {}
            for c in (f.get("clases") or []):
                results.append({
                    "fondoId": f.get("id"),
                    "claseId": c.get("id"),
                    "nombre":  f.get("nombre", ""),
                    "clase":   c.get("nombre", ""),
                    "gerente": gest.get("nombre", "") if isinstance(gest, dict) else "",
                    "tipo":    tipo.get("nombre", "") if isinstance(tipo, dict) else "",
                    "moneda":  c.get("moneda", ""),
                })
        return jsonify({"ok": True, "data": results})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route('/api/fci/debug', methods=['GET'])
def api_fci_debug():
    out = {}
    tests = [
        ('search_balanz', 'https://api.cafci.org.ar/fondo?nombre=balanz&limit=3&estado=1'),
        ('ficha_847_2409', 'https://api.cafci.org.ar/fondo/847/clase/2409/ficha'),
    ]
    for label, url in tests:
        try:
            r = req.get(url, timeout=10, headers=CAFCI_H)
            out[label] = {'status': r.status_code, 'preview': r.text[:400]}
        except Exception as e:
            out[label] = {'error': str(e)}
    return jsonify(out)


@app.route('/api/fci/ficha', methods=['GET'])
def api_fci_ficha():
    fid, cid = request.args.get('fondo'), request.args.get('clase')
    if not fid or not cid: return jsonify({'ok':False,'msg':'fondo y clase requeridos'}), 400
    try:
        d = req.get(f'https://api.cafci.org.ar/fondo/{fid}/clase/{cid}/ficha', timeout=10, headers=CAFCI_H).json().get('data',{})
        diaria = (d.get('info') or {}).get('diaria',{})
        rend   = diaria.get('rendimientos',{})
        actual = diaria.get('actual',{})
        fi     = d.get('fondo',{})
        return jsonify({'ok':True,'data':{
            'fondoId': int(fid), 'claseId': int(cid),
            'nombre':  fi.get('nombre', d.get('nombre','')),
            'gerente': (fi.get('gestora') or {}).get('nombre',''),
            'tipo':    (fi.get('tipoFondo') or {}).get('nombre',''),
            'moneda':  d.get('moneda',''),
            'vcp':     actual.get('vcp') or diaria.get('vcp'),
            'patrimonio': actual.get('patrimonio'),
            'fecha':   diaria.get('referenceDay'),
            'rendimientos': {
                'day':   _safe_float((rend.get('day')   or {}).get('rendimiento')),
                'week':  _safe_float((rend.get('week')  or {}).get('rendimiento')),
                'month': _safe_float((rend.get('month') or {}).get('rendimiento')),
                'ytd':   _safe_float((rend.get('ytd')   or {}).get('rendimiento')),
                'year':  _safe_float((rend.get('year')  or {}).get('rendimiento')),
            }
        }})
    except Exception as e: return jsonify({'ok':False,'msg':str(e)}), 500

@app.route('/api/fci/historico', methods=['GET'])
def api_fci_historico():
    fid  = request.args.get('fondo')
    cid  = request.args.get('clase')
    from_d = request.args.get('desde')
    to_d   = request.args.get('hasta')
    if not all([fid,cid,from_d,to_d]): return jsonify({'ok':False,'msg':'fondo clase desde hasta requeridos'}), 400
    try:
        def fmt(d): y,m,day=d.split('-'); return f'{day}-{m}-{y}'
        items = req.get(f'https://api.cafci.org.ar/fondo/{fid}/clase/{cid}/rendimiento/{fmt(from_d)}/{fmt(to_d)}', timeout=15, headers=CAFCI_H).json().get('data',[])
        series = [{'fecha':it['fecha'],'vcp':float(it['vcp'])} for it in items if isinstance(it,dict) and it.get('fecha') and it.get('vcp') is not None]
        return jsonify({'ok':True,'data':series})
    except Exception as e: return jsonify({'ok':False,'msg':str(e)}), 500

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
