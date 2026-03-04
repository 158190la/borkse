"""
Deutsche Börse Bond Analytics Dashboard
Correr: python dashboard.py
"""

import json, gspread, webbrowser, os, urllib.request
from google.oauth2.service_account import Credentials
from datetime import datetime

SPREADSHEET_URL  = "https://docs.google.com/spreadsheets/d/1UESwuK6nZQKksFDlxgioHLXQy5b_Fgo9OdFbc_hRWFw/edit?gid=304463295#gid=304463295"
CREDENTIALS_FILE = "credentials.json"
SHEET_NAME       = "Hoja 13"
OUTPUT_HTML      = "dashboard.html"

def fetch_treasury_yields():
    """
    Descarga yields del Tesoro desde FRED (Federal Reserve Bank of St. Louis).
    Todas las series son en AÑOS. DGS3MO (3 meses) fue removida para evitar
    confusión en la interpolación de la curva por plazo.
    Si alguna serie falla, se registra el error explícitamente.
    El fallback sólo se usa si TODAS las series fallan; nunca mezcla datos reales
    con datos inventados.
    """
    # Clave = plazo en años, valor = serie FRED (todas en años)
    series = {
        1:  "DGS1",
        2:  "DGS2",
        5:  "DGS5",
        7:  "DGS7",
        10: "DGS10",
        20: "DGS20",
        30: "DGS30",
    }
    yields = {}
    dates  = {}
    errors = []

    for years, sid in series.items():
        try:
            # URL estándar FRED — devuelve toda la serie hasta hoy
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                lines = r.read().decode().strip().split("\n")
            # Buscar el último valor no vacío ni "." (días festivos FRED usa ".")
            found = False
            for line in reversed(lines[1:]):
                parts = line.split(",")
                if len(parts) == 2 and parts[1] not in (".", "", "NA"):
                    yields[years] = float(parts[1])
                    dates[years]  = parts[0]
                    found = True
                    break
            if not found:
                errors.append(f"  WARNING: {sid} ({years}a) — ningún valor válido en la serie")
        except Exception as e:
            errors.append(f"  ERROR: {sid} ({years}a) — {e}")

    # Reportar errores individuales
    for err in errors:
        print(err)

    if yields:
        print(f"  Treasuries descargados ({len(yields)}/{len(series)}):")
        for y in sorted(yields.keys()):
            print(f"    {y:>2}a  {yields[y]:.3f}%  (fecha FRED: {dates[y]})")
        if len(yields) < len(series):
            missing = sorted(set(series.keys()) - set(yields.keys()))
            print(f"  WARNING: series faltantes en plazos {missing} — la interpolación será menos precisa")
    else:
        # Solo usar fallback si NINGUNA serie pudo descargarse
        print("  WARNING: no se pudo descargar ninguna yield de FRED.")
        print("  FALLBACK ACTIVADO — estos valores son estimados y pueden estar desactualizados:")
        yields = {1: 3.56, 2: 3.54, 5: 3.06, 7: 3.61, 10: 4.08, 20: 4.66, 30: 4.71}
        for y, v in sorted(yields.items()):
            print(f"    {y:>2}a  {v:.3f}%  *** FALLBACK ***")

    return yields

def get_treasury_yield(years, tsy):
    keys = sorted(tsy.keys())
    if years <= keys[0]:  return tsy[keys[0]]
    if years >= keys[-1]: return tsy[keys[-1]]
    for i in range(len(keys)-1):
        if keys[i] <= years <= keys[i+1]:
            t = (years-keys[i])/(keys[i+1]-keys[i])
            return tsy[keys[i]]*(1-t)+tsy[keys[i+1]]*t

def load_bonds():
    print("Leyendo Google Sheets...")
    creds  = Credentials.from_service_account_file(CREDENTIALS_FILE,
               scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    sheet  = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
    rows   = sheet.get_all_values()
    headers = rows[0]
    bonds   = [{headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))} for row in rows[1:]]
    print(f"OK: {len(bonds)} bonos leidos")
    return bonds

def to_float(v):
    if v in (None, "", "#N/A", "Cargando...", "#REF!"): return None
    try:    return float(str(v).replace(".","").replace(",",".").replace("%","").strip())
    except: return None

