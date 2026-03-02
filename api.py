from flask import Flask, jsonify
from flask_cors import CORS
import asyncio, os, json, tempfile
from borkse import main as scrape_main

app = Flask(__name__)
CORS(app)

@app.route('/scrape', methods=['POST','GET'])
def scrape():
    try:
        # Escribir credentials desde variable de entorno
        creds = os.environ.get('GOOGLE_CREDENTIALS')
        if creds:
            with open('credentials.json','w') as f:
                f.write(creds)
        asyncio.run(scrape_main())
        return jsonify({'ok': True, 'msg': 'Scraper completado correctamente'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
