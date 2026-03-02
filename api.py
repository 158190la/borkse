"""
API endpoint para Railway
Expone el scraper de Deutsche Börse como servicio web
"""

"""
API endpoint para Railway
Expone el scraper de Deutsche Börse como servicio web
"""

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


def run_async(coro):
    """Corre una coroutine async desde un contexto síncrono (Flask)"""
    result = {}
    def target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
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
    return jsonify({'status': 'ok', 'service': 'borkse-api'})


@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    try:
        # Escribir credentials desde variable de entorno de Railway
        creds_env = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_env:
            with open('credentials.json', 'w') as f:
                f.write(creds_env)
        elif not os.path.exists('credentials.json'):
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
