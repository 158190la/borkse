"""
Deutsche Börse → Google Sheets
================================
Paso 1: sniff()  → captura los headers reales del browser
Paso 2: fetch()  → usa esos headers para paginar y bajar todos los bonos
Paso 3: write()  → escribe todo en Google Sheets

Correr: python bonds.py
"""

import asyncio, json, re, copy, time, gspread
from playwright.async_api import async_playwright
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests as req_lib

# ── CONFIGURACIÓN ─────────────────────────────────────────────
SPREADSHEET_URL  = "https://docs.google.com/spreadsheets/d/1ARt3eNn0q9VkOc0QkfaIqIZp9PWwN0utT9h--O-hAzc/edit?gid=0#gid=0"
CREDENTIALS_FILE = "credentials.json"
SHEET_NAME       = "Bonos DB"

SEARCH_URL = (
    "https://live.deutsche-boerse.com/bonds/search"
    "?ISSUER_TYPES=CORPORATE_BONDS&BOND_TYPES=DB&CURRENCIES=USD"
    "&INTEREST_TYPES=FIXED_INTEREST_RATE&TERM_TO_MATURITY_MIN=12"
    "&YIELD_MAX=8&ORDER_BY=YIELD&ORDER_DIRECTION=DESC"
)

LIMIT_CANDIDATES = [1000, 500, 200, 100, 50, 25]

# ── PASO 1: SNIFF ─────────────────────────────────────────────
async def sniff():
    hit = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        async def process_response(resp):
            if hit:
                return
            try:
                data = await resp.json()
            except:
                return
            if isinstance(data, dict) and "data" in data and "recordsTotal" in data:
                req = resp.request
                hit.update({
                    "api_url":         req.url,
                    "method":          req.method,
                    "request_headers": dict(req.headers),
                    "post_data":       req.post_data,
                })
                print(f"✅ Capturado: {req.url}")
                print(f"   recordsTotal: {data['recordsTotal']} | primera página: {len(data['data'])} bonos")

        page.on("response", lambda r: asyncio.create_task(process_response(r)))

        print("Cargando sitio...")
        await page.goto(SEARCH_URL, wait_until="domcontentloaded")

        try:
            await page.locator("text=/^Start search/i").first.click(timeout=20000)
        except:
            try:
                await page.get_by_role("button", name=re.compile("Start search", re.I)).click(timeout=8000)
            except:
                pass

        await page.wait_for_timeout(8000)
        await browser.close()

    if not hit:
        raise RuntimeError("No se capturó ninguna respuesta. Intentá de nuevo.")

    return hit

# ── PASO 2: FETCH ─────────────────────────────────────────────
def clean_headers(h):
    drop = {"content-length", "host", "connection", "accept-encoding"}
    out  = {}
    for k, v in h.items():
        if k.lower() not in drop:
            out[k] = v
    out.setdefault("Accept",       "application/json, text/plain, */*")
    out.setdefault("Content-Type", "application/json; charset=utf-8")
    return out

def deep_set_all(obj, keys, value):
    changed = 0
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in keys:
                obj[k] = value
                changed += 1
            else:
                changed += deep_set_all(obj[k], keys, value)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            changed += deep_set_all(obj[i], keys, value)
    return changed

def set_paging(payload, offset, limit):
    p           = copy.deepcopy(payload)
    limit_keys  = {"limit", "length", "pageSize", "size", "take", "count"}
    offset_keys = {"offset", "start", "from", "skip"}
    deep_set_all(p, limit_keys,  int(limit))
    deep_set_all(p, offset_keys, int(offset))
    return p