def process_bonds(bonds, tsy):
    processed = []
    today = datetime.now().year

    for b in bonds:
        try:
            ticker = (b.get("Ticker") or "").strip()
            if not ticker: continue
            y = to_float(b.get("keyData.yield"))
            if not y or y <= 0: continue

            venc_raw = to_float(b.get("anovenc"))
            years = None
            if venc_raw and venc_raw > 0:
                years = venc_raw  # ya es el plazo en años hasta vencimiento

            coupon = to_float(b.get("keyData.coupon"))
            dur = round(years * (0.70 if coupon and coupon > 0 else 0.95), 1) if years else None

            spread = None
            if years and years > 0:
                spread = round(y - get_treasury_yield(years, tsy), 3)

            issuer = (b.get("companyName") or b.get("name.originalValue") or "N/A").strip()[:35]
            name   = (b.get("name.originalValue") or issuer).strip()[:50]

            rating = (b.get("Rating") or "NR").strip()
            if rating in ("Cargando...", "#N/A", "#REF!", ""): rating = "NR"

            ru = rating.upper()
            if   "AAA" in ru:   r_bucket = "AAA"
            elif "AA"  in ru:   r_bucket = "AA"
            elif "BBB" in ru:   r_bucket = "BBB"
            elif "BB"  in ru:   r_bucket = "BB"
            elif "CCC" in ru:   r_bucket = "CCC"
            elif "A"   in ru:   r_bucket = "A"
            elif "B"   in ru:   r_bucket = "B"
            else:               r_bucket = "NR"

            if years:
                if years < 3:    t_bucket = "0-3a"
                elif years < 7:  t_bucket = "3-7a"
                elif years < 15: t_bucket = "7-15a"
                else:            t_bucket = "15+a"
            else:
                t_bucket = "N/D"

            processed.append({
                "name":       name,
                "issuer":     issuer,
                "isin":       b.get("isin",""),
                "ticker":     b.get("Ticker",""),
                "sector":     (b.get("sector") or "").strip(),
                "yield":      round(y, 3),
                "coupon":     coupon,
                "duration":   dur,
                "years":      round(years,1) if years else None,
                "maturity":   b.get("año vencimiento",""),
                "spread":     spread,
                "price":      to_float(b.get("lastQuote") or b.get("overview.lastPrice")),
                "rating":     rating,
                "r_bucket":   r_bucket,
                "t_bucket":   t_bucket,
                "perf1y":     to_float(b.get("performance1Year") or b.get("performance.performance1Year")),
                "structural": to_float(b.get("StructuralScore")),
                "stability":  to_float(b.get("StabilityScore")),
                "trend":      to_float(b.get("TrendScore")),
                "score":      to_float(b.get("FinalLDScore")),
            })
        except:
            continue

    print(f"OK: {len(processed)} bonos procesados")
    return processed

def generate_html(bonds, tsy):
    return TEMPLATE\
        .replace("__BONDS__", json.dumps(bonds, ensure_ascii=False))\
        .replace("__TSY__",   json.dumps(tsy,   ensure_ascii=False))

TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Bond Analytics - Deutsche Boerse</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');
:root{--bg:#0a0e1a;--surf:#111827;--bdr:#1e2d45;--acc:#00d4ff;--g:#7cfc00;--o:#ff6b35;--y:#ffd700;--txt:#e2e8f0;--mut:#64748b;--mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:var(--sans);font-size:14px}
header{border-bottom:1px solid var(--bdr);padding:16px 28px;display:flex;align-items:center;justify-content:space-between;background:linear-gradient(90deg,#0a0e1a,#0d1b2e)}
h1{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--acc);letter-spacing:.08em;text-transform:uppercase}
.meta{font-family:var(--mono);font-size:11px;color:var(--mut)}
.filters{display:flex;gap:10px;padding:10px 28px;background:var(--surf);border-bottom:1px solid var(--bdr);align-items:center;flex-wrap:wrap}
.fl{font-family:var(--mono);font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em}
select{background:var(--bg);color:var(--txt);border:1px solid var(--bdr);padding:4px 8px;font-family:var(--mono);font-size:11px;border-radius:3px;cursor:pointer}
select:focus{outline:1px solid var(--acc)}
.kpis{display:flex;gap:1px;background:var(--bdr);border-bottom:1px solid var(--bdr)}
.kpi{flex:1;background:var(--surf);padding:12px 18px}
.kl{font-family:var(--mono);font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px}
.kv{font-family:var(--mono);font-size:20px;font-weight:600;color:var(--acc)}
.ks{font-size:9px;color:var(--mut);margin-top:2px;font-family:var(--mono)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--bdr);padding:1px}
.panel{background:var(--surf);padding:20px}
.panel.wide{grid-column:1/-1}
.pt{font-family:var(--mono);font-size:9px;font-weight:600;color:var(--mut);text-transform:uppercase;letter-spacing:.1em;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;gap:8px}
.pt::before{content:'';display:inline-block;width:3px;height:10px;background:var(--acc)}
canvas{max-height:280px}
.hm{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
.hm th{padding:6px 8px;text-align:center;color:var(--mut);font-weight:600;border-bottom:1px solid var(--bdr);font-size:10px}
.hm td{padding:8px 10px;text-align:center;border:1px solid var(--bdr);cursor:default}
.hm td:hover{outline:2px solid var(--acc);position:relative;z-index:1}
.hm .rl{color:var(--mut);font-size:9px;text-align:left;white-space:nowrap}
.it{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
.it th{padding:6px 10px;text-align:right;color:var(--mut);font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--bdr);cursor:pointer;user-select:none;white-space:nowrap}
.it th:first-child{text-align:left}
.it th:hover{color:var(--acc)}
.it td{padding:6px 10px;border-bottom:1px solid rgba(30,45,69,.4);text-align:right;white-space:nowrap}
.it td:first-child{text-align:left}
.it td.sec{font-size:9px;color:var(--mut)}
.it tr:hover td{background:rgba(0,212,255,.04)}
.ybar{display:inline-block;height:2px;background:var(--acc);vertical-align:middle;margin-left:4px;border-radius:2px;opacity:.5}
.sg{color:var(--g)}.sa{color:var(--acc)}.sy{color:var(--y)}.so{color:var(--o)}.sm{color:var(--mut)}
</style>
</head>
<body>
<header>
  <h1>Deutsche Boerse — Bond Analytics</h1>
  <div class="meta" id="mi">—</div>
</header>
<div class="filters">
  <span class="fl">Rating:</span>
  <select id="fr" onchange="render()"><option value="">Todos</option><option>AAA</option><option>AA</option><option>A</option><option>BBB</option><option>BB</option><option>B</option><option>CCC</option><option>NR</option></select>
  <span class="fl">Plazo:</span>
  <select id="ft" onchange="render()"><option value="">Todos</option><option>0-3a</option><option>3-7a</option><option>7-15a</option><option>15+a</option></select>
  <span class="fl">Sector:</span>
  <select id="fs" onchange="render()"><option value="">Todos</option></select>
  <span class="fl">Yield min:</span>
  <select id="fy" onchange="render()"><option value="">-</option><option value="3">3%+</option><option value="4">4%+</option><option value="5">5%+</option><option value="6">6%+</option></select>
  <span class="fl">Spread min:</span>
  <select id="fsp" onchange="render()"><option value="">-</option><option value="100">100+ bps</option><option value="200">200+ bps</option><option value="300">300+ bps</option></select>
</div>
<div class="kpis">
  <div class="kpi"><div class="kl">Bonos</div><div class="kv" id="k1">-</div><div class="ks">en pantalla</div></div>
  <div class="kpi"><div class="kl">Yield avg</div><div class="kv" id="k2">-</div><div class="ks">media</div></div>
  <div class="kpi"><div class="kl">Spread avg</div><div class="kv" id="k3">-</div><div class="ks">vs UST</div></div>
  <div class="kpi"><div class="kl">Duracion avg</div><div class="kv" id="k4">-</div><div class="ks">estimada</div></div>
  <div class="kpi"><div class="kl">Yield max</div><div class="kv" id="k5">-</div><div class="ks" id="k5s">-</div></div>
  <div class="kpi"><div class="kl">Spread max</div><div class="kv" id="k6">-</div><div class="ks" id="k6s">-</div></div>
</div>
<div class="grid">
  <div class="panel"><div class="pt">Histograma de Yields</div><canvas id="ch"></canvas></div>
  <div class="panel"><div class="pt">Yield vs Duracion — por Rating</div><canvas id="cs"></canvas></div>
  <div class="panel"><div class="pt">Mapa de Calor — Yield avg por Rating x Plazo</div><div id="hm"></div></div>
  <div class="panel" id="hm-detail-panel">
    <div class="pt">Bonos del cuadrante <span id="hm-detail-title" style="color:var(--acc);font-weight:400;margin-left:6px;font-size:9px"></span></div>
    <div id="hm-detail-empty" style="color:var(--mut);font-family:var(--mono);font-size:11px;padding:20px 0">← Click en un cuadrante del mapa</div>
    <div style="overflow-y:auto;max-height:340px;display:none" id="hm-detail-scroll">
    <table class="it"><thead><tr>
      <th style="text-align:left">Nombre del bono</th>
      <th>Yield</th>
      <th>Años</th>
    </tr></thead><tbody id="hm-detail-body"></tbody></table>
    </div>
  </div>
  <div class="panel wide"><div class="pt">Curva de Rendimientos — Bonos por Rating vs US Treasuries</div><canvas id="ccurve" style="max-height:360px"></canvas></div>
  <div class="panel wide">
    <div class="pt">Resumen por Emisor <span style="font-weight:400;font-size:9px;margin-left:8px;color:var(--mut)">click para ordenar</span></div>
    <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
    <table class="it"><thead><tr>
      <th onclick="st('issuer')">Emisor</th>
      <th onclick="st('sector')">Sector</th>
      <th onclick="st('count')">#</th>
      <th onclick="st('ya')">Yield avg</th>
      <th onclick="st('ym')">Yield max</th>
      <th onclick="st('sa')">Spread avg</th>
      <th onclick="st('da')">Dur avg</th>
      <th onclick="st('perf1y')">Perf 1Y</th>
    </tr></thead><tbody id="ib"></tbody></table>
    </div>
  </div>

</div>
<script>
const B=__BONDS__;
const TSY_RAW=__TSY__;
let hC=null,sC=null,curveC=null,sc='ya',sa=false,iD=[];
const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
const cM={'AAA':'#00ff88','AA':'#7cfc00','A':'#00d4ff','BBB':'#ffd700','BB':'#ff9f40','B':'#ff6b35','CCC':'#ff4444','NR':'#64748b'};

// Interpolar treasury para cualquier plazo
function tsyYield(y){
  const keys=Object.keys(TSY_RAW).map(Number).sort((a,b)=>a-b);
  if(y<=keys[0])return TSY_RAW[keys[0]];
  if(y>=keys[keys.length-1])return TSY_RAW[keys[keys.length-1]];
  for(let i=0;i<keys.length-1;i++){
    if(keys[i]<=y&&y<=keys[i+1]){
      const t=(y-keys[i])/(keys[i+1]-keys[i]);
      return TSY_RAW[keys[i]]*(1-t)+TSY_RAW[keys[i+1]]*t;
    }
  }
}

const sectors=[...new Set(B.map(b=>b.sector).filter(Boolean))].sort();
const fsel=document.getElementById('fs');
sectors.forEach(s=>{const o=document.createElement('option');o.value=o.textContent=s;fsel.appendChild(o);});

function filt(){
  const r=document.getElementById('fr').value,t=document.getElementById('ft').value;
  const s=document.getElementById('fs').value,y=parseFloat(document.getElementById('fy').value)||0;
  const sp=parseFloat(document.getElementById('fsp').value)||0;
  return B.filter(b=>(!r||b.r_bucket===r)&&(!t||b.t_bucket===t)&&(!s||b.sector===s)&&b.yield>=y&&(sp===0||b.spread==null||(b.spread*100)>=sp));
}

function render(){
  const b=filt();
  const ys=b.map(x=>x.yield).filter(Boolean),ss=b.map(x=>x.spread).filter(x=>x!=null),ds=b.map(x=>x.duration).filter(Boolean);
  const mx=b.reduce((a,x)=>x.yield>(a?.yield||0)?x:a,null);
  const mxsp=b.filter(x=>x.spread!=null).reduce((a,x)=>x.spread>(a?.spread||0)?x:a,null);
  document.getElementById('k1').textContent=b.length;
  document.getElementById('k2').textContent=ys.length?avg(ys).toFixed(2)+'%':'-';
  document.getElementById('k3').textContent=ss.length?Math.round(avg(ss)*100)+' bps':'-';
  document.getElementById('k4').textContent=ds.length?avg(ds).toFixed(1)+'y':'-';
  document.getElementById('k5').textContent=mx?mx.yield.toFixed(2)+'%':'-';
  document.getElementById('k5s').textContent=mx?mx.issuer:'-';
  document.getElementById('k6').textContent=mxsp?Math.round(mxsp.spread*100)+' bps':'-';
  document.getElementById('k6s').textContent=mxsp?mxsp.issuer:'-';
  document.getElementById('mi').textContent=b.length+' bonos · Corp USD Fixed · Yield ≤8% · Plazo ≥12m';
  rHist(b);rScatter(b);rHeatmap(b);rCurve(b);rTable(b);
}

function rHist(b){
  const ys=b.map(x=>x.yield).filter(Boolean),bins={};
  ys.forEach(y=>{const k=(Math.floor(y*4)/4).toFixed(2);bins[k]=(bins[k]||0)+1;});
  const labs=Object.keys(bins).sort((a,b)=>+a-+b),data=labs.map(l=>bins[l]);
  if(hC)hC.destroy();
  hC=new Chart(document.getElementById('ch'),{type:'bar',data:{labels:labs,datasets:[{data,backgroundColor:labs.map(l=>+l>=6?'#7cfc00aa':+l>=5?'#00d4ffaa':+l>=4?'#ffd700aa':'#1e5f8a'),borderWidth:0,borderRadius:2}]},options:{plugins:{legend:{display:false},tooltip:{callbacks:{title:c=>`Yield: ${c[0].label}%`,label:c=>`${c.raw} bonos`},backgroundColor:'#111827',borderColor:'#1e2d45',borderWidth:1,bodyFont:{family:'IBM Plex Mono',size:11}}},scales:{x:{ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9}},grid:{color:'#1e2d45'}},y:{ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9}},grid:{color:'#1e2d45'}}}}});
}

