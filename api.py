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
import nest_asyncio
import os

# Necesario para correr asyncio dentro de Flask
nest_asyncio.apply()

app = Flask(__name__)
CORS(app)


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de estado — para verificar que el servidor está vivo"""
    return jsonify({'status': 'ok', 'service': 'borkse-api'})


@app.route('/scrape', methods=['GET', 'POST'])
def scrape():
    """
    Corre el scraper de Deutsche Börse y actualiza Google Sheets.
    Llamado desde el botón "Correr Scraper" en research.html
    """
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
        loop = asyncio.get_event_loop()
        loop.run_until_complete(scrape_main())

        return jsonify({
            'ok': True,
            'msg': 'Scraper completado. Google Sheets actualizado correctamente.'
        })

    except Exception as e:
        return jsonify({
            'ok': False,
            'msg': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