def fetch_all_bonds(capture):
    api_url      = capture["api_url"]
    headers      = clean_headers(capture["request_headers"])
    base_payload = json.loads(capture["post_data"])
    sess         = req_lib.Session()

    def call(payload):
        r = sess.post(api_url, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    # Encontrar limit máximo efectivo
    best_limit, best_len, probe_total = None, -1, None
    for L in LIMIT_CANDIDATES:
        try:
            j     = call(set_paging(base_payload, offset=0, limit=L))
            batch = j.get("data") or []
            total = j.get("recordsTotal") or j.get("recordsFiltered")
            if total is not None:
                probe_total = int(total)
            if len(batch) > best_len:
                best_len   = len(batch)
                best_limit = L
        except:
            pass

    if not best_limit or best_len <= 0:
        raise RuntimeError("No se obtuvieron filas. Verificá el capture.")

    print(f"Limit óptimo: {best_limit} | filas/página: {best_len} | total: {probe_total}")

    # Paginar
    rows, offset, total = [], 0, probe_total or 10**12
    while offset < total:
        payload = set_paging(base_payload, offset=offset, limit=best_limit)
        j       = call(payload)
        batch   = j.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        if probe_total is None:
            t = j.get("recordsTotal") or j.get("recordsFiltered")
            if t:
                total = int(t)
        print(f"  ✓ offset {offset:>4} → +{len(batch)} (acum {len(rows)}/{total})")
        offset += best_len
        time.sleep(0.25)

    print(f"\n✅ {len(rows)} bonos descargados")
    return rows

# ── PASO 3: WRITE ─────────────────────────────────────────────
def flatten(obj, prefix=""):
    out = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if v is None:             out[key] = ""
        elif isinstance(v, bool): out[key] = "Si" if v else "No"
        elif isinstance(v, list): out[key] = ", ".join(str(x) for x in v)
        elif isinstance(v, dict): out.update(flatten(v, key))
        else:                     out[key] = v
    return out

LABELS = {
    "isin":"ISIN","wkn":"WKN","name":"Nombre",
    "instrumentName.translations.others":"Nombre (EN)",
    "lastPrice":"Último precio","currency":"Moneda","priceDate":"Fecha precio",
    "yield":"Yield (%)","coupon":"Cupón (%)","maturityDate":"Vencimiento",
    "termToMaturity":"Plazo (meses)","duration":"Duración",
    "modifiedDuration":"Duración mod.","accruedInterest":"Interés corrido (%)",
    "cleanPrice":"Precio limpio","issueDate":"Fecha emisión",
    "issueVolume":"Vol. emisión","minimumInvestment":"Inv. mínima",
    "issuerType":"Tipo emisor","bondType":"Tipo bono","interestType":"Tipo interés",
    "issuer":"Emisor","issuerInfo.name":"Emisor","rating":"Rating",
    "changeToPrevDayAbsolute":"Cambio (abs)","changeToPrevDayInPercent":"Cambio (%)",
    "greenBond":"Green Bond","callable":"Callable","subordinated":"Subordinado",
    "perpetual":"Perpetuo","convertible":"Convertible",
}

def write_to_sheets(bonds):
    print("Conectando a Google Sheets...")
    creds  = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    ss     = client.open_by_url(SPREADSHEET_URL)

    try:
        sheet = ss.worksheet(SHEET_NAME)
        sheet.clear()
    except gspread.WorksheetNotFound:
        sheet = ss.add_worksheet(SHEET_NAME, rows=2000, cols=80)

    flat    = [flatten(b) for b in bonds]
    keys    = list(dict.fromkeys(k for row in flat for k in row))
    headers = [LABELS.get(k, k) for k in keys]
    rows    = [[row.get(k, "") for k in keys] for row in flat]
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")

    all_data = (
        [[f"Fuente: live.deutsche-boerse.com  ·  Corp. Bonds USD · Tasa fija · Yield ≤8% · Plazo ≥12m  ·  Actualizado: {now}  ·  {len(bonds)} bonos"] + [""] * (len(keys)-1)] +
        [headers] +
        rows
    )

    print("Escribiendo en Google Sheets...")
    sheet.update(all_data[:500], value_input_option="USER_ENTERED")
    for i in range(500, len(all_data), 500):
        sheet.append_rows(all_data[i:i+500], value_input_option="USER_ENTERED")
        print(f"  {min(i, len(bonds))}/{len(bonds)} filas...", end="\r")

    ss.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId":sheet.id,"startRowIndex":1,"endRowIndex":2},
            "cell": {"userEnteredFormat": {
                "backgroundColor":{"red":0.08,"green":0.27,"blue":0.63},
                "textFormat":{"foregroundColor":{"red":1,"green":1,"blue":1},"bold":True},
                "horizontalAlignment":"CENTER"
            }},
            "fields":"userEnteredFormat"
        }},
        {"updateSheetProperties":{
            "properties":{"sheetId":sheet.id,"gridProperties":{"frozenRowCount":2}},
            "fields":"gridProperties.frozenRowCount"
        }},
        {"autoResizeDimensions":{
            "dimensions":{"sheetId":sheet.id,"dimension":"COLUMNS","startIndex":0,"endIndex":8}
        }},
    ]})

    print(f"\n✅ ¡Listo! {len(bonds)} bonos en '{SHEET_NAME}'")
    print(f"   {SPREADSHEET_URL}")

# ── MAIN ─────────────────────────────────────────────────────
async def main():
    capture = await sniff()
    bonds   = fetch_all_bonds(capture)
    write_to_sheets(bonds)

if __name__ == "__main__":
    asyncio.run(main())