function rScatter(b){
  const pts=b.filter(x=>x.duration&&x.yield).map(x=>({x:x.duration,y:x.yield,issuer:x.issuer,spread:x.spread,rb:x.r_bucket}));
  if(sC)sC.destroy();
  sC=new Chart(document.getElementById('cs'),{type:'scatter',data:{datasets:[{data:pts,backgroundColor:pts.map(p=>(cM[p.rb]||'#64748b')+'99'),borderColor:pts.map(p=>cM[p.rb]||'#64748b'),borderWidth:1,pointRadius:4,pointHoverRadius:7}]},options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.raw.issuer}\nYield: ${c.raw.y.toFixed(2)}%  Dur: ${c.raw.x.toFixed(1)}y\nSpread: ${c.raw.spread!=null?Math.round(c.raw.spread*100)+' bps':'N/D'}  [${c.raw.rb}]`},backgroundColor:'#111827',borderColor:'#1e2d45',borderWidth:1,bodyFont:{family:'IBM Plex Mono',size:11}}},scales:{x:{title:{display:true,text:'Duracion estimada (anos)',color:'#64748b',font:{family:'IBM Plex Mono',size:9}},ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9}},grid:{color:'#1e2d45'}},y:{title:{display:true,text:'Yield (%)',color:'#64748b',font:{family:'IBM Plex Mono',size:9}},ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9}},grid:{color:'#1e2d45'}}}}});
}


let hmBonds=[];
function rHeatmap(b){
  hmBonds=b;
  const RS=['AAA','AA','A','BBB','BB','B','CCC','NR'],TS=['0-3a','3-7a','7-15a','15+a'],g={};
  b.forEach(x=>{const k=x.r_bucket+'|'+x.t_bucket;if(!g[k])g[k]=[];g[k].push(x);});
  const avs=Object.values(g).map(v=>avg(v.map(x=>x.yield))).filter(Boolean);
  const mn=Math.min(...avs),mx=Math.max(...avs);
  function cc(y){if(!y)return'transparent';const t=(y-mn)/(mx-mn||1);return`rgba(${Math.round(10+t*245)},${Math.round(180-t*100)},${Math.round(210-t*200)},0.75)`;}
  function tc(y){return y&&y>(mn+mx)/2?'#0a0e1a':'#e2e8f0';}
  let h='<table class="hm"><thead><tr><th></th>';
  TS.forEach(t=>h+=`<th>${t}</th>`);h+='</tr></thead><tbody>';
  RS.forEach(r=>{
    h+=`<tr><td class="rl">${r}</td>`;
    TS.forEach(t=>{
      const k=r+'|'+t,vs=g[k]||[],a=avg(vs.map(x=>x.yield));
      h+=a
        ?`<td style="background:${cc(a)};color:${tc(a)};cursor:pointer" title="${vs.length} bonos | ${a.toFixed(2)}%" onclick="showHmDetail('${r}','${t}')"><div style="font-size:12px;font-weight:600">${a.toFixed(2)}%</div><div style="font-size:9px;opacity:.7">${vs.length}</div></td>`
        :`<td style="color:#1e2d45">—</td>`;
    });h+='</tr>';
  });
  document.getElementById('hm').innerHTML=h+'</tbody></table>';
}

function showHmDetail(r,t){
  const bonds=hmBonds.filter(x=>x.r_bucket===r&&x.t_bucket===t);
  bonds.sort((a,b)=>b.yield-a.yield);
  document.getElementById('hm-detail-title').textContent=`${r} · ${t} — ${bonds.length} bonos`;
  document.getElementById('hm-detail-body').innerHTML=bonds.map(b=>`
    <tr>
      <td style="text-align:left;max-width:400px;white-space:normal">${b.name}</td>
      <td class="${b.yield>=6?'sg':b.yield>=5?'sa':b.yield>=4?'sy':'sm'}">${b.yield.toFixed(2)}%</td>
      <td style="color:var(--mut)">${b.years!=null?b.years+'a':'—'}</td>
    </tr>`).join('');
  document.getElementById('hm-detail-empty').style.display='none';
  document.getElementById('hm-detail-scroll').style.display='block';
}

function rCurve(b){
  const xPts=[1,2,3,5,7,10,15,20,30];
  const tsyData=xPts.map(x=>({x,y:+tsyYield(x).toFixed(3)}));
  const ratingGroups=['AAA','AA','A','BBB','BB','B','CCC'];
  const ratingColors=['#00ff88','#7cfc00','#00d4ff','#ffd700','#ff9f40','#ff6b35','#ff4444'];
  const ratingDatasets=ratingGroups.map((r,i)=>{
    const bondsR=b.filter(x=>x.r_bucket===r&&x.years);
    if(!bondsR.length)return null;
    const pts=xPts.map(xp=>{
      const window=xp<=3?1.5:xp<=7?2:3;
      const near=bondsR.filter(x=>Math.abs(x.years-xp)<=window);
      if(!near.length)return null;
      return{x:xp,y:+avg(near.map(x=>x.yield)).toFixed(3)};
    }).filter(Boolean);
    if(pts.length<2)return null;
    return{label:r,data:pts,borderColor:ratingColors[i],backgroundColor:ratingColors[i]+'22',
      tension:.4,pointRadius:5,pointHoverRadius:8,fill:false,borderWidth:2};
  }).filter(Boolean);
  const tsyDs={label:'US Treasury',data:tsyData,borderColor:'#ffffff',backgroundColor:'#ffffff22',
    tension:.4,pointRadius:4,pointHoverRadius:7,fill:false,borderWidth:2,borderDash:[6,3]};
  if(curveC)curveC.destroy();
  curveC=new Chart(document.getElementById('ccurve'),{
    type:'line',
    data:{datasets:[tsyDs,...ratingDatasets]},
    options:{
      plugins:{
        legend:{labels:{color:'#94a3b8',font:{family:'IBM Plex Mono',size:11},usePointStyle:true}},
        tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.raw.y.toFixed(2)}%`},
          backgroundColor:'#111827',borderColor:'#1e2d45',borderWidth:1,bodyFont:{family:'IBM Plex Mono',size:11}}
      },
      scales:{
        x:{type:'linear',title:{display:true,text:'Plazo (años)',color:'#64748b',font:{family:'IBM Plex Mono',size:10}},
          ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9},callback:v=>v+'a'},
          grid:{color:'#1e2d45'},min:0,max:32},
        y:{title:{display:true,text:'Yield (%)',color:'#64748b',font:{family:'IBM Plex Mono',size:10}},
          ticks:{color:'#64748b',font:{family:'IBM Plex Mono',size:9},callback:v=>v+'%'},
          grid:{color:'#1e2d45'}}
      }
    }
  });
}


