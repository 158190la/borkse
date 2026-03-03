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
