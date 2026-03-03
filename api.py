"""
API endpoint para Railway
Expone el scraper de Deutsche Börse como servicio web
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
import threading
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def ensure_credentials():
    """Escribe credentials.json desde variable de entorno si no existe."""
    creds_env = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_env:
        with open('credentials.json', 'w') as f:
            f.write(creds_env)
        return True
    if os.path.exists('credentials.json'):
        return True
    return False


def run_async(coro):
    """Corre una coroutine async desde un contexto síncrono (Flask)."""
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


# ── /health ───────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'borkse-api'})


# ── /scrape ───────────────────────────────────────────────
@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    try:
        if not ensure_credentials():
            return jsonify({
                'ok': False,
                'msg': 'No se encontró credentials.json ni la variable GOOGLE_CREDENTIALS en Railway.'
            }), 500

        from borkse import main as scrape_main
        result = run_async(scrape_main())

        if result.get('ok'):
            return jsonify({
                'ok': True,
                'msg': 'Scraper completado. Google Sheets actualizado correctamente.'
            })
        else:
            return jsonify({
                'ok': False,
                'msg': result.get('error', 'Error desconocido')
            }), 500

    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


# ── /api/bonds ────────────────────────────────────────────
@app.route('/api/bonds', methods=['GET'])
def api_bonds():
    """
    Lee el Google Sheet, procesa los bonos con la lógica de dashboard.py
    y devuelve el array JSON listo para el dashboard HTML.
    """
    try:
        if not ensure_credentials():
            return jsonify({
                'ok': False,
                'msg': 'No se encontró credentials.json ni la variable GOOGLE_CREDENTIALS.'
            }), 500

        from dashboard import load_bonds, process_bonds, fetch_treasury_yields
        tsy   = fetch_treasury_yields()
        raw   = load_bonds()
        bonds = process_bonds(raw, tsy)

        return jsonify(bonds)

    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500



# ── /api/parte ────────────────────────────────────────────
def fetch_market_data():
    """Obtiene datos reales de mercado desde Yahoo Finance y otras fuentes públicas."""
    import requests, json
    from datetime import datetime

    data = {}

    # Tickers a consultar via Yahoo Finance
    tickers = {
        'SP500':   '^GSPC',
        'NASDAQ':  '^IXIC',
        'DOW':     '^DJI',
        'VIX':     '^VIX',
        'MERVAL':  '^MERV',
        'BRENT':   'BZ=F',
        'WTI':     'CL=F',
        'GOLD':    'GC=F',
        'DXY':     'DX-Y.NYB',
        'UST2Y':   '^IRX',
        'UST10Y':  '^TNX',
        'NATGAS':  'NG=F',
        'BTC':     'BTC-USD',
    }

    headers = {'User-Agent': 'Mozilla/5.0'}
    results = {}

    for name, ticker in tickers.items():
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d'
            r = requests.get(url, headers=headers, timeout=8)
            d = r.json()
            meta = d['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice', meta.get('previousClose', 0))
            prev  = meta.get('previousClose', price)
            chg   = ((price - prev) / prev * 100) if prev else 0
            results[name] = {'price': round(price, 2), 'chg': round(chg, 2)}
        except Exception:
            results[name] = {'price': 'N/D', 'chg': 0}

    return results


@app.route('/api/parte', methods=['GET', 'POST'])
def api_parte():
    """
    Busca datos reales de mercado y luego llama a Claude para generar
    el parte diario fundamentado en cifras reales.
    """
    try:
        import anthropic, json
        from datetime import datetime

        fecha = datetime.now().strftime('%A %d de %B de %Y')

        # 1. Obtener datos reales
        mkt = fetch_market_data()

        def fmt(k):
            v = mkt.get(k, {})
            p = v.get('price', 'N/D')
            c = v.get('chg', 0)
            signo = '+' if c > 0 else ''
            return f"{p} ({signo}{c}%)"

        market_context = f"""
DATOS DE MERCADO EN TIEMPO REAL ({fecha}):

ÍNDICES GLOBALES:
- S&P 500:       {fmt('SP500')}
- Nasdaq:        {fmt('NASDAQ')}
- Dow Jones:     {fmt('DOW')}
- VIX:           {fmt('VIX')}
- Merval (ARS):  {fmt('MERVAL')}

COMMODITIES:
- Petróleo Brent:{fmt('BRENT')}
- Petróleo WTI:  {fmt('WTI')}
- Gas Natural:   {fmt('NATGAS')}
- Oro:           {fmt('GOLD')}

DIVISAS Y TASAS:
- DXY (dólar):   {fmt('DXY')}
- UST 2Y yield:  {fmt('UST2Y')}
- UST 10Y yield: {fmt('UST10Y')}

CRYPTO:
- Bitcoin:       {fmt('BTC')}
"""

        prompt = f"""Sos el analista financiero senior de LD Wealth Management.
Generá el Parte Diario de mercados de hoy ({fecha}).

Usá EXCLUSIVAMENTE los datos reales provistos abajo. No inventes cifras ni uses datos de memoria.
Cuando menciones precios o variaciones, citá los números exactos del contexto.

{market_context}

Tu respuesta debe ser un objeto JSON válido con exactamente estas 12 claves:
claves, senales, flash, panorama, fed, fiscal, comercio, geo, usa, latam, argentina, ldwm

Cada clave contiene un array de 4 a 8 strings. Cada string es una oración informativa,
directa y profesional en español. Usá los precios reales en flash y panorama.
En ldwm: interpretá el régimen de riesgo actual basándote en los datos reales (VIX, variaciones).

Respondé SOLO con el JSON, sin texto adicional, sin backticks, sin markdown."""

        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': prompt}]
        )

        raw = message.content[0].text.strip()
        raw = raw.replace('```json', '').replace('```', '').strip()
        parte = json.loads(raw)

        return jsonify({'ok': True, 'data': parte, 'market_data': mkt})

    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500



# ── /api/market ───────────────────────────────────────────
@app.route('/api/market', methods=['GET'])
def api_market():
    """
    Proxy de Yahoo Finance para evitar CORS en el browser.
    Recibe ?tickers=^GSPC,BTC-USD y devuelve precio + variacion + closes.
    """
    from urllib.parse import unquote

    tickers_param = request.args.get('tickers', '')
    if not tickers_param:
        return jsonify({'ok': False, 'msg': 'No tickers provided'}), 400

    # Decodificar %5E -> ^ etc.
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
                r = requests.get(url, headers=headers, timeout=12)
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
                        data = {'price': round(float(price), 6), 'chg': round(float(chg), 4), 'closes': closes[-50:]}
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