function rTable(b){
  const m={};
  b.forEach(x=>{const n=x.issuer||'N/A';if(!m[n])m[n]={issuer:n,sector:x.sector||'',ys:[],ss:[],ds:[],p1:[]};m[n].ys.push(x.yield);if(x.spread!=null)m[n].ss.push(x.spread*100);if(x.duration)m[n].ds.push(x.duration);if(x.perf1y!=null)m[n].p1.push(x.perf1y);});
  iD=Object.values(m).map(v=>({issuer:v.issuer,sector:v.sector,count:v.ys.length,ya:+avg(v.ys).toFixed(2),ym:+Math.max(...v.ys).toFixed(2),sa:v.ss.length?+avg(v.ss).toFixed(0):null,da:v.ds.length?+avg(v.ds).toFixed(1):null,perf1y:v.p1.length?+avg(v.p1).toFixed(1):null}));
  rSorted();
}

function st(c){sc===c?sa=!sa:(sc=c,sa=false);rSorted();}

function rSorted(){
  const s=[...iD].sort((a,b)=>{const va=a[sc]??-Infinity,vb=b[sc]??-Infinity;return typeof va==='string'?(sa?va.localeCompare(vb):vb.localeCompare(va)):(sa?va-vb:vb-va);});
  const mx=Math.max(...s.map(r=>r.ym||0));
  document.getElementById('ib').innerHTML=s.map(r=>`<tr>
    <td>${r.issuer}</td>
    <td class="sec">${r.sector||'—'}</td>
    <td style="color:var(--mut)">${r.count}</td>
    <td class="${r.ya>=6?'sg':r.ya>=5?'sa':r.ya>=4?'sy':'sm'}">${r.ya.toFixed(2)}%<span class="ybar" style="width:${Math.round(r.ya/mx*44)}px"></span></td>
    <td class="${r.ym>=6?'sg':r.ym>=5?'sa':r.ym>=4?'sy':'sm'}">${r.ym.toFixed(2)}%</td>
    <td style="color:${r.sa>=300?'#7cfc00':r.sa>=200?'#00d4ff':r.sa>=100?'#ffd700':'#64748b'}">${r.sa!=null?r.sa+' bps':'—'}</td>
    <td style="color:var(--mut)">${r.da!=null?r.da+'y':'—'}</td>
    <td class="${r.perf1y>0?'sg':r.perf1y<0?'so':'sm'}">${r.perf1y!=null?r.perf1y+'%':'—'}</td>
  </tr>`).join('');
}

render();
</script>
</body>
</html>"""

def main():
    print("Descargando tasas del Tesoro...")
    tsy   = fetch_treasury_yields()
    bonds = load_bonds()
    processed = process_bonds(bonds, tsy)
    if not processed:
        print("ERROR: 0 bonos procesados.")
        return
    html = generate_html(processed, tsy)
    with open(OUTPUT_HTML,"w",encoding="utf-8") as f:
        f.write(html)
    print(f"OK: {OUTPUT_HTML} generado")
    webbrowser.open(f"file://{os.path.abspath(OUTPUT_HTML)}")

if __name__ == "__main__":
    main()
