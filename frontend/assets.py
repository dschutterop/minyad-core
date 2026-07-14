"""Static CSS/JS assets embedded into every frontend page.

FRONTEND_BUILD_ID hashes every .py file in this directory (not just this one)
so the browser auto-refresh script correctly detects changes anywhere in the
frontend, not only edits to this file.
"""

from __future__ import annotations

import os
import time
from hashlib import sha256
from pathlib import Path

FRONTEND_BUILD_ID = os.getenv("MINYAD_FRONTEND_VERSION") or sha256(
    b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
).hexdigest()[:16]
FRONTEND_VERSION = f"{FRONTEND_BUILD_ID}:{int(time.time())}"


FRONTEND_BUILD_ID = os.getenv("MINYAD_FRONTEND_VERSION") or sha256(Path(__file__).read_bytes()).hexdigest()[:16]


FRONTEND_VERSION = f"{FRONTEND_BUILD_ID}:{int(time.time())}"


BRAND_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root{--paper:#EDF1F4;--paper-2:#E2E8ED;--ink:#15202A;--steel:#4A6276;--hair:rgba(21,32,42,.09);--panel:#0E151C;--panel-2:#15202B;--panel-3:#1D2A37;--p-ink:#E6EDF2;--p-mut:rgba(230,237,242,.55);--p-line:rgba(150,182,208,.13);--produce:#2E9C62;--store:#D89B2A;--import:#CE4940;--produce-d:#46C684;--store-d:#F0B441;--import-d:#F26A60;--home-d:#E6EDF2;--mono:"IBM Plex Mono",ui-monospace,monospace;--sans:"Space Grotesk",ui-sans-serif,system-ui,sans-serif;--ease:cubic-bezier(.2,.7,.3,1)}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:var(--sans);letter-spacing:-.01em}a{color:inherit}.brand-shell{min-height:100vh;padding:38px clamp(16px,6vw,64px) 56px}.brand-header{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:36px}.brand-lockup{display:flex;align-items:center;gap:14px;text-decoration:none}.mark{width:30px;height:30px;overflow:visible}.mark line{stroke:var(--steel);stroke-width:1.5;stroke-linecap:round}.mark circle{fill:var(--paper);stroke:var(--steel);stroke-width:1.5}.wordmark{display:grid;gap:4px}.wordmark strong{font-size:24px;line-height:1;font-weight:700;letter-spacing:-.04em}.wordmark span,.brand-nav a,.label,.kicker,.status-pill,.scale-label,.tile-name,.window-tab,.chart-legend,.unit,.value{font-family:var(--mono);font-feature-settings:"tnum";font-variant-numeric:tabular-nums}.wordmark span{font-size:9px;color:var(--steel);letter-spacing:.32em;text-transform:uppercase}.brand-nav{display:flex;gap:18px;flex-wrap:wrap}.brand-nav a{text-decoration:none;color:var(--steel);font-size:11px;letter-spacing:.18em;text-transform:uppercase}.brand-nav a.active{color:var(--ink)}.brand-main{max-width:1180px;margin:auto}.card{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}.kicker{display:flex;align-items:center;gap:16px;color:var(--steel);font-size:11px;letter-spacing:.34em;text-transform:uppercase}.kicker:after{content:"";height:1px;width:86px;background:rgba(74,98,118,.22)}.page-title{font-size:clamp(42px,7vw,72px);line-height:.95;margin:22px 0 22px;letter-spacing:-.065em}.page-copy{max-width:800px;color:rgba(21,32,42,.68);font-size:20px;line-height:1.55}.instrument{background:var(--panel);color:var(--p-ink);border:1px solid rgba(150,182,208,.18);border-radius:18px;box-shadow:0 26px 70px rgba(14,21,28,.18);overflow:hidden}.dashboard-page{margin:0;min-height:100vh;background:var(--panel)}.dashboard-full{min-height:100vh;border:0;border-radius:0;box-shadow:none}.dashboard-nav{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 24px;border-bottom:1px solid var(--p-line);background:var(--panel)}.dashboard-nav .brand-nav a{color:var(--p-mut)}.dashboard-nav .brand-nav a.active{color:var(--p-ink)}.dashboard-nav .wordmark strong{color:var(--p-ink)}.dashboard-nav .wordmark span{color:var(--p-mut)}.dashboard-nav .mark circle{fill:var(--panel)}.dashboard-full .views{padding-bottom:32px}.dashboard-full .flow-board{height:calc(100vh - 220px);min-height:560px}.window-bar{height:62px;border-bottom:1px solid var(--p-line);display:flex;align-items:center;justify-content:space-between;padding:0 20px}.traffic{display:flex;gap:10px}.traffic i{width:10px;height:10px;border-radius:50%;background:#304455}.traffic i:nth-child(1){background:var(--import-d)}.traffic i:nth-child(2){background:var(--store-d)}.traffic i:nth-child(3){background:var(--produce-d)}.window-tab{background:#0A1016;border:1px solid var(--p-line);border-radius:7px;color:var(--p-mut);font-size:11px;letter-spacing:.08em;padding:9px 14px}.layout-toggle{display:flex;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;padding:4px}.layout-toggle button{margin:0;border:0;background:transparent;color:var(--p-mut);font:600 11px/1 var(--mono);letter-spacing:.1em;padding:9px 13px;border-radius:6px;cursor:pointer}.layout-toggle button.active{background:var(--panel-3);color:var(--p-ink)}.window-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;margin-left:auto}.dash-head{display:flex;justify-content:flex-end;gap:18px;align-items:start;padding:28px 28px 10px}.dash-title{display:flex;gap:14px;align-items:center}.dash-title .mark circle{fill:var(--panel)}.dash-title strong{font-size:22px}.dash-meta{text-align:right;color:var(--p-mut);font-family:var(--mono);font-size:13px;line-height:1.7;font-feature-settings:"tnum"}.self{color:var(--produce-d)}.views{position:relative;padding:0 26px 28px}.view{display:none;animation:fade .24s var(--ease)}.view.active{display:block}@keyframes fade{from{opacity:.25}to{opacity:1}}.tile-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.tile{background:var(--panel-2);border:1px solid var(--p-line);border-left:3px solid var(--steel);border-radius:11px;padding:18px;min-width:0}.tile.produce{border-left-color:var(--produce-d)}.tile.store{border-left-color:var(--store-d)}.tile.import{border-left-color:var(--import-d)}.tile.household{border-left-color:var(--p-ink)}.tile-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.tile-name{font-size:12px;text-transform:uppercase;letter-spacing:.16em;color:var(--p-mut);display:flex;align-items:center;gap:8px}.icon{width:22px;height:22px;fill:none;stroke:var(--steel);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.phrase{font-family:var(--mono);font-feature-settings:"tnum";font-size:clamp(34px,5vw,54px);line-height:1;color:var(--p-ink);letter-spacing:-.04em;transition:color .24s var(--ease)}.phrase .unit{font-size:.55em;color:currentColor;letter-spacing:0}.produce-c{color:var(--produce-d)}.store-c{color:var(--store-d)}.import-c{color:var(--import-d)}.household-c{color:var(--home-d)}.steel-c{color:var(--p-mut)}.bar{position:relative;height:8px;margin:20px 0 8px;border:1px solid var(--p-line);border-radius:999px;background:#0A1016;overflow:hidden}.bar .fill{position:absolute;top:0;bottom:0;width:0;background:var(--steel);transition:width .24s var(--ease),left .24s var(--ease),right .24s var(--ease)}.bar.center:after{content:"";position:absolute;left:50%;top:-5px;bottom:-5px;width:1px;background:rgba(230,237,242,.38)}.scale{display:flex;justify-content:space-between;gap:8px}.scale-label{font-size:10px;color:var(--p-mut);white-space:nowrap}.status-pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--p-line);border-radius:999px;padding:6px 9px;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--p-mut)}.status-pill i{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 0 rgba(230,237,242,0);transition:background .24s var(--ease),box-shadow .24s var(--ease),opacity .24s var(--ease)}.status-pill.flash i{animation:pill-flash 1s ease-in-out infinite;box-shadow:0 0 14px currentColor}.status-pill:not(.flash) i{opacity:.55}@keyframes pill-flash{0%,100%{opacity:1;transform:scale(1);box-shadow:0 0 7px currentColor}50%{opacity:.45;transform:scale(1.45);box-shadow:0 0 18px currentColor}}.soc{margin-top:18px}.soc-gauge{position:relative}.cells{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;margin:8px 0}.cells i{height:18px;border:1px solid var(--p-line);border-radius:3px;background:#0A1016}.cells i.on{background:var(--store-d);border-color:rgba(240,180,65,.5)}.soc-limit{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--p-ink);box-shadow:0 0 0 1px #0A1016;transform:translateX(-1px);opacity:.9}.soc-limit.max{background:var(--produce-d)}.soc-limit.min{background:var(--import-d)}.soc-limit-labels{position:relative;height:16px;margin-top:2px}.soc-limit-label{position:absolute;top:0;transform:translateX(-50%);font-family:var(--mono);font-size:9px;line-height:1;color:var(--p-mut);white-space:nowrap}.soc-limit-label.min{color:var(--import-d)}.soc-limit-label.max{color:var(--produce-d)}.thin{height:5px;background:#0A1016;border:1px solid var(--p-line);border-radius:999px;overflow:hidden}.thin i{display:block;height:100%;background:var(--produce-d)}.chart-card{margin-top:14px;background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:18px}.chart-top,.daystrip{display:flex;justify-content:space-between;gap:16px;align-items:center}.chart-legend{display:flex;gap:10px;flex-wrap:wrap;color:var(--p-mut);font-size:11px}.chart-legend button{border:0;background:transparent;color:inherit;padding:4px 6px;border-radius:6px;cursor:pointer;font:inherit;opacity:1}.chart-legend button:hover,.chart-legend button:focus-visible{background:var(--panel-3);outline:none}.chart-legend button[aria-pressed="false"]{opacity:.38;text-decoration:line-through}.chart-legend i{display:inline-block;width:18px;height:2px;margin-right:5px;vertical-align:middle;background:currentColor}.chart-wrap{position:relative}.chart{width:100%;height:300px;margin-top:10px}.chart-tooltip{position:absolute;z-index:5;min-width:190px;pointer-events:none;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;color:var(--p-ink);padding:10px 12px;box-shadow:0 16px 40px rgba(0,0,0,.35);font-family:var(--mono);font-size:11px;line-height:1.45;transform:translate(-50%,calc(-100% - 12px))}.chart-tooltip[hidden]{display:none}.chart-tooltip b{display:block;margin-bottom:4px;font-size:12px}.chart-tooltip span{display:block;color:var(--p-mut)}.chart-hover{fill:transparent;pointer-events:stroke;stroke:transparent;stroke-width:16}.chart-marker{stroke:var(--p-ink);stroke-width:1;stroke-dasharray:2 4}.chart-dot{stroke:#0A1016;stroke-width:2}.sparkline{width:100%;height:54px;margin-top:12px}.sparkline path{fill:none;stroke:var(--p-ink);stroke-width:2}.load-meta{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.badge.warn{border-color:rgba(240,180,65,.5);color:var(--store-d)}.axis,.gridline{stroke:var(--p-line);stroke-width:1}.zero-line{stroke:rgba(230,237,242,.38);stroke-width:1.4}.forecast-fill{fill:rgba(74,98,118,.18)}.forecast-line{fill:none;stroke:rgba(150,182,208,.48);stroke-width:2;stroke-dasharray:6 6}.prod-line{fill:none;stroke:var(--produce-d);stroke-width:2.6}.prod-fill{fill:rgba(70,198,132,.12)}.bat-line{fill:none;stroke:var(--store-d);stroke-width:2}.bat-charge-fill{fill:rgba(240,180,65,.14)}.bat-discharge-fill{fill:rgba(216,155,42,.18)}.grid-line{fill:none;stroke:var(--import-d);stroke-width:2}.home-line{fill:none;stroke:var(--p-mut);stroke-width:2.4}.pv-uncertainty-band{fill:rgba(150,182,208,.16);stroke:none}.load-forecast-line{fill:none;stroke:var(--home-d);stroke-width:1.7;stroke-dasharray:6 7;opacity:.7}.grid-forecast-line{fill:none;stroke:var(--import-d);stroke-width:1.7;stroke-dasharray:6 7;opacity:.7}.curtailment-line{fill:none;stroke:#E8B04A;stroke-width:1.4;stroke-dasharray:2 3}.grid-import-fill{fill:rgba(242,106,96,.16)}.grid-export-fill{fill:rgba(70,198,132,.14)}.imp-fill{fill:rgba(242,106,96,.16)}.exp-fill{fill:rgba(70,198,132,.14)}.now{stroke:var(--p-ink);stroke-width:1;stroke-dasharray:3 5}.daystrip{margin-top:14px;border-top:1px solid var(--p-line);padding-top:14px}.daystrip div{min-width:0}.daystrip b{display:block;font-family:var(--mono);font-feature-settings:"tnum";font-size:22px}.daystrip span{font-family:var(--mono);font-size:10px;color:var(--p-mut);letter-spacing:.1em;text-transform:uppercase}.flow-board{height:560px;position:relative;background:radial-gradient(circle at 50% 43%,rgba(29,42,55,.8),transparent 34%);border:1px solid var(--p-line);border-radius:12px;margin-top:14px}.flow-svg{position:absolute;inset:0;width:100%;height:100%}.flow-line{fill:none;stroke-width:4;stroke-linecap:round;opacity:.8}.flow-dot{animation:drift 2s linear infinite}@keyframes drift{to{offset-distance:100%}}.flow-node{position:absolute;transform:translate(-50%,-50%);background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:14px;width:170px;text-align:center}.flow-node.solar{left:50%;top:18%}.flow-node.home{left:50%;top:48%;border-color:rgba(230,237,242,.3)}.flow-node.battery{left:25%;top:78%}.flow-node.grid{left:75%;top:78%}.flow-node .phrase{font-size:26px}.mobile-readout{display:none}.mobile-rows{display:grid;gap:10px}.mobile-row{display:flex;justify-content:space-between;border-top:1px solid var(--p-line);padding-top:10px}.status-card,.overview-card,.panel,.flow-panel{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}input{width:100%;margin-top:8px;border:1px solid rgba(74,98,118,.25);background:#fff;padding:11px 12px;font:inherit;color:var(--ink)}button{font-family:var(--mono)}pre{background:#111827;color:#eef2f7;padding:16px;overflow:auto}.grid:not(.flow-node),.metric-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--hair);border:1px solid var(--hair)}.grid:not(.flow-node)>*{background:var(--paper);padding:14px}.error{color:var(--import)}@media(max-width:1100px){.tile-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.dashboard-nav{align-items:flex-start;flex-direction:column;padding:14px}.brand-shell{padding:18px 12px}.brand-header{align-items:flex-start;flex-direction:column}.instrument{border-radius:14px}.dash-head,.window-bar{padding-left:14px;padding-right:14px}.tile-grid{grid-template-columns:1fr}.chart{height:220px}.daystrip{display:grid;grid-template-columns:repeat(2,1fr)}.desktop-only{display:none}.mobile-readout{display:block;padding:0 14px 18px}.flow-board{height:520px}.dashboard-full .flow-board{height:520px;min-height:520px}.flow-node{width:140px}.flow-node.battery{left:22%}.flow-node.grid{left:78%}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;transition-duration:.001ms!important;scroll-behavior:auto!important}.flow-dot{display:none}.status-pill.flash i{animation:none}}

.history-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.history-tab{border:1px solid rgba(74,98,118,.25);background:#fff;color:var(--steel);border-radius:999px;padding:10px 14px;cursor:pointer;font:700 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase}.history-tab.active{background:var(--panel);color:var(--p-ink);border-color:var(--panel)}.history-period-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.history-period-controls button{border:1px solid rgba(74,98,118,.25);background:#fff;color:var(--steel);border-radius:8px;padding:9px 11px;cursor:pointer;font:700 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase}.history-period-controls button:hover,.history-period-controls button:focus-visible{background:rgba(237,241,244,.86);outline:none}.history-period-controls button:disabled{opacity:.42;cursor:not-allowed}.history-period-label{min-width:160px;text-align:center;color:var(--steel);font:700 11px/1.2 var(--mono);letter-spacing:.08em;text-transform:uppercase}.history-panel{display:none}.history-panel.active{display:block}.history-toolbar{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.history-hint{color:rgba(21,32,42,.62);font-family:var(--mono);font-size:11px}.history-chart-card{background:#fff;border:1px solid rgba(74,98,118,.18);border-radius:14px;padding:18px;margin-top:12px}.history-chart{width:100%;height:420px;touch-action:none}.history-mini{width:100%;height:78px;margin-top:10px;cursor:crosshair}.history-window{fill:rgba(74,98,118,.16);stroke:rgba(74,98,118,.55);stroke-width:1.5}.history-brush{fill:rgba(46,156,98,.18);stroke:var(--produce);stroke-width:1.5}.history-tooltip{position:absolute;z-index:6;min-width:210px;pointer-events:none;background:#fff;border:1px solid rgba(74,98,118,.22);border-radius:10px;color:var(--ink);padding:10px 12px;box-shadow:0 16px 40px rgba(14,21,28,.16);font-family:var(--mono);font-size:11px;line-height:1.45;transform:translate(-50%,calc(-100% - 10px))}.history-tooltip[hidden]{display:none}.history-empty{padding:28px;text-align:center;color:var(--steel);font-family:var(--mono);border:1px dashed rgba(74,98,118,.28);border-radius:12px}.history-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.history-stat{background:rgba(237,241,244,.86);border:1px solid rgba(74,98,118,.16);border-radius:10px;padding:12px}.history-stat b{display:block;font-family:var(--mono);font-size:22px}.history-stat span{color:var(--steel);font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.1em}@media(max-width:860px){.history-chart{height:300px}.history-stats{grid-template-columns:repeat(2,1fr)}.history-period-label{min-width:120px;text-align:left}}

.solar-hero{display:grid;grid-template-columns:1fr minmax(260px,360px);gap:18px;align-items:stretch}.solar-total{background:var(--panel);color:var(--p-ink);border-color:rgba(150,182,208,.18);display:flex;flex-direction:column;justify-content:space-between}.solar-total .phrase{font-size:clamp(44px,6vw,68px)}.solar-overview{margin-top:18px;background:var(--panel);color:var(--p-ink);border:1px solid rgba(150,182,208,.18);border-radius:14px;padding:20px}.solar-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:14px}.inverter-card{background:var(--panel-2);border:1px solid var(--p-line);border-left:3px solid var(--produce-d);border-radius:11px;padding:14px}.inverter-card b{display:block;font-family:var(--mono);font-size:18px;margin:8px 0}.inverter-card .bar{margin:12px 0 8px}.solar-empty{border:1px dashed var(--p-line);border-radius:12px;padding:22px;color:var(--p-mut);font-family:var(--mono);text-align:center}.solar-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}.array-list{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.array-pill{border:1px solid var(--p-line);border-radius:999px;padding:7px 10px;color:var(--p-mut);font-family:var(--mono);font-size:11px}@media(max-width:860px){.solar-hero{grid-template-columns:1fr}}
"""


THEME_BOOT_SCRIPT = """
<script>
(() => {
  const KEY = 'minyad.theme';
  const apply = (theme) => {
    const resolved = theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = theme;
  };
  const saved = localStorage.getItem(KEY) || 'system';
  apply(saved);
  window.minyadTheme = {
    key: KEY,
    apply,
    async load() {
      try {
        const res = await fetch('/api/system-settings');
        if (!res.ok) throw new Error('theme settings unavailable');
        const data = await res.json();
        const theme = data.theme || 'system';
        localStorage.setItem(KEY, theme);
        apply(theme);
        return theme;
      } catch (_) {
        apply(localStorage.getItem(KEY) || 'system');
        return localStorage.getItem(KEY) || 'system';
      }
    },
    async save(theme) {
      localStorage.setItem(KEY, theme);
      apply(theme);
      const res = await fetch('/api/system-settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({theme})
      });
      if (!res.ok) throw new Error('Unable to save theme');
      return res.json();
    }
  };
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem(KEY) || 'system') === 'system') apply('system');
  });
  window.minyadTheme.load();
})();
</script>
"""


LANGUAGE_BOOT_SCRIPT = """
<script>
(() => {
  const KEY = 'minyad.language';
  const supported = new Set(['en', 'nl']);
  const dictionaries = {
    en: {
      'Zelfvoorziening vandaag': 'Self-sufficiency today',
      'laden...': 'loading...',
      'vandaag': 'today',
      'Batterij': 'Battery',
      'laden': 'charge',
      'ontladen': 'discharge',
      'Net': 'Grid',
      'Huis': 'Home',
      'Dagoverzicht': 'Day overview',
      'Batterijstatus': 'Battery status',
      'Netstatus': 'Grid status',
      'Zelfvoorziening': 'Self-sufficiency',
      'Vandaag': 'Today',
      'Dag': 'Day',
      'Maand': 'Month',
      'Jaar': 'Year',
      'Laden...': 'Loading...',
      'Geen historische punten beschikbaar voor deze periode.': 'No historical points available for this period.',
      'sleep onderaan om te zoomen': 'drag below to zoom',
      'Laat de Claude-agentcontainer normaal draaien, maar beheer runtime of de agent Claude.ai/API-aanroepen mag doen. Wijzigingen vereisen geen containerrestart.': 'Keep the Claude agent container running normally, but control at runtime whether the agent may make Claude.ai/API calls. Changes do not require a container restart.',
      'Claude agent inschakelen': 'Enable Claude agent',
      'Token guard inschakelen': 'Enable token guard',
      'Minimum tokens overhouden': 'Minimum tokens to keep',
      'geschat': 'estimated',
      'Kan dashboarddata niet laden:': 'Unable to load dashboard data:',
      'Nog geen dagpunten beschikbaar.': 'No day points available yet.',
      'Tip: sleep over de onderste mini-grafiek om een periode te selecteren. Dubbelklik boven of onder om terug uit te zoomen.': 'Tip: drag over the lower mini graph to select a period. Double-click above or below to zoom back out.',
    },
    nl: {
      'Dashboard': 'Dashboard',
      'Agent': 'Agent',
      'Health': 'Status',
      'History': 'Historie',
      'Trade': 'Handel',
      'Solar': 'Zon',
      'Battery': 'Batterij',
      'Asset Steering': 'Assetsturing',
      'Reporting': 'Rapportage',
      'Settings': 'Instellingen',
      'Virtual Power Plant': 'Virtuele energiecentrale',
      'Primary navigation': 'Hoofdnavigatie',
      'Power unit': 'Vermogenseenheid',
      'Watts': 'Watt',
      'Kilowatts': 'Kilowatt',
      'Dashboard layout': 'Dashboardweergave',
      'Cluster': 'Cluster',
      'Flow': 'Flow',
      'Agent mailbox': 'Agentpostvak',
      'Close': 'Sluiten',
      'Subject': 'Onderwerp',
      'Message or task for the agent...': 'Bericht of taak voor de agent...',
      'Send to agent': 'Naar agent sturen',
      'Messages': 'Berichten',
      'Archive': 'Archief',
      'Loading...': 'Laden...',
      'Select a message.': 'Selecteer een bericht.',
      'Reply': 'Antwoorden',
      'Delete': 'Verwijderen',
      'Ack': 'Bevestigen',
      'Self-sufficiency today': 'Zelfvoorziening vandaag',
      'Solar - now': 'Zon - nu',
      'Solar': 'Zon',
      'Producing': 'Produceert',
      'Standby': 'Stand-by',
      'Battery': 'Batterij',
      'Grid': 'Net',
      'Importing': 'Importeert',
      'Exporting': 'Exporteert',
      'Home Consumption': 'Thuisverbruik',
      'Live': 'Live',
      'Approx': 'Geschat',
      'mismatch': 'afwijking',
      'Combined day graph - kW / EUR/kWh': 'Gecombineerde daggrafiek - kW / EUR/kWh',
      'Forecast': 'Prognose',
      'Production': 'Productie',
      'Home': 'Thuis',
      'Day-ahead prices': 'Day-ahead prijzen',
      'kWh produced': 'kWh geproduceerd',
      'kWh self used': 'kWh zelf verbruikt',
      'kWh exported': 'kWh geexporteerd',
      'kWh imported': 'kWh geimporteerd',
      'charge': 'laden',
      'discharge': 'ontladen',
      'import': 'import',
      'export': 'export',
      'kWh today': 'kWh vandaag',
      'kWh imported today': 'kWh vandaag geimporteerd',
      'exported': 'geexporteerd',
      'Settings sections': 'Instellingensecties',
      'Battery control': 'Batterijregeling',
      'Charging, discharge and inverter limits': 'Laad-, ontlaad- en omvormerlimieten',
      'Energy trade': 'Energiehandel',
      'Day-ahead price collection and retry behavior': 'Day-ahead prijzen ophalen en retrygedrag',
      'Runtime access and token guard': 'Runtime-toegang en tokenbewaking',
      'Appearance': 'Weergave',
      'Light, dark or system theme': 'Licht, donker of systeemthema',
      'System': 'Systeem',
      'Debug logging and diagnostics': 'Debuglogging en diagnostiek',
      'Effective values from /battery/settings.': 'Effectieve waarden uit /battery/settings.',
      'Start surplus W': 'Startoverschot W',
      'Stop surplus W': 'Stopoverschot W',
      'Start duration s': 'Startduur s',
      'Stop duration s': 'Stopduur s',
      'Cooldown s': 'Afkoeling s',
      'Max charge W': 'Max laden W',
      'Max charge A': 'Max laden A',
      'Nominal battery V': 'Nominale batterijspanning V',
      'Max discharge W': 'Max ontladen W',
      'Minimum SoC %': 'Minimale SoC %',
      'Maximum SoC %': 'Maximale SoC %',
      'Inverter IP': 'Omvormer-IP',
      'Retries': 'Pogingen',
      'Retry delay s': 'Retryvertraging s',
      'GoodWe poll interval s': 'GoodWe pollinterval s',
      'GoodWe poll interval grace s': 'GoodWe pollintervalmarge s',
      'Save battery settings': 'Batterijinstellingen opslaan',
      'EPEX day-ahead collection settings. Changes are published to MQTT and picked up without restarting the trade price collector.': 'EPEX day-ahead verzamelinstellingen. Wijzigingen worden naar MQTT gepubliceerd en opgepakt zonder de trade price collector te herstarten.',
      'Bidding zone': 'Biedzone',
      'Poll time Europe/Amsterdam': 'Ophaaltijd Europa/Amsterdam',
      'Retry attempts': 'Aantal pogingen',
      'Retry interval minutes': 'Retry-interval minuten',
      'Day-ahead price API URL': 'Day-ahead price API-URL',
      'Save trade settings': 'Handelsinstellingen opslaan',
      'Claude agent': 'Claude-agent',
      'Current status:': 'Huidige status:',
      'Enable Claude agent': 'Claude-agent inschakelen',
      'Enable token guard': 'Tokenbewaking inschakelen',
      'Minimum tokens to keep': 'Minimum tokens overhouden',
      'Save Claude agent settings': 'Claude-agentinstellingen opslaan',
      'Choose how Minyad should render every web interface. The preference is saved server-side and cached locally for instant page loads.': 'Kies hoe Minyad elke webinterface weergeeft. De voorkeur wordt server-side opgeslagen en lokaal gecachet voor snelle paginaladingen.',
      'Theme preference': 'Themakeuze',
      'System default': 'Systeemstandaard',
      'Follow this device': 'Volg dit apparaat',
      'Light': 'Licht',
      'Bright interface': 'Lichte interface',
      'Dark': 'Donker',
      'Low-light interface': 'Donkere interface',
      'Language': 'Taal',
      'Choose the display language for Minyad.': 'Kies de weergavetaal voor Minyad.',
      'English': 'Engels',
      'Dutch': 'Nederlands',
      'Debug logging': 'Debuglogging',
      'Debug status': 'Debugstatus',
      'Refresh now': 'Nu vernieuwen',
      'Battery status': 'Batterijstatus',
      'State:': 'Status:',
      'Power flow:': 'Vermogen:',
      'Voltage:': 'Spanning:',
      'Charge current:': 'Laadstroom:',
      'Battery mode:': 'Batterijmodus:',
      'Charge setpoint:': 'Laadsetpoint:',
      'Discharge setpoint:': 'Ontlaadsetpoint:',
      'Bridge status:': 'Bridgestatus:',
      'Bridge last seen:': 'Bridge laatst gezien:',
      'Override:': 'Override:',
      'Battery override': 'Batterij-override',
      'Force charge': 'Forceer laden',
      'Force stop': 'Forceer stop',
      'Force discharge': 'Forceer ontladen',
      'Pause (1h)': 'Pauze (1u)',
      'Resume normal': 'Normaal hervatten',
      'DSMR grid status': 'DSMR-netstatus',
      'Live data from the minyad/grid MQTT topic.': 'Live data uit het minyad/grid MQTT-topic.',
      'Status:': 'Status:',
      'Timestamp:': 'Tijdstempel:',
      'Net power:': 'Netvermogen:',
      'Delivered:': 'Geleverd:',
      'Returned:': 'Teruggeleverd:',
      'Micro-inverter overview': 'Micro-omvormeroverzicht',
      'Live Enphase micro-inverter production. Each panel is represented by its micro-inverter and shows the currently reported wattage.': 'Live Enphase micro-omvormerproductie. Elk paneel wordt weergegeven door zijn micro-omvormer en toont het actuele wattage.',
      'Updated': 'Bijgewerkt',
      'Total now': 'Totaal nu',
      'Panels / micro-inverters': 'Panelen / micro-omvormers',
      'reporting': 'rapporteren',
      'Control decisions': 'Regelbesluiten',
      'A paginated audit trail of battery control decisions and setpoint writes.': 'Een gepagineerd auditlog van batterijbesluiten en setpoint-wijzigingen.',
      'Previous 50': 'Vorige 50',
      'Next 50': 'Volgende 50',
      'Refresh': 'Vernieuwen',
      'Time': 'Tijd',
      'Source': 'Bron',
      'Action': 'Actie',
      'Setpoint': 'Setpoint',
      'Delta': 'Delta',
      'Limits': 'Limieten',
      'Reason': 'Reden',
      'Loading decisions...': 'Besluiten laden...',
      'Day-ahead prices': 'Day-ahead prijzen',
      'Live dashboard for the trade price collector. It reads the retained day-ahead price payload and graphs hourly EUR/kWh values.': 'Live dashboard voor de trade price collector. Het leest de retained day-ahead prijzen en tekent uurlijkse EUR/kWh waarden.',
      'lowest EUR/kWh': 'laagste EUR/kWh',
      'average EUR/kWh': 'gemiddelde EUR/kWh',
      'highest EUR/kWh': 'hoogste EUR/kWh',
      'hourly points': 'uurpunten',
      'Health': 'Status',
      'Last checked': 'Laatst gecontroleerd',
      'Refresh now': 'Nu vernieuwen',
      'Service': 'Service',
      'Detail': 'Detail',
      'Endpoint': 'Endpoint',
      'Last seen': 'Laatst gezien',
      'No service health checks returned.': 'Geen servicestatussen ontvangen.',
      'Last decision': 'Laatste besluit',
      'Setpoint': 'Setpoint',
      'Confidence': 'Vertrouwen',
      'Unread messages': 'Ongelezen berichten',
      'Latest 25': 'Laatste 25',
      'Latest 50': 'Laatste 50',
      'Latest 100': 'Laatste 100',
      'Send a message to the agent': 'Stuur een bericht naar de agent',
      'Message or task for the agent...': 'Bericht of taak voor de agent...',
      'Asset steering': 'Assetsturing',
      'Manage the strategy thresholds that steer battery charging and discharging. Values are stored as strategy.* settings and consumed by the strategy/control services.': 'Beheer de strategiedrempels die laden en ontladen sturen. Waarden worden opgeslagen als strategy.* instellingen en gebruikt door de strategie-/controlservices.',
      'Save asset steering': 'Assetsturing opslaan',
      'Recent steering activity': 'Recente stuuractiviteit',
      'Refresh activity': 'Activiteit vernieuwen',
      'Latest decision:': 'Laatste besluit:',
      'Latest setpoint:': 'Laatste setpoint:',
    }
  };
  const normalize = (text) => text.replace(/[\\u2013\\u2014]/g, '-').replace(/\\u2026/g, '...').replace(/\\s+/g, ' ').trim();
  const translateText = (text, language) => dictionaries[language]?.[normalize(text)];
  const translateAttributes = (root, language) => {
    root.querySelectorAll('[placeholder],[aria-label],[title]').forEach((el) => {
      for (const attr of ['placeholder', 'aria-label', 'title']) {
        const value = el.getAttribute(attr);
        const translated = value && translateText(value, language);
        if (translated) el.setAttribute(attr, translated);
      }
    });
  };
  const walk = (root, language) => {
    const skip = new Set(['SCRIPT', 'STYLE', 'CODE', 'PRE', 'TEXTAREA']);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return node.parentElement && skip.has(node.parentElement.tagName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const translated = translateText(node.nodeValue, language);
      if (translated) node.nodeValue = node.nodeValue.replace(node.nodeValue.trim(), translated);
    }
  };
  const apply = (language) => {
    const next = supported.has(language) ? language : 'en';
    document.documentElement.lang = next;
    document.documentElement.dataset.language = next;
    localStorage.setItem(KEY, next);
    if (document.body) {
      walk(document.body, next);
      translateAttributes(document.body, next);
    }
  };
  window.minyadI18n = {
    key: KEY,
    apply,
    t(text) {
      return translateText(text, localStorage.getItem(KEY) || 'en') || text;
    },
    async load() {
      try {
        const res = await fetch('/api/system-settings');
        if (!res.ok) throw new Error('language settings unavailable');
        const data = await res.json();
        apply(data.language || 'en');
        return data.language || 'en';
      } catch (_) {
        apply(localStorage.getItem(KEY) || 'en');
        return localStorage.getItem(KEY) || 'en';
      }
    },
    async save(language) {
      apply(language);
      const res = await fetch('/api/system-settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({language})
      });
      if (!res.ok) throw new Error('Unable to save language');
      return res.json();
    }
  };
  document.addEventListener('DOMContentLoaded', () => {
    apply(localStorage.getItem(KEY) || 'en');
    window.minyadI18n.load();
    let timer = null;
    new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => apply(localStorage.getItem(KEY) || 'en'), 50);
    }).observe(document.body, {childList: true, subtree: true});
  });
})();
</script>
"""


AUTO_REFRESH_SCRIPT = f"""
<script>
(() => {{
  const currentVersion = {FRONTEND_VERSION!r};
  let reloading = false;
  async function checkFrontendVersion() {{
    if (reloading) return;
    try {{
      const res = await fetch('/frontend-version', {{cache: 'no-store'}});
      if (!res.ok) return;
      const data = await res.json();
      if (data.version && data.version !== currentVersion) {{
        reloading = true;
        window.location.reload();
      }}
    }} catch (_) {{}}
  }}
  window.addEventListener('focus', checkFrontendVersion);
  document.addEventListener('visibilitychange', () => {{
    if (document.visibilityState === 'visible') checkFrontendVersion();
  }});
  setInterval(checkFrontendVersion, 15000);
  setTimeout(checkFrontendVersion, 3000);
}})();
</script>
"""


BRAND_CSS += """
.mailbox-button{position:relative;border:1px solid var(--p-line);background:#0A1016;color:var(--p-ink);border-radius:9px;padding:9px 12px;cursor:pointer;font:600 16px/1 var(--mono)}
.mailbox-button .badge{position:absolute;right:-7px;top:-7px;min-width:18px;height:18px;border-radius:999px;background:var(--import-d);color:#fff;border:1px solid rgba(255,255,255,.25);font:700 10px/17px var(--mono);text-align:center;padding:0 4px}
.mailbox-button .badge[hidden],.mailbox-panel[hidden],.message-detail[hidden]{display:none}
.mailbox-panel{position:absolute;right:26px;top:132px;z-index:20;width:min(760px,calc(100vw - 32px));max-height:78vh;overflow:auto;background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;box-shadow:0 28px 80px rgba(0,0,0,.35);padding:14px}
.mailbox-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.mailbox-tabs{display:flex;gap:8px;margin:10px 0}.mailbox-tabs button{border:1px solid var(--p-line);background:#0A1016;color:var(--p-ink);border-radius:999px;padding:7px 11px;cursor:pointer}.mailbox-tabs button.active{background:var(--p-ink);color:#0A1016}
.mailbox-layout{display:grid;grid-template-columns:minmax(190px,.9fr) minmax(260px,1.4fr);gap:12px;margin-top:12px}.mailbox-list{display:grid;align-content:start;gap:8px;max-height:42vh;overflow:auto}.mailbox-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.mailbox-item{width:100%;text-align:left;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;color:var(--p-ink);padding:10px;cursor:pointer;font-weight:400}.mailbox-item.active{border-color:var(--p-ink)}
.mailbox-item.unread{border-color:rgba(230,237,242,.34);font-weight:800}.mailbox-subject{display:flex;align-items:center;justify-content:space-between;gap:8px}.message-checks{white-space:nowrap;font:800 13px/1 var(--mono);letter-spacing:-.32em;color:var(--p-mut);padding-right:.32em}.message-checks .human.ack{color:#22C55E}.message-checks .agent.ack{color:#3B82F6}
.mailbox-item small{display:block;color:var(--p-mut);font:500 10px/1.5 var(--mono);letter-spacing:.08em;text-transform:uppercase}
@media(max-width:680px){.mailbox-layout{grid-template-columns:1fr}.mailbox-panel{right:16px}.mailbox-list{max-height:30vh}}
.severity-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:var(--p-mut)}
.severity-dot.high{background:var(--import-d)}.severity-dot.normal{background:var(--store-d)}.severity-dot.low{background:var(--steel)}
.message-detail{margin-top:10px;border-top:1px solid var(--p-line);padding-top:10px;color:var(--p-ink)}
.message-detail p{white-space:pre-wrap;color:var(--p-mut);line-height:1.45}
.reply-box input,.reply-box textarea{width:100%;margin-top:8px;border:1px solid var(--p-line);border-radius:8px;background:#0A1016;color:var(--p-ink);padding:10px;font:inherit}
.reply-box textarea{min-height:82px}
.reply-box button,.mailbox-head button,.mailbox-actions button{border:1px solid var(--p-line);background:#0A1016;color:var(--p-ink);border-radius:8px;padding:8px 10px;cursor:pointer}
"""


BRAND_CSS += """
html[data-theme=dark]{--paper:#071017;--paper-2:#101b24;--ink:#E6EDF2;--steel:#9DB1C1;--hair:rgba(184,210,228,.14)}
html[data-theme=dark] body:not(.dashboard-page){background:radial-gradient(circle at top,#142636 0,#071017 38rem);color:var(--ink)}
html[data-theme=dark] .card,html[data-theme=dark] .status-card,html[data-theme=dark] .overview-card,html[data-theme=dark] .panel,html[data-theme=dark] .flow-panel{background:rgba(16,27,36,.92);border-color:rgba(184,210,228,.14);color:var(--ink)}
html[data-theme=dark] .page-copy,html[data-theme=dark] .history-hint{color:rgba(230,237,242,.68)}
html[data-theme=dark] input,html[data-theme=dark] select{background:#0A1016;border-color:rgba(184,210,228,.18);color:var(--ink)}
html[data-theme=dark] .grid:not(.flow-node)>*{background:var(--paper)}
html[data-theme=dark] .history-tab,html[data-theme=dark] .history-period-controls button,html[data-theme=dark] .history-chart-card,html[data-theme=dark] .history-tooltip{background:#101b24;color:var(--ink);border-color:rgba(184,210,228,.14)}
html[data-theme=dark] .history-period-label{color:var(--steel)}
html[data-theme=dark] .history-stat{background:#0A1016;border-color:rgba(184,210,228,.14)}
html[data-theme=dark] form button,html[data-theme=dark] .secondary{background:#E6EDF2;color:#071017;border:1px solid rgba(230,237,242,.3)}
html[data-theme=light] .dashboard-page,html[data-theme=light] .dashboard-full,html[data-theme=light] .dashboard-nav{background:#EDF1F4;color:#15202A}
html[data-theme=light] .dashboard-full,html[data-theme=light] .dashboard-nav,html[data-theme=light] .window-bar{border-color:rgba(74,98,118,.22)}
html[data-theme=light] .dashboard-nav .wordmark strong,html[data-theme=light] .dashboard-nav .brand-nav a.active,html[data-theme=light] .dash-title strong,html[data-theme=light] .phrase{color:#15202A}
html[data-theme=light] .dashboard-nav .brand-nav a,html[data-theme=light] .dashboard-nav .wordmark span,html[data-theme=light] .dash-meta,html[data-theme=light] .tile-name,html[data-theme=light] .scale-label,html[data-theme=light] .chart-legend{color:#4A6276}
html[data-theme=light] .dashboard-nav .mark circle,html[data-theme=light] .dash-title .mark circle{fill:#EDF1F4}
html[data-theme=light] .tile,html[data-theme=light] .chart-card,html[data-theme=light] .flow-node{background:#fff;border-color:rgba(74,98,118,.18)}
html[data-theme=light] .window-tab,html[data-theme=light] .layout-toggle,html[data-theme=light] .layout-toggle button.active,html[data-theme=light] .bar,html[data-theme=light] .thin,html[data-theme=light] .cells i,html[data-theme=light] .chart-tooltip,html[data-theme=light] .mailbox-button,html[data-theme=light] .mailbox-item,html[data-theme=light] .reply-box input,html[data-theme=light] .reply-box textarea,html[data-theme=light] .reply-box button,html[data-theme=light] .mailbox-head button{background:#fff;color:#15202A;border-color:rgba(74,98,118,.18)}
html[data-theme=light] .cells i.on{background:var(--store-d);border-color:rgba(216,155,42,.55)}
html[data-theme=light] .mailbox-panel{background:#fff;border-color:rgba(74,98,118,.18)}
.theme-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.theme-option{border:1px solid rgba(74,98,118,.22);border-radius:12px;padding:14px;background:rgba(255,255,255,.5)}.theme-option input{width:auto;margin:0 8px 0 0}.theme-option b{display:block}.theme-option span{display:block;color:var(--steel);font-size:13px;margin-top:4px}@media(max-width:700px){.theme-options{grid-template-columns:1fr}}
.settings-layout{display:grid;grid-template-columns:minmax(210px,260px) minmax(0,1fr);gap:18px;align-items:start}.settings-nav{position:sticky;top:18px;display:grid;gap:8px}.settings-nav button{width:100%;display:grid;gap:4px;text-align:left;border:1px solid rgba(74,98,118,.2);border-radius:12px;background:rgba(255,255,255,.48);color:var(--ink);padding:14px 16px;cursor:pointer}.settings-nav button strong{font:700 13px/1.2 var(--mono);letter-spacing:.06em;text-transform:uppercase}.settings-nav button span{color:var(--steel);font-size:12px;line-height:1.35}.settings-nav button.active{background:var(--panel);color:var(--p-ink);border-color:var(--panel)}.settings-nav button.active span{color:var(--p-mut)}.settings-section{display:none}.settings-section.active{display:block}.settings-section h2{margin-top:0}.settings-section pre:empty{display:none}html[data-theme=dark] .settings-nav button{background:rgba(16,27,36,.92);color:var(--ink);border-color:rgba(184,210,228,.14)}html[data-theme=dark] .settings-nav button.active{background:#E6EDF2;color:#071017;border-color:#E6EDF2}html[data-theme=dark] .settings-nav button.active span{color:#4A6276}@media(max-width:800px){.settings-layout{grid-template-columns:1fr}.settings-nav{position:static;display:flex;overflow-x:auto;padding-bottom:4px;scrollbar-width:thin}.settings-nav button{min-width:190px}.settings-section{scroll-margin-top:12px}}

.agent-hero{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.agent-stat{background:#fff;border:1px solid rgba(74,98,118,.18);border-radius:12px;padding:16px}.agent-stat b{display:block;font-family:var(--mono);font-size:26px}.agent-layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(320px,.75fr);gap:16px}.agent-list{display:grid;gap:10px}.agent-decision,.agent-message-card{background:#fff;border:1px solid rgba(74,98,118,.18);border-left:4px solid var(--steel);border-radius:12px;padding:14px}.agent-decision.charge{border-left-color:var(--store)}.agent-decision.discharge{border-left-color:var(--produce)}.agent-decision.hold{border-left-color:var(--steel)}.agent-decision header,.agent-message-card header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.agent-meta{font-family:var(--mono);font-size:11px;color:var(--steel);letter-spacing:.08em;text-transform:uppercase}.agent-reason{white-space:pre-wrap;line-height:1.45}.agent-controls{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.agent-controls button{border:1px solid rgba(74,98,118,.25);background:#fff;border-radius:999px;padding:10px 14px;cursor:pointer}.agent-controls button.active{background:var(--panel);color:var(--p-ink)}.agent-compose-toggle{width:100%;border:1px solid rgba(74,98,118,.25);background:var(--panel);color:var(--p-ink);border-radius:12px;padding:13px 16px;cursor:pointer;text-align:left;display:flex;align-items:center;justify-content:space-between;gap:12px}.agent-compose-toggle:after{content:"+";font-size:18px}.agent-compose-toggle[aria-expanded="true"]:after{content:"–"}.agent-compose-panel[hidden]{display:none}.agent-compose-panel{margin-top:12px}.agent-compose{display:grid;grid-template-columns:1fr;gap:10px}.agent-compose textarea{width:100%;min-height:120px;margin-top:8px;border:1px solid rgba(74,98,118,.25);background:#fff;padding:11px 12px;font:inherit;color:var(--ink)}.agent-compose button[type=submit]{border:1px solid rgba(74,98,118,.25);background:#fff;border-radius:999px;padding:10px 14px;cursor:pointer}.agent-snapshot{max-height:260px}.agent-empty{border:1px dashed rgba(74,98,118,.28);border-radius:12px;padding:24px;text-align:center;color:var(--steel);font-family:var(--mono)}html[data-theme=dark] .agent-stat,html[data-theme=dark] .agent-decision,html[data-theme=dark] .agent-message-card,html[data-theme=dark] .agent-controls button,html[data-theme=dark] .agent-compose textarea,html[data-theme=dark] .agent-compose button[type=submit]{background:#101b24;color:var(--ink);border-color:rgba(184,210,228,.14)}html[data-theme=dark] .agent-controls button.active{background:#E6EDF2;color:#071017}@media(max-width:900px){.agent-hero{grid-template-columns:repeat(2,1fr)}.agent-layout{grid-template-columns:1fr}}
.report-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0}.report-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.report-actions button{border:1px solid rgba(74,98,118,.25);background:#fff;border-radius:999px;padding:9px 13px;cursor:pointer}.report-actions button:disabled{opacity:.45;cursor:not-allowed}.report-table-wrap{overflow:auto;border:1px solid rgba(74,98,118,.18);border-radius:12px;background:#fff}.report-table{width:100%;border-collapse:collapse;min-width:1080px}.report-table th,.report-table td{padding:10px 12px;border-bottom:1px solid rgba(74,98,118,.12);text-align:left;vertical-align:top}.report-table th{position:sticky;top:0;background:#fff;color:var(--steel);font:700 10px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase}.report-table td{font-family:var(--mono);font-size:12px}.report-reason{font-family:var(--sans)!important;min-width:300px;max-width:520px;white-space:normal;line-height:1.35}.report-action{display:inline-flex;border-radius:999px;padding:4px 8px;font:700 10px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;background:rgba(74,98,118,.12);color:var(--steel)}.report-action.charge{background:rgba(216,155,42,.16);color:var(--store)}.report-action.discharge{background:rgba(46,156,98,.16);color:var(--produce)}.report-action.hold{background:rgba(74,98,118,.12);color:var(--steel)}.report-empty{padding:24px;text-align:center;color:var(--steel);font-family:var(--mono)}html[data-theme=dark] .report-actions button,html[data-theme=dark] .report-table-wrap,html[data-theme=dark] .report-table th{background:#101b24;color:var(--ink);border-color:rgba(184,210,228,.14)}html[data-theme=dark] .report-table th,html[data-theme=dark] .report-table td{border-bottom-color:rgba(184,210,228,.1)}
.health-shell{display:grid;gap:16px}.health-summary{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.health-summary-main{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.health-updated{color:var(--steel);font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase}.health-actions{display:flex;align-items:center;gap:10px}.health-refresh{border:1px solid rgba(74,98,118,.25);background:#fff;color:var(--ink);border-radius:8px;padding:10px 12px;cursor:pointer;font:700 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase}.health-refresh:hover,.health-refresh:focus-visible{background:rgba(237,241,244,.86);outline:none}.health-table-wrap{overflow:auto;border:1px solid rgba(74,98,118,.18);border-radius:12px;background:#fff}.health-table{width:100%;min-width:760px;border-collapse:collapse}.health-table th,.health-table td{padding:13px 14px;border-bottom:1px solid rgba(74,98,118,.12);text-align:left;vertical-align:middle}.health-table th{background:#F8FAFC;color:var(--steel);font:700 10px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase}.health-table tr:last-child td{border-bottom:0}.health-service{font-weight:700}.health-detail{color:rgba(21,32,42,.72);line-height:1.35}.health-meta{font-family:var(--mono);font-size:12px;color:var(--steel);font-variant-numeric:tabular-nums}.health-status{display:inline-flex;align-items:center;gap:8px;min-width:70px;border:1px solid currentColor;border-radius:999px;padding:7px 10px;font:800 11px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase}.health-status i{width:8px;height:8px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor}.health-ok{color:var(--produce)}.health-nok{color:var(--import)}.health-warn{color:var(--store)}.health-empty{padding:24px;text-align:center;color:var(--steel);font-family:var(--mono)}html[data-theme=dark] .health-refresh,html[data-theme=dark] .health-table-wrap{background:#101b24;color:var(--ink);border-color:rgba(184,210,228,.14)}html[data-theme=dark] .health-table th{background:#0A1016;color:var(--steel);border-bottom-color:rgba(184,210,228,.12)}html[data-theme=dark] .health-table td{border-bottom-color:rgba(184,210,228,.10)}html[data-theme=dark] .health-detail{color:rgba(230,237,242,.72)}html[data-theme=dark] .health-refresh:hover,html[data-theme=dark] .health-refresh:focus-visible{background:#162631}@media(max-width:720px){.health-summary{align-items:flex-start}.health-table{min-width:640px}.health-table th,.health-table td{padding:11px 12px}.health-shell .page-title{font-size:clamp(38px,12vw,52px)}}
"""


BRAND_CSS += """
body.dashboard-page{--panel:#08111A;--panel-2:#101A24;--panel-3:#162434;--p-ink:#F4F7FA;--p-mut:rgba(226,235,243,.64);--p-line:rgba(184,210,228,.16);--produce-d:#4CDB83;--store-d:#FFC247;--import-d:#FF635C;--home-d:#F3F7FB;--steel:#9AAABA;background:radial-gradient(circle at 50% -10%,rgba(50,82,112,.32),transparent 38rem),linear-gradient(180deg,#071018 0,#08111A 42%,#05090E 100%);color:var(--p-ink);font-family:var(--sans);letter-spacing:0}
body.dashboard-page .instrument,body.dashboard-page .dashboard-full{background:transparent;border:0;box-shadow:none}
body.dashboard-page .dashboard-nav{background:transparent;border:0;padding:20px 26px 8px}
body.dashboard-page .brand-lockup{gap:12px}
body.dashboard-page .wordmark strong{color:var(--p-ink);font-family:var(--mono);font-size:17px;font-weight:600;letter-spacing:.26em;text-transform:uppercase}
body.dashboard-page .wordmark span{display:none}
body.dashboard-page .brand-nav{display:flex;gap:12px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
body.dashboard-page .brand-nav a{color:rgba(226,235,243,.46);font-family:var(--mono);font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;text-decoration:none;padding:7px 0;border-bottom:1px solid transparent}
body.dashboard-page .brand-nav a:hover,body.dashboard-page .brand-nav a:focus-visible{color:var(--p-ink);outline:none}
body.dashboard-page .brand-nav a.active{color:var(--produce-d);border-bottom-color:var(--produce-d)}
body.dashboard-page .mark{width:28px;height:28px;filter:drop-shadow(0 0 10px rgba(76,219,131,.32))}
body.dashboard-page .mark line,body.dashboard-page .mark circle{stroke:var(--produce-d)}
body.dashboard-page .mark circle{fill:#08111A}
body.dashboard-page .window-bar{height:auto;border:0;display:flex;justify-content:flex-end;padding:2px 26px 8px;background:transparent}
body.dashboard-page .window-actions{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-left:0}
body.dashboard-page .layout-toggle,body.dashboard-page .segmented-control{display:flex;gap:3px;padding:4px;border:1px solid rgba(184,210,228,.14);border-radius:999px;background:rgba(5,10,15,.48)}
body.dashboard-page .layout-toggle button,body.dashboard-page .segmented-control button{border:0;background:transparent;color:rgba(226,235,243,.58);border-radius:999px;padding:8px 12px;font:600 10px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
body.dashboard-page .layout-toggle button.active,body.dashboard-page .segmented-control button.active{background:rgba(244,247,250,.12);color:var(--p-ink);box-shadow:inset 0 0 0 1px rgba(244,247,250,.04)}
body.dashboard-page .mailbox-button{border:1px solid rgba(184,210,228,.14);background:rgba(5,10,15,.48);color:var(--p-ink);border-radius:999px;box-shadow:none}
body.dashboard-page .dash-head{margin-top:0;padding:0 26px 18px}
body.dashboard-page .dash-meta{font-family:var(--mono);font-size:12px;line-height:1.45;color:rgba(244,247,250,.62);letter-spacing:.02em}
body.dashboard-page .views{padding:0 26px 28px}
body.dashboard-page .tile-grid{gap:16px;align-items:stretch}
body.dashboard-page .tile,body.dashboard-page .chart-card,body.dashboard-page .flow-node,body.dashboard-page .mailbox-panel{background:linear-gradient(180deg,rgba(16,26,36,.88),rgba(9,17,26,.9));border:1px solid var(--p-line);border-left-width:1px;border-radius:14px;box-shadow:0 0 0 1px rgba(255,255,255,.02),0 18px 48px rgba(0,0,0,.25);backdrop-filter:blur(10px)}
body.dashboard-page .tile{min-width:0}
body.dashboard-page .metric-card{min-height:262px;padding:20px;display:grid;grid-template-rows:auto auto minmax(92px,1fr) auto;gap:13px;align-content:stretch}
body.dashboard-page .tile.produce{border-left:2px solid var(--produce-d);box-shadow:0 0 32px rgba(76,219,131,.08)}
body.dashboard-page .tile.store{border-left:2px solid var(--store-d);box-shadow:0 0 32px rgba(255,194,71,.08)}
body.dashboard-page .tile.battery-card{--battery-accent:#888780;border-left:2px solid var(--battery-accent);box-shadow:0 0 0 1px rgba(255,255,255,.02),0 18px 48px rgba(0,0,0,.25),0 0 32px color-mix(in srgb,var(--battery-accent) 8%,transparent);transition:color .4s,background-color .4s,border-color .4s}
body.dashboard-page .battery-card .store-c,body.dashboard-page .battery-card .status-pill{color:var(--battery-accent);transition:color .4s,background-color .4s,border-color .4s}
body.dashboard-page .battery-card .bar .fill{background:var(--battery-accent);transition:width .24s var(--ease),left .24s var(--ease),right .24s var(--ease),color .4s,background-color .4s,border-color .4s}
body.dashboard-page .battery-card .status-pill{border-color:var(--battery-accent);background:color-mix(in srgb,var(--battery-accent) 12%,transparent);transition:color .4s,background-color .4s,border-color .4s}
body.dashboard-page .battery-card .status-pill i{background:var(--battery-accent);transition:color .4s,background-color .4s,border-color .4s}
body.dashboard-page .tile.import{border-left:2px solid var(--import-d);box-shadow:0 0 32px rgba(255,99,92,.08)}
body.dashboard-page .tile.household{border-left:2px solid rgba(244,247,250,.9)}
body.dashboard-page .tile-head{margin-bottom:0;gap:14px}
body.dashboard-page .metric-card-head{display:flex;align-items:center;justify-content:space-between;min-height:27px}
body.dashboard-page .tile-name{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.095em;color:rgba(244,247,250,.76);line-height:1.35;text-transform:uppercase}
body.dashboard-page .icon{width:23px;height:23px;stroke:currentColor;opacity:.82}
body.dashboard-page .metric-value-row{display:grid;gap:5px;align-content:start}
body.dashboard-page .phrase{font-family:var(--mono);font-size:clamp(42px,4.8vw,60px);font-weight:500;line-height:.95;letter-spacing:0;text-shadow:0 0 20px color-mix(in srgb,currentColor 20%,transparent);font-variant-numeric:tabular-nums}
body.dashboard-page .phrase .unit{font-size:.42em;font-weight:500;margin-left:6px;color:currentColor;vertical-align:baseline}
body.dashboard-page .metric-subtitle{font-family:var(--mono);font-size:11px;line-height:1.4;color:rgba(226,235,243,.62);letter-spacing:.04em;text-transform:uppercase}
body.dashboard-page .metric-visual{display:grid;gap:9px;align-content:center;min-height:92px}
body.dashboard-page .visual-stack{display:grid;gap:8px}
body.dashboard-page .metric-footer{display:flex;align-items:end;justify-content:space-between;gap:12px;min-height:34px;padding-top:10px;border-top:1px solid rgba(184,210,228,.10);font-family:var(--mono)}
body.dashboard-page .footer-stat{display:grid;gap:2px;min-width:0}
body.dashboard-page .footer-stat b{display:block;font-size:14px;font-weight:650;line-height:1.1;color:var(--p-ink);font-variant-numeric:tabular-nums}
body.dashboard-page .footer-stat-strong b{font-size:16px}
body.dashboard-page .footer-label{font-size:10px;line-height:1.35;color:rgba(226,235,243,.58);letter-spacing:.08em;text-transform:uppercase}
body.dashboard-page .status-pill{height:25px;display:inline-flex;align-items:center;gap:7px;border:1px solid currentColor;background:color-mix(in srgb,currentColor 9%,transparent);border-radius:999px;padding:0 10px;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.085em;line-height:1;text-transform:uppercase;white-space:nowrap;box-shadow:inset 0 0 16px color-mix(in srgb,currentColor 7%,transparent)}
body.dashboard-page .status-pill i{width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.9;box-shadow:0 0 8px currentColor}
body.dashboard-page .status-pill.flash i,body.dashboard-page .status-pill.is-active i{animation:none;opacity:1;box-shadow:0 0 11px currentColor}
body.dashboard-page .status-pill-small{height:21px;padding:0 8px;font-size:9px;letter-spacing:.08em}
body.dashboard-page .status--producing{color:var(--produce-d)}
body.dashboard-page .status--charging,body.dashboard-page .status--discharging{color:var(--store-d)}
body.dashboard-page .status--exporting{color:var(--produce-d)}
body.dashboard-page .status--importing{color:var(--import-d)}
body.dashboard-page .status--live{color:var(--home-d)}
body.dashboard-page .status--warning{color:var(--store-d);background:rgba(255,194,71,.10);border-color:rgba(255,194,71,.45)}
body.dashboard-page .status--mismatch{color:var(--store-d);background:rgba(255,194,71,.12);border-color:rgba(255,194,71,.46)}
body.dashboard-page .status--standby{color:rgba(226,235,243,.56);background:rgba(226,235,243,.05);border-color:rgba(226,235,243,.20)}
body.dashboard-page .bar{height:10px;margin:0;background:rgba(7,16,25,.86);border:1px solid rgba(184,210,228,.18);border-radius:999px;box-shadow:inset 0 1px 4px rgba(0,0,0,.45)}
body.dashboard-page .bar .fill{border-radius:999px;box-shadow:0 0 14px currentColor}
body.dashboard-page .bar.center:after{background:rgba(244,247,250,.55)}
body.dashboard-page .scale{align-items:center}
body.dashboard-page .scale.three-up .scale-label:nth-child(2){text-align:center;color:rgba(244,247,250,.74)}
body.dashboard-page .scale-label{font-family:var(--mono);font-size:11px;line-height:1.45;color:rgba(226,235,243,.66)}
body.dashboard-page .sparkline{width:100%;height:58px;margin:0;opacity:.95}
body.dashboard-page .sparkline path{fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
body.dashboard-page .sparkline .spark-fill{fill:currentColor;opacity:.12;stroke:none}
body.dashboard-page .soc{display:grid;gap:6px}
body.dashboard-page .battery-pack-row{display:flex;align-items:center;gap:12px}
body.dashboard-page .battery-pack{display:flex;align-items:center;gap:5px;min-width:0;flex:1}
body.dashboard-page .battery-shell{position:relative;flex:1;min-width:0;border:1px solid rgba(184,210,228,.24);border-radius:7px;background:rgba(7,16,25,.82);padding:4px;box-shadow:inset 0 1px 5px rgba(0,0,0,.42)}
body.dashboard-page .battery-terminal{width:5px;height:18px;border:1px solid rgba(184,210,228,.24);border-left:0;border-radius:0 4px 4px 0;background:rgba(184,210,228,.14)}
body.dashboard-page .cells{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;margin:0;height:24px}
body.dashboard-page .cells i{height:100%;border-radius:3px;background:rgba(5,10,15,.9);border:1px solid rgba(184,210,228,.18)}
body.dashboard-page .cells i.on,body.dashboard-page .battery-pack.low .cells i.on,body.dashboard-page .battery-pack.high .cells i.on{background:var(--battery-cell-fill,linear-gradient(90deg,#E24B4A 0%,#E24B4A 10%,#EF9F27 10%,#EF9F27 20%,var(--produce-d) 20%,var(--produce-d) 100%));border-color:rgba(255,255,255,.34);box-shadow:0 0 8px rgba(70,198,132,.14)}
body.dashboard-page .battery-soc-text{min-width:42px;text-align:right;font-family:var(--mono);font-size:17px;font-weight:700;color:var(--p-ink);font-variant-numeric:tabular-nums}
body.dashboard-page .soc-limit{width:2px;top:2px;bottom:2px;z-index:2;box-shadow:0 0 10px currentColor}
body.dashboard-page .soc-limit-labels{height:14px;margin-top:0}
body.dashboard-page .soc-limit-label{font-family:var(--mono);font-size:10px;font-weight:600;line-height:1.2}
body.dashboard-page .thin{display:none}
body.dashboard-page .tile.produce .sparkline{color:var(--produce-d)}
body.dashboard-page .tile.import .sparkline{color:var(--import-d)}
body.dashboard-page .tile.produce #grid-spark{color:var(--produce-d)}
body.dashboard-page .tile.household .sparkline{color:var(--home-d)}
body.dashboard-page .chart-card{margin-top:18px;padding:20px}
body.dashboard-page .chart-top{align-items:flex-start;gap:18px;margin-bottom:8px}
body.dashboard-page .chart-legend{font-family:var(--mono);font-size:11px;line-height:1.4;gap:10px 14px}
body.dashboard-page .chart-legend button{display:inline-flex;align-items:center;gap:6px;padding:4px 5px;border-radius:6px}
body.dashboard-page .chart-legend button:hover,body.dashboard-page .chart-legend button:focus-visible{background:rgba(255,255,255,.06)}
body.dashboard-page .chart-legend button[aria-pressed="false"]{opacity:.34;text-decoration:none}
body.dashboard-page .chart-legend i{width:18px;height:2px;margin-right:0;border-radius:999px}
body.dashboard-page .chart-range{display:flex;gap:4px;align-items:center;margin-left:auto;border:1px solid rgba(184,210,228,.13);background:rgba(5,10,15,.52);border-radius:999px;padding:4px}
body.dashboard-page .chart-range button{border:0;background:transparent;color:var(--p-mut);border-radius:999px;padding:7px 12px;font:600 11px/1 var(--mono);cursor:pointer}
body.dashboard-page .chart-range button.active{background:rgba(244,247,250,.12);color:var(--p-ink)}
body.dashboard-page .chart-wrap{padding-top:2px}
body.dashboard-page .chart{height:322px}
body.dashboard-page .axis-label{fill:rgba(226,235,243,.72);font-family:var(--mono);font-size:10px}
body.dashboard-page .axis,body.dashboard-page .gridline{stroke:rgba(184,210,228,.11)}
body.dashboard-page .gridline-h{stroke:rgba(184,210,228,.17)}
body.dashboard-page .gridline-v{stroke:rgba(184,210,228,.065)}
body.dashboard-page .zero-line{stroke:rgba(244,247,250,.35);stroke-width:1.2}
body.dashboard-page .forecast-line{stroke:rgba(154,170,186,.78);stroke-width:1.7;stroke-dasharray:6 7}
body.dashboard-page .prod-line{stroke:var(--produce-d);stroke-width:2.2;opacity:.92}
body.dashboard-page .bat-line{stroke:var(--store-d);stroke-width:2;opacity:.92}
body.dashboard-page .grid-line{stroke:var(--import-d);stroke-width:2;opacity:.9}
body.dashboard-page .home-line{stroke:var(--home-d);stroke-width:2;opacity:.82}
body.dashboard-page .prod-fill{fill:rgba(76,219,131,.10)}
body.dashboard-page .bat-charge-fill,body.dashboard-page .bat-discharge-fill{fill:rgba(255,194,71,.09)}
body.dashboard-page .grid-import-fill{fill:rgba(255,99,92,.10)}
body.dashboard-page .grid-export-fill{fill:rgba(76,219,131,.08)}
body.dashboard-page .imp-fill{fill:rgba(255,99,92,.10)}
body.dashboard-page .exp-fill{fill:rgba(76,219,131,.08)}
body.dashboard-page .now{stroke:rgba(244,247,250,.84);stroke-width:1.25;stroke-dasharray:3 6}
body.dashboard-page .now-label-bg{fill:rgba(244,247,250,.12);stroke:rgba(244,247,250,.22);stroke-width:1}
body.dashboard-page .now-label{fill:var(--p-ink);font-family:var(--mono);font-size:9px;font-weight:700;letter-spacing:.08em}
body.dashboard-page .chart-tooltip{background:#071019;border-color:rgba(184,210,228,.22);border-radius:10px;box-shadow:0 16px 38px rgba(0,0,0,.42)}
body.dashboard-page .daystrip{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:0;margin-top:14px;padding-top:0;border:1px solid rgba(184,210,228,.12);border-radius:12px;overflow:hidden;background:rgba(8,17,26,.72)}
body.dashboard-page .kpi-tile{min-width:0;display:grid;align-content:center;gap:5px;min-height:62px;padding:12px 15px;border-right:1px solid rgba(184,210,228,.10)}
body.dashboard-page .kpi-tile:last-child{border-right:0}
body.dashboard-page .kpi-tile b{display:block;font-family:var(--mono);font-size:20px;font-weight:650;line-height:1;font-variant-numeric:tabular-nums}
body.dashboard-page .kpi-tile span{font-family:var(--mono);font-size:10px;line-height:1.35;color:rgba(226,235,243,.62);letter-spacing:.08em;text-transform:uppercase}
@media(max-width:1200px){body.dashboard-page .tile-grid{grid-template-columns:repeat(2,1fr)}body.dashboard-page .daystrip{grid-template-columns:repeat(4,1fr)}}
@media(max-width:860px){body.dashboard-page .dashboard-nav{padding:16px 14px 8px;align-items:flex-start;flex-direction:column}body.dashboard-page .brand-nav{justify-content:flex-start;gap:10px}body.dashboard-page .window-bar{justify-content:flex-start;padding:2px 14px 14px}body.dashboard-page .window-actions{justify-content:flex-start}body.dashboard-page .layout-toggle button,body.dashboard-page .segmented-control button{padding:7px 10px}body.dashboard-page .dash-head{margin-top:0;padding:0 14px 16px}body.dashboard-page .views{padding:0 14px 22px}body.dashboard-page .tile-grid{grid-template-columns:1fr}body.dashboard-page .metric-card{min-height:0}body.dashboard-page .chart{height:260px}body.dashboard-page .chart-top{display:grid}body.dashboard-page .chart-range{margin-left:0}body.dashboard-page .daystrip{grid-template-columns:repeat(2,1fr)}body.dashboard-page .metric-footer{align-items:start;flex-wrap:wrap}}
html[data-theme=light] body.dashboard-page{--panel:#EDF1F4;--panel-2:#FFFFFF;--panel-3:#E6EDF2;--p-ink:#15202A;--p-mut:rgba(74,98,118,.72);--p-line:rgba(74,98,118,.20);--home-d:#263441;--steel:#5F7588;background:radial-gradient(circle at 50% -12%,rgba(76,219,131,.14),transparent 34rem),linear-gradient(180deg,#F7FAFC 0,#EDF1F4 48%,#E5EBF0 100%);color:var(--p-ink)}
html[data-theme=light] body.dashboard-page .wordmark strong{color:var(--p-ink)}
html[data-theme=light] body.dashboard-page .brand-nav a{color:rgba(74,98,118,.66)}
html[data-theme=light] body.dashboard-page .brand-nav a:hover,html[data-theme=light] body.dashboard-page .brand-nav a:focus-visible{color:var(--ink)}
html[data-theme=light] body.dashboard-page .brand-nav a.active{color:var(--produce);border-bottom-color:var(--produce)}
html[data-theme=light] body.dashboard-page .mark{filter:drop-shadow(0 0 8px rgba(46,156,98,.18))}
html[data-theme=light] body.dashboard-page .mark line,html[data-theme=light] body.dashboard-page .mark circle{stroke:var(--produce)}
html[data-theme=light] body.dashboard-page .mark circle{fill:#EDF1F4}
html[data-theme=light] body.dashboard-page .layout-toggle,html[data-theme=light] body.dashboard-page .segmented-control,html[data-theme=light] body.dashboard-page .chart-range,html[data-theme=light] body.dashboard-page .mailbox-button{background:rgba(255,255,255,.72);border-color:rgba(74,98,118,.20);color:var(--ink)}
html[data-theme=light] body.dashboard-page .layout-toggle button,html[data-theme=light] body.dashboard-page .segmented-control button,html[data-theme=light] body.dashboard-page .chart-range button{color:rgba(74,98,118,.76)}
html[data-theme=light] body.dashboard-page .layout-toggle button.active,html[data-theme=light] body.dashboard-page .segmented-control button.active,html[data-theme=light] body.dashboard-page .chart-range button.active{background:#DDE6ED;color:#15202A}
html[data-theme=light] body.dashboard-page .dash-meta{color:rgba(74,98,118,.72)}
html[data-theme=light] body.dashboard-page .tile,html[data-theme=light] body.dashboard-page .chart-card,html[data-theme=light] body.dashboard-page .flow-node,html[data-theme=light] body.dashboard-page .mailbox-panel{background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(244,248,250,.94));border-color:rgba(74,98,118,.18);box-shadow:0 0 0 1px rgba(255,255,255,.72),0 18px 42px rgba(21,32,42,.10);backdrop-filter:blur(8px)}
html[data-theme=light] body.dashboard-page .tile.produce{box-shadow:0 0 0 1px rgba(255,255,255,.72),0 18px 42px rgba(21,32,42,.10),0 0 28px rgba(46,156,98,.08)}
html[data-theme=light] body.dashboard-page .tile.store{box-shadow:0 0 0 1px rgba(255,255,255,.72),0 18px 42px rgba(21,32,42,.10),0 0 28px rgba(216,155,42,.08)}
html[data-theme=light] body.dashboard-page .tile.battery-card{border-left-color:var(--battery-accent);box-shadow:0 0 0 1px rgba(255,255,255,.72),0 18px 42px rgba(21,32,42,.10),0 0 28px color-mix(in srgb,var(--battery-accent) 8%,transparent)}
html[data-theme=light] body.dashboard-page .tile.import{box-shadow:0 0 0 1px rgba(255,255,255,.72),0 18px 42px rgba(21,32,42,.10),0 0 28px rgba(206,73,64,.08)}
html[data-theme=light] body.dashboard-page .tile-name{color:rgba(74,98,118,.86)}
html[data-theme=light] body.dashboard-page .metric-subtitle,html[data-theme=light] body.dashboard-page .scale-label,html[data-theme=light] body.dashboard-page .footer-label,html[data-theme=light] body.dashboard-page .kpi-tile span{color:rgba(74,98,118,.76)}
html[data-theme=light] body.dashboard-page .metric-footer{border-top-color:rgba(74,98,118,.12)}
html[data-theme=light] body.dashboard-page .footer-stat b{color:var(--p-ink)}
html[data-theme=light] body.dashboard-page .status--standby{color:rgba(74,98,118,.70);background:rgba(74,98,118,.06);border-color:rgba(74,98,118,.24)}
html[data-theme=light] body.dashboard-page .bar,html[data-theme=light] body.dashboard-page .battery-shell,html[data-theme=light] body.dashboard-page .cells i{background:#EEF3F6;border-color:rgba(74,98,118,.18);box-shadow:inset 0 1px 3px rgba(21,32,42,.08)}
html[data-theme=light] body.dashboard-page .cells i.on,html[data-theme=light] body.dashboard-page .battery-pack.low .cells i.on,html[data-theme=light] body.dashboard-page .battery-pack.high .cells i.on{background:var(--battery-cell-fill,linear-gradient(90deg,#E24B4A 0%,#E24B4A 10%,#EF9F27 10%,#EF9F27 20%,var(--produce-d) 20%,var(--produce-d) 100%));border-color:rgba(74,98,118,.22);box-shadow:0 0 10px rgba(74,98,118,.08)}
html[data-theme=light] body.dashboard-page .battery-terminal{background:#DDE6ED;border-color:rgba(74,98,118,.20)}
html[data-theme=light] body.dashboard-page .daystrip{background:rgba(255,255,255,.86);border-color:rgba(74,98,118,.16)}
html[data-theme=light] body.dashboard-page .kpi-tile{border-right-color:rgba(74,98,118,.12)}
html[data-theme=light] body.dashboard-page .axis-label{fill:rgba(74,98,118,.82)}
html[data-theme=light] body.dashboard-page .gridline-h{stroke:rgba(74,98,118,.16)}
html[data-theme=light] body.dashboard-page .gridline-v{stroke:rgba(74,98,118,.07)}
html[data-theme=light] body.dashboard-page .zero-line{stroke:rgba(21,32,42,.30)}
html[data-theme=light] body.dashboard-page .now{stroke:rgba(21,32,42,.64)}
html[data-theme=light] body.dashboard-page .now-label-bg{fill:rgba(255,255,255,.88);stroke:rgba(74,98,118,.22)}
html[data-theme=light] body.dashboard-page .now-label{fill:#15202A}
html[data-theme=light] body.dashboard-page .forecast-line{stroke:rgba(95,117,136,.78)}
html[data-theme=light] body.dashboard-page .home-line{stroke:var(--home-d)}
html[data-theme=light] body.dashboard-page .chart-tooltip{background:#FFFFFF;border-color:rgba(74,98,118,.20);color:var(--p-ink);box-shadow:0 16px 38px rgba(21,32,42,.16)}
html[data-theme=light] body.dashboard-page .chart-tooltip span{color:rgba(74,98,118,.76)}
"""
