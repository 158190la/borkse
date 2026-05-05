# LDWM Borkse — Contexto del proyecto

## Qué es esto
Portal de research interno para **LD Wealth Management** (ldwm.ar).
Archivo principal: `research (10).html` — single-page app con múltiples pestañas.

## Pestañas actuales
| ID | Nombre | Descripción |
|----|--------|-------------|
| `home` | Home | Cards de acceso rápido |
| `dashboard` | Bonos ARG | Tabla de bonos globales |
| `lecaps` | LECAPs | Curva de tasa fija + comparador |
| `fci` | FCI | Fondos comunes argentinos |
| `mercados` | Mercados | Monitor de mercados |
| `parte` | Parte Diario | Generación con GPT |
| `globales` | Globales | Bonos internacionales |
| `monetario` | Monitor AR | BCRA + monetario |
| `predictor` | Predictor | Macro 2026 dual escenario |
| `usmonitor` | US Monitor | Mercado americano |
| `insider` | Insider US | Form 4 SEC trades |
| `scraper` | Scraper | Actualizar datos |
| `rotation` | Rotation ✅ | Rotation Indicator (nuevo) |
| `tasas` | Tasas ARG ✅ | Curvas de rendimiento (nuevo) |

## Arquitectura JS
- Cada pestaña tiene su propio IIFE al final del `<script>` global
- `showPage(id)` maneja navegación y lazy init
- `window.AR_STATE` = objeto global con datos del mercado:
  - `oficial`, `embi`, `ipcMensual`, `m2Var30d`, `resVar30d`, `reservas`
  - `temLecapAvg`, `teaLecapAvg`, `lcData` ← desde `lcProcess()`
  - `cerRealAnual`, `cerData` ← desde `lcProcessCer()`
  - `monUpdated`, `lecapUpdated`, `cerUpdated`

## APIs usadas
- `https://data912.com/live/arg_notes` — LECAPs / LECERs
- `https://data912.com/live/arg_bonds` — BONCAPs / BONCERs / DLK
- `https://api.bcra.gob.ar/estadisticas/v4.0/monetarias` — BCRA
- `https://api.argentinadatos.com/v1` — IPC, EMBI, letras
- `https://dolarapi.com/v1/dolares/bolsa` — MEP
- `https://dolarapi.com/v1/dolares/contadoconliqui` — CCL

## Variables globales clave
```js
LC_DATA   // array bonos fija (LECAP/BONCAP): {sym, tipo, venc, dias, precio, tea, tem, ...}
CER_DATA  // array bonos CER (LECER/BONCER): {sym, tipo, venc, dias, precio, ask}
VF_MAP    // valor de corte por símbolo (LECAP/BONCAP)
VT_CER_MAP // valor técnico estimado por símbolo (CER)
```

## Funciones expuestas en window
- `monLoad()` — carga Monitor Monetario + popula AR_STATE
- `lcLoad()` — carga LECAPs + CER desde data912
- `rotInit()`, `rotSyncFromState()`, `rotComputeAndRender()`, `rotSaveSnap()`, `rotDeleteSnap()`, `rotRefresh()`
- `tasasInit()`, `tasasSync()`, `tasasRefresh()`, `tasSwitchTab(tab)`

## Trabajo pendiente
1. **index.html** — Rediseño con Three.js globo 3D interactivo (tema dark navy/gold). Ver conversación.
2. **Rotation Indicator** — JS completo ✅ — HTML/CSS ✅
3. **Tasas Argentinas** — JS completo ✅ — HTML/CSS ✅

## Rama de desarrollo
`claude/review-repository-BHUC0`

## Credenciales (no commitear cambios)
- Login: admin / ldwm2026

## Sitio web público
- `ldwm.ar` — landing page (index.html a rediseñar con Three.js)
- `ldwm.ar/research.html` — portal interno
