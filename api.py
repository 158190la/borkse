"""
API endpoint para Railway
Expone el scraper de Deutsche Börse como servicio web
"""

from flask import Flask, jsonify
from flask_cors import CORS
import asyncio
import threading
import os

app = Flask(__name__)
CORS(app)


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
@app.route('/api/parte', methods=['GET', 'POST'])
def api_parte():
    """
    Llama a la API de Anthropic desde el servidor (evita CORS)
    y devuelve el parte diario en JSON.
    """
    try:
        import anthropic
        from datetime import datetime

        fecha = datetime.now().strftime('%A %d de %B de %Y')

        prompt = f"""Sos el analista financiero senior de LD Wealth Management.
Generá el Parte Diario de mercados de hoy ({fecha}).

Tu respuesta debe ser un objeto JSON válido con exactamente estas 12 claves:
claves, senales, flash, panorama, fed, fiscal, comercio, geo, usa, latam, argentina, ldwm

Cada clave debe contener un array de strings (entre 4 y 8 ítems por sección).
Cada ítem es una oración informativa, directa y profesional, en español.

Secciones:
- claves: titulares más importantes del día en mercados globales
- senales: variables y datos clave a seguir en las próximas 24-48h
- flash: resumen de índices y activos (S&P, Nasdaq, Merval, petróleo, oro, dólar, bonos)
- panorama: análisis macro global — acciones, bonos, commodities, divisas
- fed: postura de la Fed y otros bancos centrales, expectativas de tasas
- fiscal: política fiscal, déficit, gasto público en EE.UU. y mundo
- comercio: comercio internacional, aranceles, cadenas de valor
- geo: geopolítica relevante para mercados
- usa: datos económicos de EE.UU. del día o semana
- latam: Brasil, Chile, Colombia, México — contexto regional breve
- argentina: economía, mercados, política y empresas locales
- ldwm: régimen de riesgo actual, drivers del día, implicancia para posicionamiento y qué mirar las próximas 48h

Respondé SOLO con el JSON, sin texto adicional, sin backticks, sin markdown."""

        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': prompt}]
        )

        import json
        raw = message.content[0].text.strip()
        # Limpiar posibles backticks
        raw = raw.replace('```json', '').replace('```', '').strip()
        parte = json.loads(raw)

        return jsonify({'ok': True, 'data': parte})

    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500



@app.route('/api/treasury', methods=['GET'])
def api_treasury():
    """
    Devuelve los yields del Tesoro (interpolados desde FRED).
    Útil si el frontend quiere actualizar la curva de forma independiente.
    """
    try:
        from dashboard import fetch_treasury_yields
        tsy = fetch_treasury_yields()
        return jsonify(tsy)
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500


# ── main ──────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
