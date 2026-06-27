"""Minyad web frontend."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

app = FastAPI(title="Minyad Frontend")
API_BASE_URL = os.getenv("API_BASE_URL", "http://minyad-api:8000")
MINYAD_API_SECRET = os.getenv("MINYAD_API_SECRET", "")

MENU = ["Dashboard", "Agent", "Health", "History", "Trade", "Solar", "Battery", "DSMR", "Asset Steering", "Reporting", "Settings"]

BRAND_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root{--paper:#EDF1F4;--paper-2:#E2E8ED;--ink:#15202A;--steel:#4A6276;--hair:rgba(21,32,42,.09);--panel:#0E151C;--panel-2:#15202B;--panel-3:#1D2A37;--p-ink:#E6EDF2;--p-mut:rgba(230,237,242,.55);--p-line:rgba(150,182,208,.13);--produce:#2E9C62;--store:#D89B2A;--import:#CE4940;--produce-d:#46C684;--store-d:#F0B441;--import-d:#F26A60;--home-d:#E6EDF2;--mono:"IBM Plex Mono",ui-monospace,monospace;--sans:"Space Grotesk",ui-sans-serif,system-ui,sans-serif;--ease:cubic-bezier(.2,.7,.3,1)}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:var(--sans);letter-spacing:-.01em}a{color:inherit}.brand-shell{min-height:100vh;padding:38px clamp(16px,6vw,64px) 56px}.brand-header{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:36px}.brand-lockup{display:flex;align-items:center;gap:14px;text-decoration:none}.mark{width:30px;height:30px;overflow:visible}.mark line{stroke:var(--steel);stroke-width:1.5;stroke-linecap:round}.mark circle{fill:var(--paper);stroke:var(--steel);stroke-width:1.5}.wordmark{display:grid;gap:4px}.wordmark strong{font-size:24px;line-height:1;font-weight:700;letter-spacing:-.04em}.wordmark span,.brand-nav a,.label,.kicker,.status-pill,.scale-label,.tile-name,.window-tab,.chart-legend,.unit,.value{font-family:var(--mono);font-feature-settings:"tnum";font-variant-numeric:tabular-nums}.wordmark span{font-size:9px;color:var(--steel);letter-spacing:.32em;text-transform:uppercase}.brand-nav{display:flex;gap:18px;flex-wrap:wrap}.brand-nav a{text-decoration:none;color:var(--steel);font-size:11px;letter-spacing:.18em;text-transform:uppercase}.brand-nav a.active{color:var(--ink)}.brand-main{max-width:1180px;margin:auto}.card{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}.kicker{display:flex;align-items:center;gap:16px;color:var(--steel);font-size:11px;letter-spacing:.34em;text-transform:uppercase}.kicker:after{content:"";height:1px;width:86px;background:rgba(74,98,118,.22)}.page-title{font-size:clamp(42px,7vw,72px);line-height:.95;margin:22px 0 22px;letter-spacing:-.065em}.page-copy{max-width:800px;color:rgba(21,32,42,.68);font-size:20px;line-height:1.55}.instrument{background:var(--panel);color:var(--p-ink);border:1px solid rgba(150,182,208,.18);border-radius:18px;box-shadow:0 26px 70px rgba(14,21,28,.18);overflow:hidden}.dashboard-page{margin:0;min-height:100vh;background:var(--panel)}.dashboard-full{min-height:100vh;border:0;border-radius:0;box-shadow:none}.dashboard-nav{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 24px;border-bottom:1px solid var(--p-line);background:var(--panel)}.dashboard-nav .brand-nav a{color:var(--p-mut)}.dashboard-nav .brand-nav a.active{color:var(--p-ink)}.dashboard-nav .wordmark strong{color:var(--p-ink)}.dashboard-nav .wordmark span{color:var(--p-mut)}.dashboard-nav .mark circle{fill:var(--panel)}.dashboard-full .views{padding-bottom:32px}.dashboard-full .flow-board{height:calc(100vh - 220px);min-height:560px}.window-bar{height:62px;border-bottom:1px solid var(--p-line);display:flex;align-items:center;justify-content:space-between;padding:0 20px}.traffic{display:flex;gap:10px}.traffic i{width:10px;height:10px;border-radius:50%;background:#304455}.traffic i:nth-child(1){background:var(--import-d)}.traffic i:nth-child(2){background:var(--store-d)}.traffic i:nth-child(3){background:var(--produce-d)}.window-tab{background:#0A1016;border:1px solid var(--p-line);border-radius:7px;color:var(--p-mut);font-size:11px;letter-spacing:.08em;padding:9px 14px}.layout-toggle{display:flex;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;padding:4px}.layout-toggle button{margin:0;border:0;background:transparent;color:var(--p-mut);font:600 11px/1 var(--mono);letter-spacing:.1em;padding:9px 13px;border-radius:6px;cursor:pointer}.layout-toggle button.active{background:var(--panel-3);color:var(--p-ink)}.window-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;margin-left:auto}.dash-head{display:flex;justify-content:flex-end;gap:18px;align-items:start;padding:28px 28px 10px}.dash-title{display:flex;gap:14px;align-items:center}.dash-title .mark circle{fill:var(--panel)}.dash-title strong{font-size:22px}.dash-meta{text-align:right;color:var(--p-mut);font-family:var(--mono);font-size:13px;line-height:1.7;font-feature-settings:"tnum"}.self{color:var(--produce-d)}.views{position:relative;padding:0 26px 28px}.view{display:none;animation:fade .24s var(--ease)}.view.active{display:block}@keyframes fade{from{opacity:.25}to{opacity:1}}.tile-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.tile{background:var(--panel-2);border:1px solid var(--p-line);border-left:3px solid var(--steel);border-radius:11px;padding:18px;min-width:0}.tile.produce{border-left-color:var(--produce-d)}.tile.store{border-left-color:var(--store-d)}.tile.import{border-left-color:var(--import-d)}.tile.household{border-left-color:var(--p-ink)}.tile-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.tile-name{font-size:12px;text-transform:uppercase;letter-spacing:.16em;color:var(--p-mut);display:flex;align-items:center;gap:8px}.icon{width:22px;height:22px;fill:none;stroke:var(--steel);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.phrase{font-family:var(--mono);font-feature-settings:"tnum";font-size:clamp(34px,5vw,54px);line-height:1;color:var(--p-ink);letter-spacing:-.04em;transition:color .24s var(--ease)}.phrase .unit{font-size:.55em;color:currentColor;letter-spacing:0}.produce-c{color:var(--produce-d)}.store-c{color:var(--store-d)}.import-c{color:var(--import-d)}.household-c{color:var(--home-d)}.steel-c{color:var(--p-mut)}.bar{position:relative;height:8px;margin:20px 0 8px;border:1px solid var(--p-line);border-radius:999px;background:#0A1016;overflow:hidden}.bar .fill{position:absolute;top:0;bottom:0;width:0;background:var(--steel);transition:width .24s var(--ease),left .24s var(--ease),right .24s var(--ease)}.bar.center:after{content:"";position:absolute;left:50%;top:-5px;bottom:-5px;width:1px;background:rgba(230,237,242,.38)}.scale{display:flex;justify-content:space-between;gap:8px}.scale-label{font-size:10px;color:var(--p-mut);white-space:nowrap}.status-pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--p-line);border-radius:999px;padding:6px 9px;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--p-mut)}.status-pill i{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 0 rgba(230,237,242,0);transition:background .24s var(--ease),box-shadow .24s var(--ease),opacity .24s var(--ease)}.status-pill.flash i{animation:pill-flash 1s ease-in-out infinite;box-shadow:0 0 14px currentColor}.status-pill:not(.flash) i{opacity:.55}@keyframes pill-flash{0%,100%{opacity:1;transform:scale(1);box-shadow:0 0 7px currentColor}50%{opacity:.45;transform:scale(1.45);box-shadow:0 0 18px currentColor}}.soc{margin-top:18px}.soc-gauge{position:relative}.cells{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;margin:8px 0}.cells i{height:18px;border:1px solid var(--p-line);border-radius:3px;background:#0A1016}.cells i.on{background:var(--store-d);border-color:rgba(240,180,65,.5)}.soc-limit{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--p-ink);box-shadow:0 0 0 1px #0A1016;transform:translateX(-1px);opacity:.9}.soc-limit.max{background:var(--produce-d)}.soc-limit.min{background:var(--import-d)}.soc-limit-labels{position:relative;height:16px;margin-top:2px}.soc-limit-label{position:absolute;top:0;transform:translateX(-50%);font-family:var(--mono);font-size:9px;line-height:1;color:var(--p-mut);white-space:nowrap}.soc-limit-label.min{color:var(--import-d)}.soc-limit-label.max{color:var(--produce-d)}.thin{height:5px;background:#0A1016;border:1px solid var(--p-line);border-radius:999px;overflow:hidden}.thin i{display:block;height:100%;background:var(--produce-d)}.chart-card{margin-top:14px;background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:18px}.chart-top,.daystrip{display:flex;justify-content:space-between;gap:16px;align-items:center}.chart-legend{display:flex;gap:10px;flex-wrap:wrap;color:var(--p-mut);font-size:11px}.chart-legend button{border:0;background:transparent;color:inherit;padding:4px 6px;border-radius:6px;cursor:pointer;font:inherit;opacity:1}.chart-legend button:hover,.chart-legend button:focus-visible{background:var(--panel-3);outline:none}.chart-legend button[aria-pressed="false"]{opacity:.38;text-decoration:line-through}.chart-legend i{display:inline-block;width:18px;height:2px;margin-right:5px;vertical-align:middle;background:currentColor}.chart-wrap{position:relative}.chart{width:100%;height:300px;margin-top:10px}.chart-tooltip{position:absolute;z-index:5;min-width:190px;pointer-events:none;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;color:var(--p-ink);padding:10px 12px;box-shadow:0 16px 40px rgba(0,0,0,.35);font-family:var(--mono);font-size:11px;line-height:1.45;transform:translate(-50%,calc(-100% - 12px))}.chart-tooltip[hidden]{display:none}.chart-tooltip b{display:block;margin-bottom:4px;font-size:12px}.chart-tooltip span{display:block;color:var(--p-mut)}.chart-hover{fill:transparent;pointer-events:stroke;stroke:transparent;stroke-width:16}.chart-marker{stroke:var(--p-ink);stroke-width:1;stroke-dasharray:2 4}.chart-dot{stroke:#0A1016;stroke-width:2}.sparkline{width:100%;height:54px;margin-top:12px}.sparkline path{fill:none;stroke:var(--p-ink);stroke-width:2}.load-meta{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.badge.warn{border-color:rgba(240,180,65,.5);color:var(--store-d)}.axis,.gridline{stroke:var(--p-line);stroke-width:1}.zero-line{stroke:rgba(230,237,242,.38);stroke-width:1.4}.forecast-fill{fill:rgba(74,98,118,.18)}.forecast-line{fill:none;stroke:rgba(150,182,208,.48);stroke-width:2;stroke-dasharray:6 6}.prod-line{fill:none;stroke:var(--produce-d);stroke-width:2.6}.prod-fill{fill:rgba(70,198,132,.12)}.bat-line{fill:none;stroke:var(--store-d);stroke-width:2}.bat-charge-fill{fill:rgba(240,180,65,.14)}.bat-discharge-fill{fill:rgba(216,155,42,.18)}.grid-line{fill:none;stroke:var(--import-d);stroke-width:2}.home-line{fill:none;stroke:var(--p-mut);stroke-width:2.4}.grid-import-fill{fill:rgba(242,106,96,.16)}.grid-export-fill{fill:rgba(70,198,132,.14)}.imp-fill{fill:rgba(242,106,96,.16)}.exp-fill{fill:rgba(70,198,132,.14)}.now{stroke:var(--p-ink);stroke-width:1;stroke-dasharray:3 5}.daystrip{margin-top:14px;border-top:1px solid var(--p-line);padding-top:14px}.daystrip div{min-width:0}.daystrip b{display:block;font-family:var(--mono);font-feature-settings:"tnum";font-size:22px}.daystrip span{font-family:var(--mono);font-size:10px;color:var(--p-mut);letter-spacing:.1em;text-transform:uppercase}.flow-board{height:560px;position:relative;background:radial-gradient(circle at 50% 43%,rgba(29,42,55,.8),transparent 34%);border:1px solid var(--p-line);border-radius:12px;margin-top:14px}.flow-svg{position:absolute;inset:0;width:100%;height:100%}.flow-line{fill:none;stroke-width:4;stroke-linecap:round;opacity:.8}.flow-dot{animation:drift 2s linear infinite}@keyframes drift{to{offset-distance:100%}}.flow-node{position:absolute;transform:translate(-50%,-50%);background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:14px;width:170px;text-align:center}.flow-node.solar{left:50%;top:18%}.flow-node.home{left:50%;top:48%;border-color:rgba(230,237,242,.3)}.flow-node.battery{left:25%;top:78%}.flow-node.grid{left:75%;top:78%}.flow-node .phrase{font-size:26px}.mobile-readout{display:none}.mobile-rows{display:grid;gap:10px}.mobile-row{display:flex;justify-content:space-between;border-top:1px solid var(--p-line);padding-top:10px}.status-card,.overview-card,.panel,.flow-panel{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}input{width:100%;margin-top:8px;border:1px solid rgba(74,98,118,.25);background:#fff;padding:11px 12px;font:inherit;color:var(--ink)}button{font-family:var(--mono)}pre{background:#111827;color:#eef2f7;padding:16px;overflow:auto}.grid:not(.flow-node),.metric-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--hair);border:1px solid var(--hair)}.grid:not(.flow-node)>*{background:var(--paper);padding:14px}.error{color:var(--import)}@media(max-width:1100px){.tile-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.dashboard-nav{align-items:flex-start;flex-direction:column;padding:14px}.brand-shell{padding:18px 12px}.brand-header{align-items:flex-start;flex-direction:column}.instrument{border-radius:14px}.dash-head,.window-bar{padding-left:14px;padding-right:14px}.tile-grid{grid-template-columns:1fr}.chart{height:220px}.daystrip{display:grid;grid-template-columns:repeat(2,1fr)}.desktop-only{display:none}.mobile-readout{display:block;padding:0 14px 18px}.flow-board{height:520px}.dashboard-full .flow-board{height:520px;min-height:520px}.flow-node{width:140px}.flow-node.battery{left:22%}.flow-node.grid{left:78%}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;transition-duration:.001ms!important;scroll-behavior:auto!important}.flow-dot{display:none}.status-pill.flash i{animation:none}}

.history-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.history-tab{border:1px solid rgba(74,98,118,.25);background:#fff;color:var(--steel);border-radius:999px;padding:10px 14px;cursor:pointer;font:700 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase}.history-tab.active{background:var(--panel);color:var(--p-ink);border-color:var(--panel)}.history-panel{display:none}.history-panel.active{display:block}.history-toolbar{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.history-hint{color:rgba(21,32,42,.62);font-family:var(--mono);font-size:11px}.history-chart-card{background:#fff;border:1px solid rgba(74,98,118,.18);border-radius:14px;padding:18px;margin-top:12px}.history-chart{width:100%;height:420px;touch-action:none}.history-mini{width:100%;height:78px;margin-top:10px;cursor:crosshair}.history-window{fill:rgba(74,98,118,.16);stroke:rgba(74,98,118,.55);stroke-width:1.5}.history-brush{fill:rgba(46,156,98,.18);stroke:var(--produce);stroke-width:1.5}.history-tooltip{position:absolute;z-index:6;min-width:210px;pointer-events:none;background:#fff;border:1px solid rgba(74,98,118,.22);border-radius:10px;color:var(--ink);padding:10px 12px;box-shadow:0 16px 40px rgba(14,21,28,.16);font-family:var(--mono);font-size:11px;line-height:1.45;transform:translate(-50%,calc(-100% - 10px))}.history-tooltip[hidden]{display:none}.history-empty{padding:28px;text-align:center;color:var(--steel);font-family:var(--mono);border:1px dashed rgba(74,98,118,.28);border-radius:12px}.history-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.history-stat{background:rgba(237,241,244,.86);border:1px solid rgba(74,98,118,.16);border-radius:10px;padding:12px}.history-stat b{display:block;font-family:var(--mono);font-size:22px}.history-stat span{color:var(--steel);font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.1em}@media(max-width:860px){.history-chart{height:300px}.history-stats{grid-template-columns:repeat(2,1fr)}}

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
html[data-theme=dark] .history-tab,html[data-theme=dark] .history-chart-card,html[data-theme=dark] .history-tooltip{background:#101b24;color:var(--ink);border-color:rgba(184,210,228,.14)}
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
"""

def brand_mark() -> str:
    return """
    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true">
      <line x1="16" y1="7" x2="7" y2="24"></line><line x1="16" y1="7" x2="25" y2="24"></line><line x1="7" y1="24" x2="25" y2="24"></line>
      <circle cx="16" cy="7" r="2.4"></circle><circle cx="7" cy="24" r="2.4"></circle><circle cx="25" cy="24" r="2.4"></circle>
    </svg>
    """


def menu_href(item: str) -> str:
    if item == "Dashboard":
        return "/"
    return "/" + item.lower().replace(" ", "-")


def render_nav(active: str) -> str:
    return "".join(
        f"<a class='{ 'active' if item == active else '' }' href='{menu_href(item)}'>{item}</a>"
        for item in MENU
    )


def render_page(active: str, body: str) -> str:
    links = render_nav(active)
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Minyad — {active}</title>
        <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%230E151C'/%3E%3Ctext x='16' y='22' text-anchor='middle' font-family='Arial,sans-serif' font-size='20' font-weight='700' fill='%23E6EDF2'%3EM%3C/text%3E%3C/svg%3E">
        <style>{BRAND_CSS}</style>
        {THEME_BOOT_SCRIPT}
      </head>
      <body>
        <div class="brand-shell">
          <header class="brand-header">
            <a class="brand-lockup" href="/" aria-label="Minyad dashboard">
              {brand_mark()}
              <span class="wordmark"><strong>Minyad</strong><span>Virtual Power Plant</span></span>
            </a>
            <nav class="brand-nav" aria-label="Primary navigation">{links}</nav>
          </header>
          <main class="brand-main">{body}</main>
        </div>
      </body>
    </html>
    """


def render_dashboard_page() -> str:
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Minyad — Dashboard</title>
        <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%230E151C'/%3E%3Ctext x='16' y='22' text-anchor='middle' font-family='Arial,sans-serif' font-size='20' font-weight='700' fill='%23E6EDF2'%3EM%3C/text%3E%3C/svg%3E">
        <style>{BRAND_CSS}</style>
        {THEME_BOOT_SCRIPT}
      </head>
      <body class="dashboard-page">
        {energy_dashboard_body()}
      </body>
    </html>
    """


def agent_body() -> str:
    return """
    <div class='card'>
      <div class='agent-hero'>
        <div class='agent-stat'><span class='agent-meta'>Last decision</span><b id='agent-last-action'>--</b></div>
        <div class='agent-stat'><span class='agent-meta'>Setpoint</span><b id='agent-last-setpoint'>--</b></div>
        <div class='agent-stat'><span class='agent-meta'>Confidence</span><b id='agent-last-confidence'>--</b></div>
        <div class='agent-stat'><span class='agent-meta'>Unread messages</span><b id='agent-unread'>--</b></div>
      </div>
      <div class='agent-controls'>
        <button type='button' class='active' data-limit='25'>Latest 25</button>
        <button type='button' data-limit='50'>Latest 50</button>
        <button type='button' data-limit='100'>Latest 100</button>
        <button type='button' onclick='loadAgentDashboard()'>Refresh</button>
      </div>
    </div>
    <div class='agent-layout' style='margin-top:16px'>
      <section class='panel'>
        <div id='agent-decisions' class='agent-list'><div class='agent-empty'>Loading decisions…</div></div>
      </section>
      <aside class='panel'>
        <button type='button' id='agent-compose-toggle' class='agent-compose-toggle' aria-expanded='false' aria-controls='agent-compose-panel'>Send a message to the agent</button>
        <div id='agent-compose-panel' class='agent-compose-panel' hidden>
          <form id='agent-compose' class='agent-compose'>
            <input id='agent-compose-subject' maxlength='160' placeholder='Subject' required>
            <textarea id='agent-compose-body' placeholder='Message or task for the agent…' required></textarea>
            <button type='submit'>Send to agent</button>
            <span id='agent-compose-status' class='agent-meta'></span>
          </form>
        </div>
        <div id='agent-messages' class='agent-list'><div class='agent-empty'>Loading messages…</div></div>
      </aside>
    </div>
    <script>
      let agentLimit=25;
      const agentEl=id=>document.getElementById(id);
      const agentEsc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const fmtTime=value=>value?new Date(value).toLocaleString():'--';
      const fmtSetpoint=value=>value===null||value===undefined?'hold':`${Number(value).toLocaleString()} W`;
      function snapshotPreview(snapshot){try{return JSON.stringify(snapshot,null,2)}catch(e){return '{}'}}
      function renderDecisions(items){
        const wrap=agentEl('agent-decisions');
        if(!items.length){wrap.innerHTML='<div class="agent-empty">No agent decisions recorded yet.</div>';return;}
        const latest=items[0];
        agentEl('agent-last-action').textContent=latest.action_taken;
        agentEl('agent-last-setpoint').textContent=fmtSetpoint(latest.setpoint_w);
        agentEl('agent-last-confidence').textContent=latest.confidence;
        wrap.innerHTML=items.map(d=>`<article class="agent-decision ${agentEsc(d.action_taken)}"><header><strong>${agentEsc(d.action_taken)} · ${fmtSetpoint(d.setpoint_w)}</strong><span class="agent-meta">${fmtTime(d.created_at)}</span></header><div class="agent-meta">${agentEsc(d.confidence)} confidence · ${d.dry_run?'dry run':'live'} · ${agentEsc(d.model)}</div><p class="agent-reason">${agentEsc(d.reasoning)}</p><details><summary class="agent-meta">Input snapshot</summary><pre class="agent-snapshot">${agentEsc(snapshotPreview(d.input_snapshot))}</pre></details></article>`).join('');
      }
      function renderMessages(items){
        const wrap=agentEl('agent-messages');
        if(!items.length){wrap.innerHTML='<div class="agent-empty">No recent agent messages.</div>';return;}
        wrap.innerHTML=items.map(m=>`<article class="agent-message-card"><header><strong>${agentEsc(m.subject)}</strong><span class="agent-meta">${fmtTime(m.created_at)}</span></header><div class="agent-meta">${agentEsc(m.category)} · ${agentEsc(m.severity)} · ${m.read_at?'read':'unread'}</div><p class="agent-reason">${agentEsc(m.body)}</p></article>`).join('');
      }
      async function loadAgentDashboard(){
        try{
          const [decisionsRes,messagesRes,unreadRes]=await Promise.all([fetch(`/api/agent/decisions?limit=${agentLimit}`),fetch('/api/messages?limit=10'),fetch('/api/messages/unread-count')]);
          renderDecisions(decisionsRes.ok?await decisionsRes.json():[]);
          renderMessages(messagesRes.ok?await messagesRes.json():[]);
          const unread=unreadRes.ok?await unreadRes.json():{unread_count:0}; agentEl('agent-unread').textContent=String(unread.unread_count||0);
        }catch(err){agentEl('agent-decisions').innerHTML=`<div class='agent-empty error'>${agentEsc(err.message||'Unable to load agent activity')}</div>`;}
      }
      document.querySelectorAll('[data-limit]').forEach(btn=>btn.addEventListener('click',()=>{agentLimit=Number(btn.dataset.limit);document.querySelectorAll('[data-limit]').forEach(b=>b.classList.toggle('active',b===btn));loadAgentDashboard();}));
      agentEl('agent-compose-toggle').addEventListener('click',()=>{const toggle=agentEl('agent-compose-toggle');const panel=agentEl('agent-compose-panel');const expanded=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!expanded));panel.hidden=expanded;if(expanded){toggle.focus();}else{agentEl('agent-compose-subject').focus();}});
      agentEl('agent-compose').addEventListener('submit',async event=>{event.preventDefault();const subject=agentEl('agent-compose-subject').value.trim();const body=agentEl('agent-compose-body').value.trim();const status=agentEl('agent-compose-status');if(!subject||!body)return;status.textContent='Sending…';try{const res=await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender:'operator',category:'info',subject,body,severity:'normal'})});if(!res.ok)throw new Error('Unable to send message');agentEl('agent-compose-subject').value='';agentEl('agent-compose-body').value='';status.textContent='Sent. The agent will pick it up in the next cycle.';loadAgentDashboard();}catch(err){status.textContent=err.message||'Unable to send message';}});
      loadAgentDashboard(); setInterval(loadAgentDashboard,15000);
    </script>
    """

def asset_steering_body() -> str:
    return """
    <div class='card'>
      <h2>Asset steering</h2>
      <p>Manage the strategy thresholds that steer battery charging and discharging. Values are stored as <code>strategy.*</code> settings and consumed by the strategy/control services.</p>
      <form id='asset-steering-settings' class='grid'>
        <label>Solar-rich GHI threshold <input name='ghi_solar_rich_threshold' type='number' min='0' max='20' step='0.1'></label>
        <label>Solar-poor GHI threshold <input name='ghi_solar_poor_threshold' type='number' min='0' max='20' step='0.1'></label>
        <label>Dynamic tariff ceiling EUR/kWh <input name='dynamic_tariff_ceiling_eur_kwh' type='number' min='-1' max='5' step='0.001'></label>
        <label>Daily recalculation time <input name='daily_recalculate_local_time' type='time'></label>
        <label>Battery ramp floor W <input name='ramp_floor_w' type='number' min='0' max='5000' step='1'></label>
        <label>Battery ramp ceiling W <input name='ramp_ceiling_w' type='number' min='1' max='5000' step='1'></label>
        <label>Battery ramp hold seconds <input name='ramp_hold_seconds' type='number' min='0' max='3600' step='1'></label>
        <button type='submit'>Save asset steering</button>
      </form>
      <pre id='asset-steering-result'></pre>
    </div>
    <div class='card'>
      <h2>Recent steering activity</h2>
      <button class='secondary' onclick='loadAssetSteeringStatus()'>Refresh activity</button>
      <div class='grid' style='margin-top:12px'>
        <p>Latest decision: <strong id='latest-decision'>--</strong></p>
        <p>Latest setpoint: <strong id='latest-setpoint'>--</strong></p>
      </div>
      <pre id='asset-steering-status'>Loading...</pre>
    </div>
    <script>
      async function loadAssetSteeringSettings(){
        const res = await fetch('/api/asset-steering/settings');
        const data = await res.json();
        for (const [k,v] of Object.entries(data)){ const el = document.querySelector(`[name="${k}"]`); if(el) el.value = v; }
        document.getElementById('asset-steering-result').textContent = JSON.stringify(data, null, 2);
      }
      document.getElementById('asset-steering-settings').addEventListener('submit', async (event)=>{
        event.preventDefault(); const data = {};
        new FormData(event.target).forEach((v,k)=>{ data[k] = k === 'daily_recalculate_local_time' ? v : Number(v); });
        const res = await fetch('/api/asset-steering/settings',{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        document.getElementById('asset-steering-result').textContent = JSON.stringify(await res.json(), null, 2);
        loadAssetSteeringStatus();
      });
      async function loadAssetSteeringStatus(){
        const res = await fetch('/api/asset-steering/status');
        const data = await res.json();
        const decision = data.latest_decision;
        const setpoint = data.latest_setpoint;
        document.getElementById('latest-decision').textContent = decision ? `${decision.mode} · ${decision.trigger_reason}` : '--';
        document.getElementById('latest-setpoint').textContent = setpoint ? `${setpoint.source} · ${setpoint.charge_rate_w ?? 0}W · discharge ${setpoint.discharge_allowed ? 'allowed' : 'blocked'}` : '--';
        document.getElementById('asset-steering-status').textContent = JSON.stringify(data, null, 2);
      }
      loadAssetSteeringSettings(); loadAssetSteeringStatus(); setInterval(loadAssetSteeringStatus, 15000);
    </script>
    """



def solar_body() -> str:
    return """
    <section class='solar-hero'>
      <div class='card'>
        <span class='kicker'>Solar</span>
        <h1 class='page-title'>Micro-inverter overview</h1>
        <p class='page-copy'>Live Enphase micro-inverter production. Each panel is represented by its micro-inverter and shows the currently reported wattage.</p>
        <div class='solar-meta'>
          <span class='status-pill produce-c' id='solar-bridge-pill'><i></i><span id='solar-bridge'>Loading</span></span>
          <span class='scale-label'>Updated <span id='solar-updated'>--</span></span>
        </div>
      </div>
      <aside class='card solar-total' aria-label='Total current solar production'>
        <span class='tile-name'>Total now</span>
        <div class='phrase produce-c'><span id='solar-total-kw'>--</span> <span class='unit'>kW</span></div>
        <div>
          <div class='bar'><span id='solar-total-bar' class='fill' style='background:var(--produce-d)'></span></div>
          <div class='scale'><span class='scale-label'>0 W</span><span class='scale-label' id='solar-total-scale'>peak</span></div>
        </div>
      </aside>
    </section>
    <section class='solar-overview'>
      <div class='chart-top'><span class='tile-name'>Panels / micro-inverters</span><span class='scale-label'><span id='inverter-count'>0</span> reporting</span></div>
      <div id='array-list' class='array-list'></div>
      <div id='inverter-grid' class='solar-grid'><div class='solar-empty'>Loading inverter telemetry…</div></div>
      <p id='solar-error' class='error' role='alert'></p>
    </section>
    <script>
      const $=id=>document.getElementById(id);
      const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const num=v=>{const x=Number(v);return Number.isFinite(x)?x:null};
      function age(iso){if(!iso)return '--'; const d=new Date(iso); if(Number.isNaN(d.getTime()))return iso; const s=Math.max(0,Math.round((Date.now()-d.getTime())/1000)); return s<90?s+'s ago':d.toLocaleString();}
      function setPill(active){const pill=$('solar-bridge-pill'); pill.className='status-pill '+(active?'produce-c flash':'steel-c');}
      async function loadSolar(){
        try{
          const res=await fetch('/api/solar/status'); if(!res.ok)throw new Error('Solar status request failed ('+res.status+')');
          const data=await res.json(); const inverters=data.inverters||[]; const total=num(data.power_w)??inverters.reduce((a,i)=>a+(num(i.power_w)||0),0); const peak=Math.max(300, ...inverters.map(i=>num(i.power_w)||0), Math.ceil(total/1000)*1000);
          $('solar-total-kw').textContent=(total/1000).toFixed(2); $('solar-total-bar').style.width=Math.min(100,total/Math.max(1,peak)*100)+'%'; $('solar-total-scale').textContent='~'+peak+' W scale';
          $('solar-bridge').textContent=data.bridge_status||'unknown'; $('solar-updated').textContent=age(data.updated_at||data.bridge_last_seen); setPill((data.bridge_status||'').toLowerCase()==='online'); $('inverter-count').textContent=inverters.length;
          const arrays=Object.entries(data.arrays||{}); $('array-list').innerHTML=arrays.map(([name,w])=>`<span class='array-pill'>${esc(name)} · ${esc(w)} W</span>`).join('');
          $('inverter-grid').innerHTML=inverters.length?inverters.map(inv=>{const w=num(inv.power_w)||0; const pct=Math.min(100,w/Math.max(1,peak)*100); return `<article class='inverter-card'><span class='tile-name'>Inverter</span><b>${esc(inv.serial)}</b><div class='phrase produce-c' style='font-size:34px'>${Math.round(w)} <span class='unit'>W</span></div><div class='bar'><span class='fill' style='background:var(--produce-d);width:${pct}%'></span></div><div class='scale'><span class='scale-label'>current</span><span class='scale-label'>${esc(age(inv.last_report_at))}</span></div></article>`}).join(''):`<div class='solar-empty'>No micro-inverter telemetry received yet. Waiting for retained MQTT topics under minyad/solar/inverter/+/.</div>`;
          $('solar-error').textContent='';
        }catch(e){$('solar-error').textContent=e.message||'Unable to load solar status';}
      }
      loadSolar(); setInterval(loadSolar, 10000);
    </script>
    """

def health_body() -> str:
    return """
    <section class='card'>
      <div style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'>
        <span class='status-pill' id='overall-pill'><i></i><span id='overall-status'>Loading</span></span>
        <span class='scale-label'>Last checked <span id='health-checked'>--</span></span>
        <button class='secondary' onclick='loadHealth()'>Refresh now</button>
      </div>
    </section>
    <section class='health-grid' id='health-grid' style='display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:18px'></section>
    <section class='card' style='margin-top:18px'>
      <h2>Raw health payload</h2>
      <pre id='health-raw'>Loading...</pre>
    </section>
    <script>
      const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const statusClass=s=>s==='ok'?'produce-c flash':(s==='error'?'import-c flash':'store-c flash');
      function setOverall(status){const pill=document.getElementById('overall-pill'); pill.className='status-pill '+statusClass(status); document.getElementById('overall-status').textContent=status.toUpperCase();}
      function componentCard(item){
        const facts=Object.entries(item).filter(([k])=>!['name','status','detail'].includes(k)).map(([k,v])=>`<div><span class='scale-label'>${esc(k.replaceAll('_',' '))}</span><br><strong>${esc(typeof v==='object'?JSON.stringify(v):v)}</strong></div>`).join('');
        return `<article class='card'><div class='tile-head'><span class='tile-name'>${esc(item.name)}</span><span class='status-pill ${statusClass(item.status)}'><i></i>${esc(item.status)}</span></div><p>${esc(item.detail)}</p><div class='grid' style='margin-top:12px'>${facts}</div></article>`;
      }
      async function loadHealth(){
        try{
          const res=await fetch('/api/health/status'); if(!res.ok) throw new Error('Health request failed ('+res.status+')');
          const data=await res.json(); setOverall(data.status); document.getElementById('health-checked').textContent=new Date(data.generated_at).toLocaleString();
          document.getElementById('health-grid').innerHTML=(data.components||[]).map(componentCard).join('');
          document.getElementById('health-raw').textContent=JSON.stringify(data,null,2);
        }catch(e){setOverall('error'); document.getElementById('health-grid').innerHTML=`<div class='card'><p class='error'>${esc(e.message||'Unable to load health')}</p></div>`;}
      }
      loadHealth(); setInterval(loadHealth, 15000);
    </script>
    """


def battery_settings_body() -> str:
    return """
    <div class='settings-layout'>
      <nav class='settings-nav' role='tablist' aria-label='Settings sections'>
        <button type='button' role='tab' class='active' data-settings-section='battery' aria-controls='settings-battery' aria-selected='true'><strong>Battery</strong><span>Charging, discharge and inverter limits</span></button>
        <button type='button' role='tab' tabindex='-1' data-settings-section='trade' aria-controls='settings-trade' aria-selected='false'><strong>Energy trade</strong><span>ENTSO-E collection and retry behavior</span></button>
        <button type='button' role='tab' tabindex='-1' data-settings-section='agent' aria-controls='settings-agent' aria-selected='false'><strong>Agent</strong><span>Runtime access and token guard</span></button>
        <button type='button' role='tab' tabindex='-1' data-settings-section='appearance' aria-controls='settings-appearance' aria-selected='false'><strong>Appearance</strong><span>Light, dark or system theme</span></button>
        <button type='button' role='tab' tabindex='-1' data-settings-section='system' aria-controls='settings-system' aria-selected='false'><strong>System</strong><span>Debug logging and diagnostics</span></button>
      </nav>
      <div class='settings-panels'>
    <section id='settings-battery' role='tabpanel' class='card settings-section active' data-settings-panel='battery'><h2>Battery control</h2><p>Effective values from /battery/settings.</p>
      <form id='battery-settings' class='grid'>
        <label>Start surplus W <input name='start_w' type='number' min='100' max='5000'></label>
        <label>Stop surplus W <input name='stop_w' type='number' min='0'></label>
        <label>Start duration s <input name='start_duration' type='number' min='10' max='3600'></label>
        <label>Stop duration s <input name='stop_duration' type='number' min='10' max='3600'></label>
        <label>Cooldown s <input name='cooldown' type='number' min='60' max='7200'></label>
        <label>Max charge W <input name='max_charge_w' type='number' min='100' max='5000'></label>
        <label>Max charge A <input name='max_charge_a' type='number' min='1' max='200'></label>
        <label>Nominal battery V <input name='nominal_v' type='number' min='40' max='60'></label>
        <label>Max discharge W <input name='max_discharge_w' type='number' min='0' max='5000'></label>
        <label>Minimum SoC % <input name='soc_floor' type='number' min='0' max='100'></label>
        <label>Maximum SoC % <input name='soc_ceiling' type='number' min='0' max='100'></label>
        <label>Inverter IP <input name='inverter_ip' type='text' pattern='^([0-9]{1,3}\\.){3}[0-9]{1,3}$'></label>
        <label>Retries <input name='inverter_retries' type='number' min='1' max='10'></label>
        <label>Retry delay s <input name='inverter_delay' type='number' min='1' max='30'></label>
        <label>GoodWe poll interval s <input name='inverter_poll_interval_s' type='number' min='1' max='3600'></label>
        <p style='grid-column:1/-1;color:var(--steel);font-size:14px;margin:0'>Effective charge cap = min(max_charge_w, max_charge_a × nominal_v): <strong id='effective-charge-cap'>-- W</strong></p>
        <button type='submit'>Save battery settings</button>
      </form><pre id='settings-result'></pre></section>

    <section id='settings-trade' role='tabpanel' class='card settings-section' data-settings-panel='trade' hidden><h2>Energy trade</h2><p>EPEX day-ahead collection settings. Changes are published to MQTT and picked up without restarting <code>minyad-trade</code>.</p>
      <form id='trade-settings' class='grid'>
        <label>Bidding zone <input name='bidding_zone' type='text'></label>
        <label>Poll time Europe/Amsterdam <input name='poll_time_local' type='time'></label>
        <label>Retry attempts <input name='retry_attempts' type='number' min='1' max='24'></label>
        <label>Retry interval minutes <input name='retry_interval_minutes' type='number' min='1' max='240'></label>
        <label>ENTSO-E API URL <input name='entsoe_api_url' type='url' placeholder='https://web-api.tp.entsoe.eu/api'></label>
        <button type='submit'>Save trade settings</button>
      </form><pre id='trade-result'></pre></section>


    <section id='settings-agent' role='tabpanel' class='card settings-section' data-settings-panel='agent' hidden>
      <h2>Claude agent</h2>
      <p style='color:var(--steel);font-size:14px;margin:0 0 12px'>Laat de Claude-agentcontainer normaal draaien, maar beheer runtime of de agent Claude.ai/API-aanroepen mag doen. Wijzigingen vereisen geen containerrestart.</p>
      <p>Huidige status: <strong id='claude-agent-status' class='badge'>...</strong></p>
      <form id='claude-agent-settings' class='grid'>
        <label><input name='enabled' type='checkbox' style='width:auto'> Claude agent inschakelen</label>
        <label><input name='token_guard_enabled' type='checkbox' style='width:auto'> Token guard inschakelen</label>
        <label>Minimum tokens overhouden <input name='min_tokens_remaining' type='number' min='0' step='1'></label>
        <button type='submit'>Save Claude agent settings</button>
      </form>
      <pre id='claude-agent-result'></pre>
    </section>

    <section id='settings-appearance' role='tabpanel' class='card settings-section' data-settings-panel='appearance' hidden>
      <h2>Appearance</h2>
      <p style='color:var(--steel);font-size:14px;margin:0 0 12px'>Choose how Minyad should render every web interface. The preference is saved server-side and cached locally for instant page loads.</p>
      <div class='theme-options' role='radiogroup' aria-label='Theme preference'>
        <label class='theme-option'><input type='radio' name='theme' value='system'><b>System</b><span>Follow this device</span></label>
        <label class='theme-option'><input type='radio' name='theme' value='light'><b>Light</b><span>Bright interface</span></label>
        <label class='theme-option'><input type='radio' name='theme' value='dark'><b>Dark</b><span>Low-light interface</span></label>
      </div>
      <pre id='theme-result'></pre>
    </section>

    <section id='settings-system' role='tabpanel' class='card settings-section' data-settings-panel='system' hidden>
      <h2>System</h2>
      <div class='toggle-row'>
        <span class='status-dot' id='debug-dot'></span>
        <label><input type='checkbox' id='debug-toggle'> Debug logging</label>
      </div>
      <p style='color:#64748b;font-size:14px;margin:0 0 12px'>
        Enables verbose DEBUG-level logging on the API and all MQTT events.
        When enabled, the debug status panel below shows live diagnostics.
      </p>
      <div id='debug-status-section' style='display:none'>
        <div style='display:flex;align-items:center;gap:10px;margin-bottom:8px'>
          <strong>Debug status</strong>
          <span style='font-size:12px;color:#64748b' id='debug-refresh-ts'></span>
          <button class='secondary' style='padding:4px 10px;font-size:12px' onclick='loadDebugStatus()'>Refresh now</button>
        </div>
        <pre class='debug' id='debug-output'>Loading...</pre>
      </div>
    </section>
      </div>
    </div>

    <script>
      function showSettingsSection(name, updateHash = true) {
        const fallback = 'battery';
        const target = document.querySelector(`[data-settings-panel="${name}"]`) ? name : fallback;
        document.querySelectorAll('[data-settings-panel]').forEach((panel) => {
          const active = panel.dataset.settingsPanel === target;
          panel.classList.toggle('active', active);
          panel.hidden = !active;
        });
        document.querySelectorAll('[data-settings-section]').forEach((button) => {
          const active = button.dataset.settingsSection === target;
          button.classList.toggle('active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
          button.tabIndex = active ? 0 : -1;
        });
        if (updateHash) history.replaceState(null, '', `#${target}`);
      }
      const settingsTabs = [...document.querySelectorAll('[data-settings-section]')];
      settingsTabs.forEach((button) => {
        button.addEventListener('click', () => showSettingsSection(button.dataset.settingsSection));
        button.addEventListener('keydown', (event) => {
          const current = settingsTabs.indexOf(button);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? settingsTabs.length - 1 : event.key === 'ArrowDown' || event.key === 'ArrowRight' ? (current + 1) % settingsTabs.length : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? (current - 1 + settingsTabs.length) % settingsTabs.length : -1;
          if (next < 0) return;
          event.preventDefault();
          settingsTabs[next].focus();
          showSettingsSection(settingsTabs[next].dataset.settingsSection);
        });
      });
      window.addEventListener('hashchange', () => showSettingsSection(location.hash.slice(1), false));
      showSettingsSection(location.hash.slice(1), false);

      function updateEffectiveChargeCap(){
        const form = document.getElementById('battery-settings');
        const maxW = Number(form.elements.max_charge_w?.value || 0);
        const maxA = Number(form.elements.max_charge_a?.value || 0);
        const nominalV = Number(form.elements.nominal_v?.value || 0);
        const effective = Math.min(maxW || Infinity, (maxA && nominalV) ? maxA * nominalV : Infinity);
        document.getElementById('effective-charge-cap').textContent = Number.isFinite(effective) ? `${effective} W` : '-- W';
      }
      async function loadBatterySettings(){
        const res = await fetch('/api/battery/settings'); const data = await res.json();
        for (const [k,v] of Object.entries(data)){ const el = document.querySelector(`[name="${k}"]`); if(el) el.value = v; }
        updateEffectiveChargeCap();
        document.getElementById('settings-result').textContent = JSON.stringify(data, null, 2);
      }
      document.getElementById('battery-settings').addEventListener('input', updateEffectiveChargeCap);
      document.getElementById('battery-settings').addEventListener('submit', async (event)=>{
        event.preventDefault(); const data = {};
        new FormData(event.target).forEach((v,k)=>{ data[k] = k === 'inverter_ip' ? v : Number(v); });
        const res = await fetch('/api/battery/settings',{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        const updated = await res.json();
        document.getElementById('settings-result').textContent = JSON.stringify(updated, null, 2);
        updateEffectiveChargeCap();
      });

      async function loadTradeSettings(){
        const res = await fetch('/api/trade/settings'); const data = await res.json();
        for (const [k,v] of Object.entries(data)){ const el = document.querySelector(`#trade-settings [name="${k}"]`); if(el) el.value = v; }
        document.getElementById('trade-result').textContent = JSON.stringify(data, null, 2);
      }
      document.getElementById('trade-settings').addEventListener('submit', async (event)=>{
        event.preventDefault(); const data = {};
        new FormData(event.target).forEach((v,k)=>{ data[k] = k === 'bidding_zone' || k === 'poll_time_local' || k === 'entsoe_api_url' ? v : Number(v); });
        const res = await fetch('/api/trade/settings',{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        document.getElementById('trade-result').textContent = JSON.stringify(await res.json(), null, 2);
      });


      function renderClaudeAgentSettings(data){
        const form = document.getElementById('claude-agent-settings');
        form.elements.enabled.checked = Boolean(data.enabled);
        form.elements.token_guard_enabled.checked = Boolean(data.token_guard_enabled);
        form.elements.min_tokens_remaining.value = data.min_tokens_remaining ?? 5000;
        document.getElementById('claude-agent-status').textContent = data.enabled ? 'enabled' : 'disabled';
        document.getElementById('claude-agent-result').textContent = JSON.stringify(data, null, 2);
      }
      async function loadClaudeAgentSettings(){
        const res = await fetch('/api/claude-agent/settings');
        renderClaudeAgentSettings(await res.json());
      }
      document.getElementById('claude-agent-settings').addEventListener('submit', async (event)=>{
        event.preventDefault();
        const form = event.target;
        const data = {
          enabled: form.elements.enabled.checked,
          token_guard_enabled: form.elements.token_guard_enabled.checked,
          min_tokens_remaining: Number(form.elements.min_tokens_remaining.value || 0),
        };
        const res = await fetch('/api/claude-agent/settings',{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        renderClaudeAgentSettings(await res.json());
      });

      let debugRefreshTimer = null;

      function applyDebugState(enabled) {
        const dot = document.getElementById('debug-dot');
        const section = document.getElementById('debug-status-section');
        dot.className = 'status-dot ' + (enabled ? 'dot-on' : 'dot-off');
        if (enabled) {
          section.style.display = 'block';
          loadDebugStatus();
          if (!debugRefreshTimer) debugRefreshTimer = setInterval(loadDebugStatus, 5000);
        } else {
          section.style.display = 'none';
          clearInterval(debugRefreshTimer);
          debugRefreshTimer = null;
        }
      }

      async function loadDebugStatus() {
        try {
          const res = await fetch('/api/debug/status');
          const data = await res.json();
          document.getElementById('debug-output').textContent = JSON.stringify(data, null, 2);
          document.getElementById('debug-refresh-ts').textContent = 'refreshed ' + new Date().toLocaleTimeString();
        } catch(e) {
          document.getElementById('debug-output').textContent = 'Error: ' + e.message;
        }
      }

      document.querySelectorAll('input[name="theme"]').forEach((input) => {
        input.addEventListener('change', async (e) => {
          if (!e.target.checked) return;
          try {
            const settings = await window.minyadTheme.save(e.target.value);
            document.getElementById('theme-result').textContent = JSON.stringify({theme: settings.theme}, null, 2);
          } catch (err) {
            document.getElementById('theme-result').textContent = 'Error: ' + err.message;
          }
        });
      });

      document.getElementById('debug-toggle').addEventListener('change', async (e) => {
        const enabled = e.target.checked;
        await fetch('/api/system-settings', {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({debug_logging: enabled})
        });
        applyDebugState(enabled);
      });

      async function loadSystemSettings() {
        const res = await fetch('/api/system-settings');
        const data = await res.json();
        document.getElementById('debug-toggle').checked = data.debug_logging;
        const theme = data.theme || 'system';
        localStorage.setItem(window.minyadTheme.key, theme);
        window.minyadTheme.apply(theme);
        const themeInput = document.querySelector(`input[name="theme"][value="${theme}"]`);
        if (themeInput) themeInput.checked = true;
        document.getElementById('theme-result').textContent = JSON.stringify({theme}, null, 2);
        applyDebugState(data.debug_logging);
      }

      loadBatterySettings();
      loadTradeSettings();
      loadClaudeAgentSettings();
      loadSystemSettings();
    </script>
    """


def battery_control_body() -> str:
    return """
    <div class='card'><h2>Battery status</h2>
      <p>State: <strong id='battery-state' class='badge'>...</strong></p>
      <div class='grid'>
        <p>SOC: <meter id='battery-soc-gauge' min='0' max='100' value='0'></meter> <span id='battery-soc'>--</span>%</p>
        <p>SOH: <strong id='battery-soh'>--</strong>%</p>
        <p>Power flow: <strong id='battery-power'>--</strong> W</p>
        <p>Voltage: <strong id='battery-voltage'>--</strong> V</p>
        <p>Charge current: <strong id='battery-charge-current'>--</strong> A</p>
        <p>Battery mode: <strong id='battery-mode'>--</strong></p>
        <p>Charge setpoint: <strong id='battery-setpoint'>--</strong> W</p>
        <p>Discharge setpoint: <strong id='battery-discharge-setpoint'>--</strong> W</p>
        <p>Bridge status: <strong id='battery-bridge'>--</strong></p>
        <p>Bridge last seen: <strong id='battery-bridge-last-seen'>--</strong></p>
        <p>Override: <strong id='battery-override'>none</strong></p>
      </div>
      <p id='battery-status-error' role='alert'></p>
    </div>
    <div class='card'><h2>Battery override</h2>
      <button onclick='forceCharge()'>Force charge</button>
      <button onclick='sendOverride({mode:"force_off"})'>Force stop</button>
      <button onclick='forceDischarge()'>Force discharge</button>
      <button onclick='sendOverride({mode:"pause", duration_seconds:3600})'>Pause (1h)</button>
      <button onclick='resumeNormal()'>Resume normal</button>
    </div>
    <script>
      function displayValue(value, suffix = ''){
        return value === undefined || value === null || value === '' ? '--' : `${value}${suffix}`;
      }
      async function loadBatteryStatus(){
        const error = document.getElementById('battery-status-error');
        try {
          const res = await fetch('/api/battery/status');
          if(!res.ok) throw new Error(`Battery status request failed (${res.status})`);
          const data = await res.json();
          const override = data.override_mode && data.override_mode !== 'none';
          document.getElementById('battery-state').textContent = override ? 'OVERRIDE' : (data.state || 'IDLE');
          document.getElementById('battery-soc-gauge').value = data.soc ?? 0;
          document.getElementById('battery-soc').textContent = displayValue(data.soc);
          document.getElementById('battery-soh').textContent = displayValue(data.soh);
          document.getElementById('battery-power').textContent = displayValue(data.power_w);
          document.getElementById('battery-voltage').textContent = displayValue(data.voltage);
          document.getElementById('battery-charge-current').textContent = displayValue(data.charge_i);
          document.getElementById('battery-mode').textContent = data.mode_label || displayValue(data.mode);
          document.getElementById('battery-setpoint').textContent = displayValue(data.setpoint_w);
          document.getElementById('battery-discharge-setpoint').textContent = displayValue(data.discharge_w);
          const bridgeStatus = data.bridge_status || (data.available === true ? 'online' : data.available === false ? 'offline' : '--');
          document.getElementById('battery-bridge').textContent = data.bridge_last_seen_valid === false ? `${bridgeStatus} (error)` : bridgeStatus;
          document.getElementById('battery-bridge-last-seen').textContent = data.bridge_last_seen ? `${data.bridge_last_seen} (${displayValue(data.bridge_last_seen_age_seconds, 's')} ago)` : '--';
          document.getElementById('battery-override').textContent = data.override_mode || 'none';
          error.textContent = data.bridge_last_seen_error || '';
          error.className = data.bridge_last_seen_error ? 'error' : '';
        } catch (err) {
          error.textContent = err.message || 'Unable to load battery status';
        }
      }
      async function sendOverride(payload){
        if(!confirm('Apply battery override?')) return;
        await fetch('/api/battery/override',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        loadBatteryStatus();
      }
      function forceCharge(){ const watts = Number(prompt('Charge watts?')); if(watts) sendOverride({mode:'force_charge', watts}); }
      function forceDischarge(){ const watts = Number(prompt('Discharge watts naar huis/net via GoodWe bridge?')); if(watts) sendOverride({mode:'force_discharge', watts}); }
      async function resumeNormal(){ if(confirm('Resume normal hysteresis control?')){ await fetch('/api/battery/override',{method:'DELETE'}); loadBatteryStatus(); } }
      loadBatteryStatus(); setInterval(loadBatteryStatus, 10000);
    </script>
    """


def dsmr_body() -> str:
    return """
    <div class='card'><h2>DSMR grid status</h2>
      <p>Live data from the <code>minyad/grid</code> MQTT topic.</p>
      <div class='grid'>
        <p>Status: <strong id='grid-status'>--</strong></p>
        <p>Timestamp: <strong id='grid-timestamp'>--</strong></p>
        <p>Net power: <strong id='grid-net-power'>--</strong> W</p>
        <p>Delivered: <strong id='grid-delivered'>--</strong> W</p>
        <p>Returned: <strong id='grid-returned'>--</strong> W</p>
        <p>L1 delivered: <strong id='grid-l1-delivered'>--</strong> W</p>
        <p>L2 delivered: <strong id='grid-l2-delivered'>--</strong> W</p>
        <p>L3 delivered: <strong id='grid-l3-delivered'>--</strong> W</p>
        <p>L1 returned: <strong id='grid-l1-returned'>--</strong> W</p>
        <p>L2 returned: <strong id='grid-l2-returned'>--</strong> W</p>
        <p>L3 returned: <strong id='grid-l3-returned'>--</strong> W</p>
        <p>L1 voltage: <strong id='grid-l1-voltage'>--</strong> V</p>
        <p>L2 voltage: <strong id='grid-l2-voltage'>--</strong> V</p>
        <p>L3 voltage: <strong id='grid-l3-voltage'>--</strong> V</p>
      </div>
      <p id='dsmr-status-error' role='alert'></p>
    </div>
    <script>
      function displayValue(value){ return value === undefined || value === null || value === '' ? '--' : value; }
      async function loadDsmrStatus(){
        const error = document.getElementById('dsmr-status-error');
        try {
          const res = await fetch('/api/grid/status');
          if(!res.ok) throw new Error(`Grid status request failed (${res.status})`);
          const data = await res.json();
          document.getElementById('grid-status').textContent = displayValue(data.grid_status);
          document.getElementById('grid-timestamp').textContent = displayValue(data.grid_timestamp);
          document.getElementById('grid-net-power').textContent = displayValue(data.grid_net_power_w);
          document.getElementById('grid-delivered').textContent = displayValue(data.grid_delivered_w);
          document.getElementById('grid-returned').textContent = displayValue(data.grid_returned_w);
          document.getElementById('grid-l1-delivered').textContent = displayValue(data.grid_phase_delivered_l1_w);
          document.getElementById('grid-l2-delivered').textContent = displayValue(data.grid_phase_delivered_l2_w);
          document.getElementById('grid-l3-delivered').textContent = displayValue(data.grid_phase_delivered_l3_w);
          document.getElementById('grid-l1-returned').textContent = displayValue(data.grid_phase_returned_l1_w);
          document.getElementById('grid-l2-returned').textContent = displayValue(data.grid_phase_returned_l2_w);
          document.getElementById('grid-l3-returned').textContent = displayValue(data.grid_phase_returned_l3_w);
          document.getElementById('grid-l1-voltage').textContent = displayValue(data.grid_voltage_l1_v);
          document.getElementById('grid-l2-voltage').textContent = displayValue(data.grid_voltage_l2_v);
          document.getElementById('grid-l3-voltage').textContent = displayValue(data.grid_voltage_l3_v);
          error.textContent = '';
        } catch (err) {
          error.textContent = err.message || 'Unable to load DSMR status';
          error.className = 'error';
        }
      }
      loadDsmrStatus(); setInterval(loadDsmrStatus, 10000);
    </script>
    """


def energy_dashboard_body() -> str:
    return """
    <section class="instrument dashboard-full" aria-label="Minyad live dashboard">
      <div class="dashboard-nav"><a class="brand-lockup" href="/" aria-label="Minyad dashboard">__MARK__<span class="wordmark"><strong>Minyad</strong><span>Virtual Power Plant</span></span></a><nav class="brand-nav" aria-label="Primary navigation">__NAV__</nav></div>
      <div class="window-bar">
        <div class="window-actions">
          <div class="layout-toggle" role="tablist" aria-label="Power unit">
            <button id="watts-toggle" type="button" onclick="setPowerUnit('w')">Watts</button>
            <button id="kilowatts-toggle" class="active" type="button" onclick="setPowerUnit('kw')">Kilowatts</button>
          </div>
          <div class="layout-toggle" role="tablist" aria-label="Dashboard layout">
            <button id="cluster-toggle" class="active" type="button" onclick="setLayout('cluster')">Cluster</button>
            <button id="flow-toggle" type="button" onclick="setLayout('flow')">Flow</button>
          </div>
          <button class="mailbox-button" type="button" onclick="toggleMailbox()" aria-label="Agent mailbox">✉<span id="mailbox-badge" class="badge" hidden>0</span></button>
        </div>
      </div>
      <div id="mailbox-panel" class="mailbox-panel" hidden>
        <div class="mailbox-head"><span class="tile-name">Agent mailbox</span><button type="button" onclick="toggleMailbox(false)">Close</button></div>
        <form id="mailbox-compose" class="reply-box" onsubmit="sendAgentMessage(event)">
          <input id="mailbox-compose-subject" maxlength="160" placeholder="Subject" required>
          <textarea id="mailbox-compose-body" placeholder="Message or task for the agent…" required></textarea>
          <button type="submit">Send to agent</button>
          <small id="mailbox-compose-status" class="scale-label"></small>
        </form>
        <div class="mailbox-tabs" role="tablist" aria-label="Mailbox folders"><button id="mailbox-tab-messages" class="active" type="button" onclick="setMailboxTab('messages')">Messages</button><button id="mailbox-tab-archive" type="button" onclick="setMailboxTab('archive')">Archive</button></div>
        <div class="mailbox-layout"><div id="mailbox-list" class="mailbox-list"><span class="scale-label">Loading…</span></div><div><div id="message-detail" class="message-detail"><span class="scale-label">Select a message.</span></div><div class="mailbox-actions"><button type="button" onclick="archiveMessage()">Archive</button><button type="button" onclick="focusReply()">Reply</button><button type="button" onclick="deleteMessage()">Delete</button><button type="button" onclick="ackMessage()">Ack</button></div></div></div>
      </div>
      <div class="dash-head">
        <div class="dash-meta"><span id="clock">--:--</span> · <span id="date">--</span><br>Self-sufficiency today · <span class="self" id="self-top">--%</span></div>
      </div>
      <div class="mobile-readout">
        <div class="tile-name">Solar · now</div><div class="phrase produce-c"><span id="m-solar">--</span> <span class="unit power-unit">kW</span></div>
      </div>
      <div class="views">
        <div id="cluster-view" class="view active">
          <div class="tile-grid">
            <article class="tile produce" aria-label="Solar live tile">
              <div class="tile-head"><span class="tile-name">__SOLAR__ Solar</span><span class="status-pill produce-c" id="solar-pill"><i></i><span id="solar-status">Producing</span></span></div>
              <div class="phrase produce-c"><span id="solar-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar"><span id="solar-bar" class="fill" style="background:var(--produce-d)"></span></div><div class="scale"><span class="scale-label">0</span><span class="scale-label">~5 kWp peak</span></div><div class="load-meta"><span class="scale-label"><span id="solar-kwh">--</span> kWh today</span></div>
            </article>
            <article class="tile store" aria-label="Battery live tile">
              <div class="tile-head"><span class="tile-name">__BATTERY__ Battery</span><span class="status-pill store-c" id="battery-pill"><i></i><span id="battery-status-word">Standby</span></span></div>
              <div class="phrase store-c"><span id="battery-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar center"><span id="battery-bar" class="fill" style="background:var(--store-d);left:50%"></span></div><div class="scale"><span class="scale-label scale-power" data-kw="−3 charge" data-w="−3000 charge">−3 charge</span><span class="scale-label scale-power" data-kw="discharge +3" data-w="discharge +3000">discharge +3</span></div>
              <div class="soc"><div class="scale"><span class="scale-label">SoC</span><span class="scale-label"><span id="soc-text">--</span></span></div><div class="soc-gauge"><div class="cells" id="soc-cells"></div><span id="soc-min-line" class="soc-limit min" title="Minimum SoC" hidden></span><span id="soc-max-line" class="soc-limit max" title="Maximum SoC" hidden></span></div><div class="soc-limit-labels"><span id="soc-min-label" class="soc-limit-label min" hidden>min --%</span><span id="soc-max-label" class="soc-limit-label max" hidden>max --%</span></div><div class="scale"><span class="scale-label">SoH</span><span class="scale-label"><span id="soh-text">98% · 9.8 / 10 kWh</span></span></div><div class="thin"><i id="soh-bar" style="width:98%"></i></div></div>
            </article>
            <article class="tile import" id="grid-tile" aria-label="Grid live tile">
              <div class="tile-head"><span class="tile-name">__GRID__ Grid</span><span class="status-pill" id="grid-pill"><i></i><span id="grid-status-word">Importing</span></span></div>
              <div class="phrase" id="grid-phrase"><span id="grid-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar center"><span id="grid-bar" class="fill" style="left:50%"></span></div><div class="scale"><span class="scale-label scale-power" data-kw="−3 import" data-w="−3000 import">−3 import</span><span class="scale-label scale-power" data-kw="export +3" data-w="export +3000">export +3</span></div><div class="load-meta"><span class="scale-label"><span id="grid-import-kwh">--</span> kWh imported today</span><span class="scale-label"><span id="grid-export-kwh">--</span> exported</span></div>
            </article>
            <article class="tile household" aria-label="Household load live tile">
              <div class="tile-head"><span class="tile-name">Home Consumption</span><span class="status-pill" id="household-pill"><i></i><span id="household-status-word">Live</span></span></div>
              <div class="phrase"><span id="household-value">--</span> <span class="unit power-unit">kW</span></div>
              <svg id="household-spark" class="sparkline" viewBox="0 0 240 54" role="img" aria-label="Household load for the last hour"></svg>
              <div class="load-meta"><span class="scale-label"><span id="household-kwh">--</span> kWh today</span><span class="status-pill badge" id="household-badge" hidden>⚠ mismatch</span></div>
            </article>
          </div>
          <div class="chart-card desktop-only"><div class="chart-top"><span class="tile-name">Combined day graph · kW / EUR/kWh</span><div class="chart-legend" aria-label="Toggle day graph series"><button type="button" data-chart-series="forecast" aria-pressed="true" style="color:var(--steel)"><i></i>Forecast</button><button type="button" data-chart-series="solar" aria-pressed="true" style="color:var(--produce-d)"><i></i>Production</button><button type="button" data-chart-series="battery" aria-pressed="true" style="color:var(--store-d)"><i></i>Battery</button><button type="button" data-chart-series="grid" aria-pressed="true" style="color:var(--import-d)"><i></i>Grid</button><button type="button" data-chart-series="household" aria-pressed="true" style="color:var(--p-mut)"><i></i>Home</button><button type="button" data-chart-series="prices" aria-pressed="false" style="color:#3B82F6"><i style="height:8px;width:8px;border-radius:2px"></i>ENTSO-E prices</button></div></div><div class="chart-wrap"><svg id="day-chart" class="chart" viewBox="0 0 960 300" role="img" aria-label="Forecast, production, battery, grid, home consumption and ENTSO-E price series for today"></svg><div id="day-chart-tooltip" class="chart-tooltip" hidden></div></div><div class="daystrip"><div><b class="produce-c" id="kwh-produced">--</b><span>kWh produced</span></div><div><b id="kwh-used">--</b><span>kWh self used</span></div><div><b class="produce-c" id="kwh-exported">--</b><span>kWh exported</span></div><div><b class="import-c" id="kwh-imported">--</b><span>kWh imported</span></div></div></div>
        </div>
        <div id="flow-view" class="view"><div class="flow-board"><svg class="flow-svg" viewBox="0 0 1000 560" aria-hidden="true"><path id="flow-solar-home" class="flow-line" d="M500 135 L500 245"/><path id="flow-home-battery" class="flow-line" d="M450 290 L260 420"/><path id="flow-home-grid" class="flow-line" d="M550 290 L740 420"/></svg><div class="flow-node solar"><span class="tile-name">Solar</span><div class="phrase produce-c"><span id="f-solar">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node home"><span class="tile-name">Home</span><div class="phrase"><span id="f-home">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node battery"><span class="tile-name">Battery</span><div class="phrase store-c"><span id="f-battery">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node grid"><span class="tile-name">Grid</span><div class="phrase" id="f-grid-phrase"><span id="f-grid">--</span> <span class="unit power-unit">kW</span></div></div></div></div>
        <div class="mobile-readout"><div class="mobile-rows"><div class="mobile-row"><span class="tile-name">Battery</span><b class="value store-c" id="m-battery">-- kW</b></div><div class="mobile-row"><span class="tile-name">Grid</span><b class="value" id="m-grid">-- kW</b></div><div class="mobile-row"><span class="tile-name">Self-sufficiency</span><b class="value produce-c" id="m-self">--%</b></div></div></div>
      </div>
    </section>
    <script>
      const solarMax=5, signedMax=3, nominalKwh=10; let powerUnit='kw'; let last={solar:0,battery:0,grid:0,household:0,soc:82,soh:98}; let batteryLimits={min:null,max:null}; let curves=null; let curvesLoadedAt=0; let mailboxMessages=[]; let mailboxTab='messages'; let selectedMessageId=null; let tradePrices=[]; let tradePricesLoadedAt=0; const chartSeriesVisible={forecast:true,solar:true,battery:true,grid:true,household:true,prices:false};
      const $=id=>document.getElementById(id); const n=v=>{const x=Number(v);return Number.isFinite(x)?x:null}; const fmtPower=(v,signed=false)=>{if(v==null)return '--'; const value=powerUnit==='w'?Math.round(Math.abs(v)*1000):Math.abs(v).toFixed(2); return signed?(v>0?'+':'−')+value:String(value)}; const unitLabel=()=>powerUnit==='w'?'W':'kW';
      async function refreshMailboxCount(){try{const res=await fetch('/api/messages/unread-count'); if(!res.ok)return; const data=await res.json(); const count=Number(data.unread_count||0); const badge=$('mailbox-badge'); badge.textContent=count>99?'99+':String(count); badge.hidden=count<1;}catch(e){}}
      function mailboxChecks(m){return `<span class="message-checks" title="Human / AI acknowledgements"><span class="human ${m.operator_ack_at?'ack':''}">✓</span><span class="agent ${m.agent_ack_at?'ack':''}">✓</span></span>`;}
      async function loadMailbox(){const list=$('mailbox-list'); const detail=$('message-detail'); list.innerHTML='<span class="scale-label">Loading…</span>'; const archived=mailboxTab==='archive'; try{const res=await fetch(`/api/messages?sender=agent&limit=30&archived=${archived?'true':'false'}`); mailboxMessages=res.ok?await res.json():[];}catch(e){mailboxMessages=[];} if(!mailboxMessages.length){list.innerHTML=`<span class="scale-label">No agent messages in ${archived?'archive':'messages'}.</span>`; selectedMessageId=null; detail.innerHTML='<span class="scale-label">Select a message.</span>'; return;} if(!selectedMessageId||!mailboxMessages.some(m=>m.id===selectedMessageId))selectedMessageId=mailboxMessages[0].id; list.innerHTML=mailboxMessages.map(m=>`<button class="mailbox-item ${m.read_at?'':'unread'} ${m.id===selectedMessageId?'active':''}" type="button" onclick="openMessage(${m.id})"><small><span class="severity-dot ${m.severity}"></span>${m.category} · ${new Date(m.created_at).toLocaleString()}</small><span class="mailbox-subject"><span>${escapeHtml(m.subject)}</span>${mailboxChecks(m)}</span></button>`).join(''); await openMessage(selectedMessageId,false);}
      function setMailboxTab(tab){mailboxTab=tab; selectedMessageId=null; $('mailbox-tab-messages').classList.toggle('active',tab==='messages'); $('mailbox-tab-archive').classList.toggle('active',tab==='archive'); loadMailbox();}
      function toggleMailbox(open){const panel=$('mailbox-panel'); const shouldOpen=open===undefined?panel.hidden:open; panel.hidden=!shouldOpen; if(shouldOpen){loadMailbox(); refreshMailboxCount();}}
      function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
      async function openMessage(id,markRead=true){selectedMessageId=id; const detail=$('message-detail'); let payload=null; try{const res=await fetch(`/api/messages/${id}`); if(res.ok)payload=await res.json();}catch(e){} if(!payload)return; const m=payload.message; detail.hidden=false; detail.innerHTML=`<small class="tile-name"><span class="severity-dot ${m.severity}"></span>${m.category} · ${m.severity} ${mailboxChecks(m)}</small><h3>${escapeHtml(m.subject)}</h3><p>${escapeHtml(m.body)}</p>${m.related_decision_id?`<p><span class="scale-label">Related decision #${m.related_decision_id}</span></p>`:''}<div class="reply-box"><textarea id="reply-body" placeholder="Reply to the agent…"></textarea></div>`; document.querySelectorAll('.mailbox-item').forEach(el=>el.classList.toggle('active',el.getAttribute('onclick')===`openMessage(${id})`)); if(markRead&&!m.read_at){await fetch(`/api/messages/${id}/read`,{method:'PATCH'}); refreshMailboxCount(); loadMailbox();}}
      async function sendAgentMessage(event){event.preventDefault();const subject=$('mailbox-compose-subject').value.trim();const body=$('mailbox-compose-body').value.trim();const status=$('mailbox-compose-status');if(!subject||!body)return;status.textContent='Sending…';try{const res=await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender:'operator',category:'info',subject,body,severity:'normal'})});if(!res.ok)throw new Error('Unable to send message');$('mailbox-compose-subject').value='';$('mailbox-compose-body').value='';status.textContent='Sent. The agent will pick it up in the next cycle.';}catch(e){status.textContent=e.message||'Unable to send message';}}
      async function sendReply(threadId){const body=$('reply-body').value.trim(); if(!body)return; await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender:'operator',category:'reply',subject:'Operator reply',body,thread_id:threadId,severity:'normal'})}); $('reply-body').value='';}
      function currentMessage(){return mailboxMessages.find(m=>m.id===selectedMessageId)}
      async function focusReply(){const box=$('reply-body'), m=currentMessage(); if(!box)return; if(box.value.trim()&&m){await sendReply(m.thread_id||m.id); await loadMailbox(); return;} box.focus();}
      async function archiveMessage(){if(!selectedMessageId)return; await fetch(`/api/messages/${selectedMessageId}/archive`,{method:'PATCH'}); selectedMessageId=null; await loadMailbox(); refreshMailboxCount();}
      async function deleteMessage(){if(!selectedMessageId)return; await fetch(`/api/messages/${selectedMessageId}`,{method:'DELETE'}); selectedMessageId=null; await loadMailbox(); refreshMailboxCount();}
      async function ackMessage(){if(!selectedMessageId)return; await fetch(`/api/messages/${selectedMessageId}/ack?actor=operator`,{method:'PATCH'}); await loadMailbox();}
      function setLayout(name){$('cluster-view').classList.toggle('active',name==='cluster');$('flow-view').classList.toggle('active',name==='flow');$('cluster-toggle').classList.toggle('active',name==='cluster');$('flow-toggle').classList.toggle('active',name==='flow')}
      function toggleChartSeries(series){chartSeriesVisible[series]=!chartSeriesVisible[series]; document.querySelectorAll(`[data-chart-series="${series}"]`).forEach(el=>el.setAttribute('aria-pressed', chartSeriesVisible[series]?'true':'false')); hideChartTooltip(); drawChart();}
      function initChartLegend(){document.querySelectorAll('[data-chart-series]').forEach(el=>el.addEventListener('click',()=>toggleChartSeries(el.dataset.chartSeries)));}
      function setPowerUnit(unit){powerUnit=unit; $('watts-toggle').classList.toggle('active',unit==='w'); $('kilowatts-toggle').classList.toggle('active',unit==='kw'); document.querySelectorAll('.power-unit').forEach(el=>el.textContent=unitLabel()); document.querySelectorAll('.scale-power').forEach(el=>el.textContent=el.dataset[unit]); renderReadings();}
      function setStatusPill(id,colorClass,isActive){const el=$(id); if(!el)return; el.className='status-pill '+colorClass+(isActive?' flash':'');}
      function renderReadings(){const home=Math.max(0,last.household||last.solar+last.battery-last.grid), gExport=last.grid>=0; $('solar-value').textContent=fmtPower(last.solar); $('m-solar').textContent=fmtPower(last.solar); $('battery-value').textContent=fmtPower(last.battery,true); $('grid-value').textContent=fmtPower(last.grid,true); $('household-value').textContent=fmtPower(home); $('f-solar').textContent=fmtPower(last.solar); $('f-battery').textContent=fmtPower(last.battery,true); $('f-grid').textContent=fmtPower(last.grid,true); $('f-home').textContent=fmtPower(home); $('m-battery').textContent=fmtPower(last.battery,true)+' '+unitLabel(); $('m-grid').textContent=fmtPower(last.grid,true)+' '+unitLabel(); $('f-grid-phrase').className='phrase '+(gExport?'produce-c':'import-c');}
      function setBar(id,v,max,color){const el=$(id); if(!el)return; const pct=Math.min(100,Math.abs(v)/max*50); el.style.background=color; if(v<0){el.style.left=(50-pct)+'%';el.style.width=pct+'%'}else{el.style.left='50%';el.style.width=pct+'%'}}
      function setSoc(soc){$('soc-text').textContent=Math.round(soc)+'%'; const c=$('soc-cells'); c.innerHTML=''; for(let i=0;i<10;i++){const cell=document.createElement('i'); if(i<Math.round(soc/10))cell.className='on'; c.appendChild(cell)} renderSocLimits();}
      function clampPct(value){return Math.max(0,Math.min(100,value));}
      function renderSocLimits(){const min=n(batteryLimits.min), max=n(batteryLimits.max); const limits=[['min',min],['max',max]]; for(const [kind,value] of limits){const line=$(`soc-${kind}-line`), label=$(`soc-${kind}-label`); if(!line||!label)continue; const hasValue=value!=null; line.hidden=!hasValue; label.hidden=!hasValue; if(!hasValue)continue; const pct=clampPct(value); line.style.left=pct+'%'; label.style.left=pct+'%'; label.textContent=`${kind} ${Math.round(value)}%`;}}
      async function loadBatteryLimits(){try{const res=await fetch('/api/battery/settings'); if(!res.ok)return; const settings=await res.json(); batteryLimits={min:n(settings.soc_floor),max:n(settings.soc_ceiling)}; renderSocLimits();}catch(e){}}
      async function loadCurves(){const now=Date.now(); if(curves&&now-curvesLoadedAt<60000)return curves; try{const res=await fetch('/api/dashboard/curves?window=day'); if(res.ok){curves=await res.json(); curvesLoadedAt=now;}}catch(e){} return curves;}
      async function loadTradePrices(){const now=Date.now(); if(tradePrices.length&&now-tradePricesLoadedAt<300000)return tradePrices; try{const res=await fetch('/api/trade/prices'); const data=res.ok?await res.json():{prices:[]}; tradePrices=(data.prices||[]).filter(p=>p.starts_at&&Number.isFinite(new Date(p.starts_at).getTime())&&Number.isFinite(Number(p.price_eur_kwh))).map(p=>({...p,source:'prices',price_eur_kwh:Number(p.price_eur_kwh)})).sort((a,b)=>new Date(a.starts_at)-new Date(b.starts_at)); tradePricesLoadedAt=now;}catch(e){} return tradePrices;}
      function upsertCurvePoint(source,powerKw){if(!curves)curves={series:{solar:[],battery:[],grid:[],household:[]}}; if(!curves.series)curves.series={}; const items=curves.series[source]||(curves.series[source]=[]), ts=new Date(), minute=ts.toISOString().slice(0,16), point={timestamp:ts.toISOString(),power_w:Math.round(Math.max(0,powerKw)*1000)}; const idx=items.findIndex(p=>String(p.timestamp||'').slice(0,16)===minute); if(idx>=0)items[idx]=point; else items.push(point); items.sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function appendCurrentChartPoints(){upsertCurvePoint('solar',last.solar); upsertCurvePoint('household',last.household);}
      function dayKwh(items, valueFn=p=>p.power_w||0){let total=0; for(let i=1;i<items.length;i++){const a=items[i-1],b=items[i],dt=(new Date(b.timestamp)-new Date(a.timestamp))/3600000; if(dt>0&&dt<1.1)total+=(valueFn(a)+valueFn(b))/2/1000*dt;} return total;}
      function householdDayKwh(items){return dayKwh(items,p=>Math.max(0,p.power_w||0));}
      function solarDayKwh(items){return dayKwh(items,p=>Math.max(0,p.power_w||0));}
      function gridDayKwh(items, direction){return dayKwh(items,p=>{const w=p.net_w??p.power_w??0; return direction==='import'?Math.max(0,w):Math.max(0,-w);});}
      function householdMismatchText(household){if(!household?.mismatch)return ''; const pct=n(household.deviation_pct), a=n(household.method_a_w), b=n(household.method_b_w); const parts=['Mismatch: de berekende Home Consumption komt niet overeen tussen de solar/battery-only check en de DSMR-netmeter check.']; if(pct!=null)parts.push(`Afwijking ${pct.toFixed(1)}%.`); if(a!=null&&b!=null)parts.push(`Zonder DSMR: ${Math.round(a)} W; met DSMR: ${Math.round(b)} W.`); parts.push('Controleer of DSMR, solar en batterijmetingen actueel zijn en dezelfde richting/eenheden gebruiken.'); return parts.join(' ');}
      function drawHouseholdSpark(items){const svg=$('household-spark'), W=240,H=54, pad=3; if(!items||items.length<2){svg.innerHTML='';return;} const now=Date.now(), recent=items.filter(p=>new Date(p.timestamp)>=now-3600000); const data=recent.length>1?recent:items.slice(-60); const max=Math.max(1000,...data.map(p=>p.power_w||0)); const min=0; const first=new Date(data[0].timestamp).getTime(), lastTs=new Date(data[data.length-1].timestamp).getTime(), span=Math.max(1,lastTs-first); const x=p=>pad+(W-pad*2)*(new Date(p.timestamp).getTime()-first)/span; const y=p=>H-pad-(H-pad*2)*((p.power_w||0)-min)/(max-min||1); svg.innerHTML=`<path d="${data.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)} ${y(p).toFixed(1)}`).join(' ')}"/>`;}
      function normalizeChartItems(items, source){return (items||[]).map(p=>{const power=source==='grid'?-(p.net_w??p.power_w??0):(p.power_w||0); return {...p,source,power_w:power};}).filter(p=>p.timestamp&&Number.isFinite(new Date(p.timestamp).getTime())&&Number.isFinite(p.power_w));}
      function isSameChartDay(timestamp, day){const d=new Date(timestamp); return d.getFullYear()===day.getFullYear()&&d.getMonth()===day.getMonth()&&d.getDate()===day.getDate();}
      function prepareChartItems(items, day=new Date()){const byMinute=new Map(); for(const item of items||[]){if(!isSameChartDay(item.timestamp,day))continue; const key=new Date(item.timestamp).toISOString().slice(0,16); byMinute.set(key,item);} return [...byMinute.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function mergeChartItems(...groups){const byMinute=new Map(); for(const group of groups){for(const item of group||[]){const key=new Date(item.timestamp).toISOString().slice(0,16); if(!byMinute.has(key))byMinute.set(key,item);}} return [...byMinute.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function chartPointMeta(point){const kw=(point.power_w||0)/1000, absKw=Math.abs(kw).toFixed(2), time=new Date(point.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); if(point.source==='battery'){const state=Math.abs(point.power_w||0)<30?'Standby':point.power_w>0?'Discharging':'Charging'; const delivered=point.power_w>0?point.power_w:(point.delivered_w??0); const accepted=point.power_w<0?Math.abs(point.power_w):(point.returned_w??0); const soc=n(point.soc)??last.soc; return {label:'Battery', color:'var(--store-d)', time, lines:[`State: ${state}`, `Power delivered: ${Math.round(Math.max(0,delivered))} W (${absKw} kW)`, `Charge power: ${Math.round(Math.max(0,accepted))} W`, `Charge state: ${Math.round(soc)}%`]};} if(point.source==='solar')return {label:'Production', color:'var(--produce-d)', time, lines:[`Power: ${Math.round(point.power_w||0)} W (${absKw} kW)`]}; if(point.source==='grid'){const state=point.power_w>=0?'Exporting':'Importing'; return {label:'Grid', color:'var(--import-d)', time, lines:[`State: ${state}`, `Power: ${Math.round(Math.abs(point.power_w||0))} W (${absKw} kW)`]};} if(point.source==='household')return {label:'Home Consumption', color:'var(--p-mut)', time, lines:[`Power: ${Math.round(Math.max(0,point.power_w||0))} W (${absKw} kW)`]}; if(point.source==='prices')return {label:'ENTSO-E price', color:'#3B82F6', time:new Date(point.starts_at||point.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}), lines:[`Price: ${Number(point.price_eur_kwh).toFixed(4)} EUR/kWh`]}; return {label:'Forecast', color:'var(--steel)', time, lines:[`Expected production: ${Math.round(point.power_w||0)} W (${absKw} kW)`]};}
      function showChartTooltip(event, point, xPos, yPos){const tip=$('day-chart-tooltip'), svg=$('day-chart'); if(!tip||!svg)return; const meta=chartPointMeta(point); tip.innerHTML=`<b style="color:${meta.color}">${meta.label} · ${meta.time}</b>${meta.lines.map(line=>`<span>${escapeHtml(line)}</span>`).join('')}`; const dot=$('day-chart-hover-dot'); if(dot){dot.setAttribute('cx',xPos); dot.setAttribute('cy',yPos); dot.setAttribute('fill',meta.color); dot.style.display='block';} const rect=svg.getBoundingClientRect(), wrap=svg.parentElement.getBoundingClientRect(); tip.style.left=(rect.left-wrap.left+(xPos/960)*rect.width)+'px'; tip.style.top=(rect.top-wrap.top+(yPos/300)*rect.height)+'px'; tip.hidden=false;}
      function hideChartTooltip(){const tip=$('day-chart-tooltip'), dot=$('day-chart-hover-dot'); if(tip)tip.hidden=true; if(dot)dot.style.display='none';}
      function drawChart(){
        const svg=$('day-chart'), W=960,H=300, left=42,right=16,top=16,bot=28, mid=150, now=new Date(), hour=now.getHours()+now.getMinutes()/60;
        const x=t=>left+(W-left-right)*t/24, y=kw=>mid-kw/5*(mid-top), toHour=iso=>{const d=new Date(iso);return d.getHours()+d.getMinutes()/60+d.getSeconds()/3600};
        let out='';
        for(let h=0;h<=24;h+=6)out+=`<line class="gridline" x1="${x(h)}" y1="${top}" x2="${x(h)}" y2="${H-bot}"/><text x="${x(h)}" y="${H-7}" fill="var(--p-mut)" font-family="var(--mono)" font-size="11" text-anchor="middle">${String(h).padStart(2,'0')}:00</text>`;
        for(let kw=-5;kw<=5;kw+=2.5)out+=`<text x="8" y="${y(kw)+4}" fill="var(--p-mut)" font-family="var(--mono)" font-size="10">${kw}</text>`;
        out+=`<line class="zero-line" x1="${left}" y1="${mid}" x2="${W-right}" y2="${mid}"/>`;
        const pts=[...Array(49)].map((_,i)=>i/2), path=(fn)=>pts.map((t,i)=>`${i?'L':'M'}${x(t).toFixed(1)} ${y(fn(t)).toFixed(1)}`).join(' '), area=(fn,base=0)=>`M${x(0)} ${y(base)} `+pts.map(t=>`L${x(t).toFixed(1)} ${y(fn(t)).toFixed(1)}`).join(' ')+` L${x(24)} ${y(base)} Z`;
        const pointPath=items=>items&&items.length?items.map((p,i)=>`${i?'L':'M'}${x(toHour(p.timestamp)).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '):'';
        const chartDay=now, forecastItems=prepareChartItems(normalizeChartItems(curves?.forecast,'forecast'),chartDay), solarItems=prepareChartItems(normalizeChartItems(curves?.series?.solar,'solar'),chartDay), batteryItems=mergeChartItems(prepareChartItems(normalizeChartItems(curves?.series?.battery,'battery'),chartDay),prepareChartItems(normalizeChartItems(curves?.battery_forecast,'battery'),chartDay)), gridItems=prepareChartItems(normalizeChartItems(curves?.series?.grid,'grid'),chartDay), householdItems=prepareChartItems(normalizeChartItems(curves?.series?.household,'household'),chartDay), priceItems=(tradePrices||[]).filter(p=>isSameChartDay(p.starts_at,chartDay));
        const signedArea=(items,positive,klass)=>items&&items.length?`<path class="${klass}" d="M${x(toHour(items[0].timestamp)).toFixed(1)} ${y(0)} `+items.map(p=>{const kw=(p.power_w||0)/1000; return `L${x(toHour(p.timestamp)).toFixed(1)} ${y(positive?Math.max(0,kw):Math.min(0,kw)).toFixed(1)}`}).join(' ')+` L${x(toHour(items[items.length-1].timestamp)).toFixed(1)} ${y(0)} Z"/>`:'';
        const visible=chartSeriesVisible; const paths=[['forecast-line',forecastItems,visible.forecast],['prod-line',solarItems,visible.solar],['bat-line',batteryItems,visible.battery],['grid-line',gridItems,visible.grid],['home-line',householdItems,visible.household]];
        if(visible.prices&&priceItems.length){const vals=priceItems.map(p=>p.price_eur_kwh), minP=Math.min(...vals), maxP=Math.max(...vals), lo=Math.min(0,minP), hi=maxP===lo?lo+0.01:maxP, barW=Math.max(2,(W-left-right)/Math.max(24,priceItems.length)*.24), yPrice=v=>H-bot-(H-bot-top)*(v-lo)/(hi-lo||1), priceColor=v=>{const t=(v-minP)/(maxP-minP||1), from=[191,219,254], to=[29,78,216], c=from.map((n,i)=>Math.round(n+(to[i]-n)*t)); return `rgb(${c[0]},${c[1]},${c[2]})`;}; for(const p of priceItems){const h=toHour(p.starts_at), x0=x(h)-barW/2, y0=yPrice(Math.max(lo,p.price_eur_kwh)), h0=Math.max(2,H-bot-y0); out+=`<rect x="${x0.toFixed(1)}" y="${y0.toFixed(1)}" width="${barW.toFixed(1)}" height="${h0.toFixed(1)}" rx="2" fill="${priceColor(p.price_eur_kwh)}" opacity="0.72" onmouseleave="hideChartTooltip()" onmousemove="handleChartHover(event,'price-bars')"/>`; } out+=`<text x="${W-right-2}" y="${top+10}" fill="#3B82F6" font-family="var(--mono)" font-size="10" text-anchor="end">${maxP.toFixed(3)} €/kWh</text>`;}
        out+=visible.forecast&&pointPath(forecastItems)?`<path class="forecast-line" d="${pointPath(forecastItems)}"/>`:'';
        out+=visible.solar&&pointPath(solarItems)?`<path class="prod-line" d="${pointPath(solarItems)}"/>`:'';
        out+=visible.battery?(pointPath(batteryItems)?signedArea(batteryItems,true,'bat-charge-fill')+signedArea(batteryItems,false,'bat-discharge-fill')+`<path class="bat-line" d="${pointPath(batteryItems)}"/>`:`<path class="bat-line" d="${path(t=>1.2*Math.sin((t-15)/24*Math.PI*4))}"/>`):'';
        out+=visible.grid?(pointPath(gridItems)?signedArea(gridItems,true,'grid-import-fill')+signedArea(gridItems,false,'grid-export-fill')+`<path class="grid-line" d="${pointPath(gridItems)}"/>`:`<path class="imp-fill" d="${area(t=>Math.min(0,1.2*Math.sin((t-12)/24*Math.PI*4)),0)}"/><path class="exp-fill" d="${area(t=>Math.max(0,1.0*Math.sin((t-10)/24*Math.PI*3)),0)}"/>`):'';
        out+=visible.household&&pointPath(householdItems)?`<path class="home-line" d="${pointPath(householdItems)}"/>`:'';
        out+=`<line class="now" x1="${x(hour)}" y1="${top}" x2="${x(hour)}" y2="${H-bot}"/>${visible.solar?`<circle cx="${x(hour)}" cy="${y(last.solar)}" r="4" fill="var(--produce-d)"/>`:''}<text x="${x(hour)+7}" y="${top+12}" fill="var(--p-ink)" font-family="var(--mono)" font-size="10">NOW</text>`;
        out+=`<circle id="day-chart-hover-dot" class="chart-dot" r="5" style="display:none"/>`; for(const [klass,items,isVisible] of paths){if(!isVisible)continue;const d=pointPath(items); if(!d)continue; out+=`<path class="chart-hover" d="${d}" onmouseleave="hideChartTooltip()" onmousemove="handleChartHover(event,'${klass}')"/>`;}
        svg.innerHTML=out;
        window.chartHoverSeries={'forecast-line':forecastItems,'prod-line':solarItems,'bat-line':batteryItems,'grid-line':gridItems,'home-line':householdItems,'price-bars':priceItems};
      }
      function handleChartHover(event,key){const svg=$('day-chart'), items=window.chartHoverSeries?.[key]||[]; if(!items.length)return; const pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); const hour=Math.max(0,Math.min(24,(loc.x-42)/(960-42-16)*24)); let nearest=items[0], best=Infinity; for(const item of items){const ts=key==='price-bars'?item.starts_at:item.timestamp, d=new Date(ts), delta=Math.abs((d.getHours()+d.getMinutes()/60+d.getSeconds()/3600)-hour); if(delta<best){best=delta; nearest=item;}} const isPrice=key==='price-bars', h=toChartHour(isPrice?nearest.starts_at:nearest.timestamp), yPos=isPrice?Math.max(24,Math.min(272,loc.y)):150-((nearest.power_w||0)/1000)/5*(150-16); showChartTooltip(event,nearest,42+(960-42-16)*h/24,yPos);}
      function toChartHour(iso){const d=new Date(iso);return d.getHours()+d.getMinutes()/60+d.getSeconds()/3600;}
      async function update(){const d=new Date(); $('clock').textContent=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); $('date').textContent=d.toLocaleDateString([], {day:'2-digit',month:'short',year:'numeric'}); let battery={},grid={},household={}; try{[grid,battery,household]=await Promise.all([fetch('/api/grid/status').then(r=>r.ok?r.json():{}),fetch('/api/battery/status').then(r=>r.ok?r.json():{}),fetch('/api/household/status').then(r=>r.ok?r.json():{})])}catch(e){}
        const solarW=n(grid.solar_power_w); last.solar=solarW==null?0:solarW/1000; last.battery=(n(battery.power_w)??0)/1000; const rawGrid=(n(grid.grid_net_power_w)??650)/1000; last.grid=-rawGrid; last.household=(n(household.power_w)??Math.max(0,last.solar*1000+last.battery*1000-last.grid*1000))/1000; last.soc=n(battery.soc)??last.soc; last.soh=n(battery.soh)??98; const home=Math.max(0,last.household);
        $('household-status-word').textContent=household.approx?'Approx':'Live'; setStatusPill('household-pill',household.approx?'store-c':'household-c',home>.03); const mismatchText=householdMismatchText(household); const badge=$('household-badge'); badge.hidden=!household.mismatch; badge.className='status-pill badge '+(household.mismatch?'warn':''); badge.title=mismatchText; badge.setAttribute('aria-label', mismatchText||'Geen household mismatch');
        renderReadings(); const solarActive=last.solar>0.05; $('solar-bar').style.width=Math.min(100,last.solar/solarMax*100)+'%'; $('solar-status').textContent=solarActive?'Producing':'Standby'; setStatusPill('solar-pill','produce-c',solarActive);
        const batteryActive=Math.abs(last.battery)>=.03; $('battery-status-word').textContent=!batteryActive?'Standby':last.battery>0?'Discharging':'Charging'; setStatusPill('battery-pill','store-c',batteryActive); setBar('battery-bar',last.battery,signedMax,'var(--store-d)'); setSoc(last.soc); $('soh-text').textContent=`${Math.round(last.soh)}% · ${(nominalKwh*last.soh/100).toFixed(1)} / 10 kWh`; $('soh-bar').style.width=last.soh+'%';
        const gExport=last.grid>=0; $('grid-status-word').textContent=Math.abs(last.grid)<.03?'Standby':gExport?'Exporting':'Importing'; $('grid-phrase').className='phrase '+(gExport?'produce-c':'import-c'); setStatusPill('grid-pill',gExport?'produce-c':'import-c',Math.abs(last.grid)>=.03); $('grid-tile').className='tile '+(gExport?'produce':'import'); setBar('grid-bar',last.grid,signedMax,gExport?'var(--produce-d)':'var(--import-d)');
        $('flow-solar-home').style.stroke='var(--produce-d)'; $('flow-solar-home').style.strokeWidth=2+Math.min(10,last.solar*2); $('flow-home-battery').style.stroke='var(--store-d)'; $('flow-home-battery').style.strokeWidth=2+Math.min(10,Math.abs(last.battery)*3); $('flow-home-grid').style.stroke=gExport?'var(--produce-d)':'var(--import-d)'; $('flow-home-grid').style.strokeWidth=2+Math.min(10,Math.abs(last.grid)*3);
        await Promise.all([loadCurves(),loadTradePrices()]); appendCurrentChartPoints(); const hItems=curves?.series?.household||[], sItems=curves?.series?.solar||[], gItems=curves?.series?.grid||[]; const produced=solarDayKwh(sItems), imported=gridDayKwh(gItems,'import'), exported=gridDayKwh(gItems,'export'), householdKwh=householdDayKwh(hItems), used=Math.max(0,produced-exported); $('solar-kwh').textContent=produced.toFixed(1); $('grid-import-kwh').textContent=imported.toFixed(1); $('grid-export-kwh').textContent=exported.toFixed(1); $('kwh-produced').textContent=produced.toFixed(1); $('kwh-exported').textContent=exported.toFixed(1); $('kwh-imported').textContent=imported.toFixed(1); $('kwh-used').textContent=used.toFixed(1); const self=Math.round(100*Math.max(0,used)/(used+imported||1)); $('self-top').textContent=self+'%'; $('m-self').textContent=self+'%'; drawHouseholdSpark(hItems); $('household-kwh').textContent=householdKwh.toFixed(1); drawChart(); }
      initChartLegend(); refreshMailboxCount(); setInterval(refreshMailboxCount,45000); loadBatteryLimits(); setInterval(loadBatteryLimits,60000); update(); setInterval(update,4000);
    </script>
    """.replace("__MARK__", brand_mark()).replace("__NAV__", render_nav("Dashboard")).replace("__SOLAR__", icon("solar")).replace("__BATTERY__", icon("battery")).replace("__GRID__", icon("grid"))


def history_body() -> str:
    return """
    <section class='card'>
      <div class='history-tabs' role='tablist' aria-label='History granularity'>
        <button class='history-tab active' type='button' role='tab' aria-selected='true' data-history-window='day'>Dag</button>
        <button class='history-tab' type='button' role='tab' aria-selected='false' data-history-window='month'>Maand</button>
        <button class='history-tab' type='button' role='tab' aria-selected='false' data-history-window='year'>Jaar</button>
      </div>
      <div class='history-chart-card'>
        <div class='history-toolbar'>
          <div><span class='tile-name' id='history-title'>Dag overzicht · kW</span><div class='history-hint' id='history-range'>Laden…</div></div>
          <div class='chart-legend' aria-label='Toggle history series'>
            <button type='button' data-history-series='forecast' aria-pressed='true' style='color:var(--steel)'><i></i>Forecast</button>
            <button type='button' data-history-series='solar' aria-pressed='true' style='color:var(--produce-d)'><i></i>Production</button>
            <button type='button' data-history-series='battery' aria-pressed='true' style='color:var(--store-d)'><i></i>Battery</button>
            <button type='button' data-history-series='grid' aria-pressed='true' style='color:var(--import-d)'><i></i>Grid</button>
            <button type='button' data-history-series='household' aria-pressed='true' style='color:var(--steel)'><i></i>Home</button>
          </div>
        </div>
        <div class='chart-wrap'>
          <svg id='history-chart' class='history-chart' viewBox='0 0 960 420' role='img' aria-label='Historical power curves'></svg>
          <div id='history-tooltip' class='history-tooltip' hidden></div>
        </div>
        <svg id='history-mini' class='history-mini' viewBox='0 0 960 78' role='img' aria-label='Zoom selector'></svg>
        <div class='history-hint'>Tip: sleep over de onderste mini-grafiek om een periode te selecteren. Dubbelklik boven of onder om terug uit te zoomen.</div>
        <div class='history-stats'>
          <div class='history-stat'><b id='hist-produced'>--</b><span>kWh produced</span></div>
          <div class='history-stat'><b id='hist-used'>--</b><span>kWh self used</span></div>
          <div class='history-stat'><b id='hist-exported'>--</b><span>kWh exported</span></div>
          <div class='history-stat'><b id='hist-imported'>--</b><span>kWh imported</span></div>
        </div>
      </div>
    </section>
    <script>
      const H={window:'day', data:null, zoom:null, dragging:null, visible:{forecast:true,solar:true,battery:true,grid:true,household:true}};
      const $=id=>document.getElementById(id), n=v=>{const x=Number(v);return Number.isFinite(x)?x:null};
      const colors={forecast:'var(--steel)',solar:'var(--produce-d)',battery:'var(--store-d)',grid:'var(--import-d)',household:'var(--steel)'};
      function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
      function normalize(items,source){return (items||[]).map(p=>{const power=source==='grid'?-(p.net_w??p.power_w??0):(p.power_w||0); return {...p,source,power_w:power,t:new Date(p.timestamp).getTime()};}).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.power_w)).sort((a,b)=>a.t-b.t);}
      function allSeries(){const d=H.data||{}; return {forecast:normalize(d.forecast,'forecast'),solar:normalize(d.series?.solar,'solar'),battery:normalize([...(d.series?.battery||[]),...(d.battery_forecast||[])],'battery'),grid:normalize(d.series?.grid,'grid'),household:normalize(d.series?.household,'household')};}
      function domain(series){const points=Object.values(series).flat(); const start=new Date(H.data?.start||Date.now()).getTime(), end=new Date(H.data?.end||Date.now()).getTime(); return H.zoom||[Math.min(start,...points.map(p=>p.t)),Math.max(end,...points.map(p=>p.t))];}
      function fmtDate(ts){const opts=H.window==='day'?{weekday:'short',hour:'2-digit',minute:'2-digit'}:H.window==='month'?{day:'2-digit',month:'short'}:{month:'short',year:'numeric'}; return new Date(ts).toLocaleString([],opts);}
      function kwh(items,fn=p=>p.power_w||0){let total=0; for(let i=1;i<items.length;i++){const a=items[i-1],b=items[i],dt=(b.t-a.t)/3600000; if(dt>0&&dt<900)total+=(fn(a)+fn(b))/2/1000*dt;} return total;}
      function updateStats(series){const produced=kwh(series.solar,p=>Math.max(0,p.power_w||0)), imported=kwh(series.grid,p=>Math.max(0,-p.power_w||0)), exported=kwh(series.grid,p=>Math.max(0,p.power_w||0)), used=Math.max(0,produced-exported); $('hist-produced').textContent=produced.toFixed(1); $('hist-imported').textContent=imported.toFixed(1); $('hist-exported').textContent=exported.toFixed(1); $('hist-used').textContent=used.toFixed(1);}
      function draw(){const svg=$('history-chart'), mini=$('history-mini'), W=960,Hh=420,left=56,right=18,top=22,bot=42; const s=allSeries(); updateStats(s); const [minT,maxT]=domain(s); const visible=Object.entries(s).filter(([k])=>H.visible[k]).flatMap(([,v])=>v.filter(p=>p.t>=minT&&p.t<=maxT)); if(!visible.length){svg.innerHTML='<foreignObject width="960" height="420"><div class="history-empty">Geen historische punten beschikbaar voor deze periode.</div></foreignObject>'; mini.innerHTML=''; return;} const maxKw=Math.max(1,...visible.map(p=>Math.abs(p.power_w)/1000))*1.15; const x=t=>left+(W-left-right)*(t-minT)/(maxT-minT||1), y=kw=>top+(Hh-top-bot)*(1-(kw+maxKw)/(maxKw*2)); let out=''; for(let i=0;i<=4;i++){const kw=-maxKw+i*(maxKw/2), yy=y(kw); out+=`<line class="gridline" x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}"/><text x="10" y="${yy+4}" fill="var(--steel)" font-family="var(--mono)" font-size="10">${kw.toFixed(1)}</text>`;} for(let i=0;i<=6;i++){const t=minT+i*(maxT-minT)/6; out+=`<text x="${x(t)}" y="${Hh-12}" fill="var(--steel)" font-family="var(--mono)" font-size="10" text-anchor="middle">${fmtDate(t)}</text>`;} out+=`<line class="zero-line" x1="${left}" y1="${y(0)}" x2="${W-right}" y2="${y(0)}"/>`; for(const [key,items] of Object.entries(s)){if(!H.visible[key])continue; const pts=items.filter(p=>p.t>=minT&&p.t<=maxT); if(pts.length<2)continue; const d=pts.map((p,i)=>`${i?'L':'M'}${x(p.t).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '); const cls=key==='solar'?'prod-line':key==='battery'?'bat-line':key==='grid'?'grid-line':key==='household'?'home-line':'forecast-line'; out+=`<path class="${cls}" d="${d}"/><path class="chart-hover" d="${d}" onmousemove="showTip(event,'${key}')" onmouseleave="hideTip()"/>`; } svg.innerHTML=out; drawMini(s,minT,maxT); $('history-range').textContent=`${fmtDate(minT)} → ${fmtDate(maxT)} · sleep onderaan om te zoomen`;}
      function drawMini(series,minT,maxT){const mini=$('history-mini'), W=960,Hh=78,left=56,right=18,top=8,bot=12; const all=Object.values(series).flat(), fullMin=Math.min(...all.map(p=>p.t)), fullMax=Math.max(...all.map(p=>p.t)), max=Math.max(1,...all.map(p=>Math.abs(p.power_w)/1000)); const x=t=>left+(W-left-right)*(t-fullMin)/(fullMax-fullMin||1), y=kw=>top+(Hh-top-bot)*(1-kw/max); const pts=series.solar.length?series.solar:all; const d=pts.map((p,i)=>`${i?'L':'M'}${x(p.t).toFixed(1)} ${y(Math.abs(p.power_w)/1000).toFixed(1)}`).join(' '); mini.innerHTML=`<path class="forecast-fill" d="${d}"/><rect class="history-window" x="${x(minT)}" y="${top}" width="${Math.max(2,x(maxT)-x(minT))}" height="${Hh-top-bot}"/><rect id="history-brush" class="history-brush" hidden y="${top}" height="${Hh-top-bot}"/>`;}
      function showTip(event,key){const items=allSeries()[key]||[]; const svg=$('history-chart'), pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); const [minT,maxT]=domain(allSeries()); const ts=minT+(loc.x-56)/(960-56-18)*(maxT-minT); let nearest=items[0], best=Infinity; for(const item of items){const d=Math.abs(item.t-ts); if(d<best){best=d; nearest=item;}} if(!nearest)return; const tip=$('history-tooltip'), rect=svg.getBoundingClientRect(), wrap=svg.parentElement.getBoundingClientRect(); tip.innerHTML=`<b style="color:${colors[key]}">${key} · ${fmtDate(nearest.t)}</b><br><span>${Math.round(nearest.power_w||0)} W (${((nearest.power_w||0)/1000).toFixed(2)} kW)</span>`; tip.style.left=(event.clientX-wrap.left)+'px'; tip.style.top=(event.clientY-wrap.top)+'px'; tip.hidden=false;}
      function hideTip(){ $('history-tooltip').hidden=true; }
      async function loadHistory(win=H.window){H.window=win; H.zoom=null; $('history-title').textContent=({'day':'Dag','month':'Maand','year':'Jaar'}[win])+' overzicht · kW'; $('history-range').textContent='Laden…'; const res=await fetch(`/api/dashboard/curves?window=${win}`); H.data=res.ok?await res.json():{series:{}}; draw();}
      document.querySelectorAll('[data-history-window]').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('[data-history-window]').forEach(b=>{b.classList.toggle('active',b===btn); b.setAttribute('aria-selected',b===btn?'true':'false')}); loadHistory(btn.dataset.historyWindow);}));
      document.querySelectorAll('[data-history-series]').forEach(btn=>btn.addEventListener('click',()=>{const k=btn.dataset.historySeries; H.visible[k]=!H.visible[k]; btn.setAttribute('aria-pressed',H.visible[k]?'true':'false'); draw();}));
      $('history-mini').addEventListener('pointerdown',e=>{const r=e.currentTarget.getBoundingClientRect(); H.dragging={start:e.clientX-r.left, end:e.clientX-r.left}; e.currentTarget.setPointerCapture(e.pointerId);});
      $('history-mini').addEventListener('pointermove',e=>{if(!H.dragging)return; const r=e.currentTarget.getBoundingClientRect(), brush=$('history-brush'); H.dragging.end=e.clientX-r.left; brush.hidden=false; brush.setAttribute('x',Math.min(H.dragging.start,H.dragging.end)/r.width*960); brush.setAttribute('width',Math.abs(H.dragging.end-H.dragging.start)/r.width*960);});
      $('history-mini').addEventListener('pointerup',e=>{if(!H.dragging)return; const r=e.currentTarget.getBoundingClientRect(), all=Object.values(allSeries()).flat(); const fullMin=Math.min(...all.map(p=>p.t)), fullMax=Math.max(...all.map(p=>p.t)); const a=Math.min(H.dragging.start,H.dragging.end)/r.width, b=Math.max(H.dragging.start,H.dragging.end)/r.width; H.dragging=null; if(b-a>.03)H.zoom=[fullMin+a*(fullMax-fullMin),fullMin+b*(fullMax-fullMin)]; draw();});
      $('history-chart').addEventListener('dblclick',()=>{H.zoom=null; draw();}); $('history-mini').addEventListener('dblclick',()=>{H.zoom=null; draw();});
      loadHistory('day');
    </script>
    """



def trade_body() -> str:
    return """
    <section class='card'>
      <span class='kicker'>Minyad-trade</span>
      <h1 class='page-title'>ENTSO-E day-ahead prices</h1>
      <p class='page-copy'>Live dashboard for the <code>minyad-trade</code> collector. It reads the retained ENTSO-E/EPEX day-ahead price payload and graphs hourly EUR/kWh values.</p>
      <div class='history-chart-card'>
        <div class='history-toolbar'>
          <div><span class='tile-name'>ENTSO-E day-ahead · EUR/kWh</span><div class='history-hint' id='trade-range'>Loading…</div></div>
          <button class='secondary' type='button' onclick='loadTradePrices()'>Refresh</button>
        </div>
        <div class='chart-wrap'>
          <svg id='trade-chart' class='history-chart' viewBox='0 0 960 420' role='img' aria-label='ENTSO-E day-ahead electricity price curve'></svg>
          <div id='trade-tooltip' class='history-tooltip' hidden></div>
        </div>
        <div class='history-stats'>
          <div class='history-stat'><b id='trade-min'>--</b><span>lowest EUR/kWh</span></div>
          <div class='history-stat'><b id='trade-avg'>--</b><span>average EUR/kWh</span></div>
          <div class='history-stat'><b id='trade-max'>--</b><span>highest EUR/kWh</span></div>
          <div class='history-stat'><b id='trade-count'>--</b><span>hourly points</span></div>
        </div>
      </div>
      <pre id='trade-json'></pre>
    </section>
    <script>
      const $=id=>document.getElementById(id); let tradePoints=[];
      function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
      function fmtTime(iso){return new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});}
      function drawTradeChart(){const svg=$('trade-chart'), W=960,H=420,left=64,right=20,top=28,bot=48; if(!tradePoints.length){svg.innerHTML='<foreignObject width="960" height="420"><div class="history-empty">No retained ENTSO-E prices are available yet. Check minyad-trade and ENTSOE_API_KEY.</div></foreignObject>'; return;} const min=Math.min(...tradePoints.map(p=>p.price_eur_kwh)), max=Math.max(...tradePoints.map(p=>p.price_eur_kwh)), pad=Math.max(.01,(max-min)*.15), lo=min-pad, hi=max+pad; const first=new Date(tradePoints[0].starts_at).getTime(), last=new Date(tradePoints[tradePoints.length-1].starts_at).getTime(); const x=p=>left+(W-left-right)*(new Date(p.starts_at).getTime()-first)/(last-first||1), y=v=>top+(H-top-bot)*(1-(v-lo)/(hi-lo||1)); let out=''; for(let i=0;i<=4;i++){const v=lo+i*(hi-lo)/4, yy=y(v); out+=`<line class="gridline" x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}"/><text x="10" y="${yy+4}" fill="var(--steel)" font-family="var(--mono)" font-size="10">${v.toFixed(3)}</text>`;} for(const p of tradePoints.filter((_,i)=>i%3===0)){out+=`<text x="${x(p)}" y="${H-14}" fill="var(--steel)" font-family="var(--mono)" font-size="10" text-anchor="middle">${fmtTime(p.starts_at)}</text>`;} const d=tradePoints.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)} ${y(p.price_eur_kwh).toFixed(1)}`).join(' '); out+=`<path class="forecast-line" d="${d}"/><path class="chart-hover" d="${d}" onmousemove="showTradeTip(event)" onmouseleave="$('trade-tooltip').hidden=true"/>`; svg.innerHTML=out;}
      function showTradeTip(event){const svg=$('trade-chart'), pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); let nearest=tradePoints[0], best=Infinity; for(const p of tradePoints){const dx=Math.abs(loc.x-(64+(960-64-20)*(new Date(p.starts_at)-new Date(tradePoints[0].starts_at))/(new Date(tradePoints.at(-1).starts_at)-new Date(tradePoints[0].starts_at)||1))); if(dx<best){best=dx; nearest=p;}} const tip=$('trade-tooltip'), wrap=svg.parentElement.getBoundingClientRect(); tip.innerHTML=`<b>ENTSO-E · ${fmtTime(nearest.starts_at)}</b><span>${nearest.price_eur_kwh.toFixed(4)} EUR/kWh</span>`; tip.style.left=(event.clientX-wrap.left)+'px'; tip.style.top=(event.clientY-wrap.top)+'px'; tip.hidden=false;}
      async function loadTradePrices(){const res=await fetch('/api/trade/prices'); const data=res.ok?await res.json():{prices:[]}; tradePoints=(data.prices||[]).filter(p=>Number.isFinite(Number(p.price_eur_kwh))).map(p=>({...p,price_eur_kwh:Number(p.price_eur_kwh)})); $('trade-range').textContent=tradePoints.length?`${data.date||tradePoints[0].date} · ${tradePoints.length} hourly prices from ${data.source||'ENTSO-E'}`:'No retained data'; const vals=tradePoints.map(p=>p.price_eur_kwh); $('trade-min').textContent=vals.length?Math.min(...vals).toFixed(4):'--'; $('trade-max').textContent=vals.length?Math.max(...vals).toFixed(4):'--'; $('trade-avg').textContent=vals.length?(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(4):'--'; $('trade-count').textContent=String(tradePoints.length||'--'); $('trade-json').textContent=JSON.stringify(data,null,2); drawTradeChart();}
      loadTradePrices(); setInterval(loadTradePrices,300000);
    </script>
    """


def reporting_body() -> str:
    return """
    <section class='card'>
      <span class='kicker'>Reporting</span>
      <h1 class='page-title'>Control decisions</h1>
      <p class='page-copy'>A paginated audit trail of battery control decisions and setpoint writes.</p>
      <div class='report-toolbar'>
        <span class='history-hint' id='report-range'>Loading…</span>
        <div class='report-actions'>
          <button type='button' id='report-prev'>Previous 50</button>
          <button type='button' id='report-next'>Next 50</button>
          <button type='button' id='report-refresh'>Refresh</button>
        </div>
      </div>
      <div class='report-table-wrap'>
        <table class='report-table'>
          <thead>
            <tr>
              <th>Time</th><th>Source</th><th>Action</th><th>Setpoint</th>
              <th>Delta</th><th>SoC</th><th>Grid</th><th>Battery</th>
              <th>Limits</th><th>Ack</th><th>Reason</th>
            </tr>
          </thead>
          <tbody id='report-rows'><tr><td colspan='11' class='report-empty'>Loading decisions…</td></tr></tbody>
        </table>
      </div>
    </section>
    <script>
      const reportPageSize=50; let reportOffset=0, reportTotal=0;
      const $=id=>document.getElementById(id);
      const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const fmtTime=value=>value?new Date(value).toLocaleString([], {weekday:'short', hour:'2-digit', minute:'2-digit', second:'2-digit', day:'2-digit', month:'short'}):'--';
      const fmtW=value=>value===null||value===undefined?'--':`${Number(value).toLocaleString()} W`;
      const fmtPct=value=>value===null||value===undefined?'--':`${Number(value).toFixed(0)}%`;
      function renderReport(payload){
        reportTotal=payload.total||0;
        const items=payload.items||[], body=$('report-rows');
        if(!items.length){
          body.innerHTML='<tr><td colspan="11" class="report-empty">No control decisions recorded yet.</td></tr>';
        }else{
          body.innerHTML=items.map(row=>`<tr>
            <td>${fmtTime(row.timestamp)}</td>
            <td>${esc(row.source)}</td>
            <td><span class="report-action ${esc(row.action)}">${esc(row.action)}</span></td>
            <td>${fmtW(row.setpoint_w)}</td>
            <td>${fmtW(row.setpoint_delta)}</td>
            <td>${fmtPct(row.battery_soc_at_time)}</td>
            <td>${fmtW(row.grid_power_at_time)}</td>
            <td>${fmtW(row.battery_power_at_time)}</td>
            <td>${esc(row.soc_floor)}-${esc(row.soc_ceiling)}%</td>
            <td>${row.ack_received?'yes':'no'}${row.ack_latency_ms!=null?` · ${esc(row.ack_latency_ms)} ms`:''}</td>
            <td class="report-reason">${esc(row.trigger_reason)}</td>
          </tr>`).join('');
        }
        const start=reportTotal?reportOffset+1:0, end=Math.min(reportOffset+items.length, reportTotal);
        $('report-range').textContent=`Showing ${start}-${end} of ${reportTotal} decisions`;
        $('report-prev').disabled=reportOffset<=0;
        $('report-next').disabled=reportOffset+reportPageSize>=reportTotal;
      }
      async function loadReport(offset=reportOffset){
        reportOffset=Math.max(0,offset);
        $('report-range').textContent='Loading…';
        try{
          const res=await fetch(`/api/reporting/decisions?limit=${reportPageSize}&offset=${reportOffset}`);
          if(!res.ok) throw new Error(`Reporting request failed (${res.status})`);
          renderReport(await res.json());
        }catch(err){
          $('report-rows').innerHTML=`<tr><td colspan="11" class="report-empty error">${esc(err.message||'Unable to load reporting data')}</td></tr>`;
          $('report-range').textContent='Unable to load decisions';
        }
      }
      $('report-prev').addEventListener('click',()=>loadReport(reportOffset-reportPageSize));
      $('report-next').addEventListener('click',()=>loadReport(reportOffset+reportPageSize));
      $('report-refresh').addEventListener('click',()=>loadReport(reportOffset));
      loadReport(0);
    </script>
    """

def icon(name: str) -> str:
    shapes = {
        'solar': '<rect x="4" y="7" width="12" height="9"/><path d="M4 10h12M8 7v9M12 7v9M10 16v4M7 20h6"/><circle cx="21" cy="6" r="2"/><path d="M21 1v2M21 9v2M16 6h2M24 6h2"/>',
        'battery': '<rect x="3" y="8" width="17" height="9" rx="2"/><path d="M20 11h2v3M7 11v3M11 11v3M15 11v3"/>',
        'grid': '<path d="M12 3v18M6 21h12M7 8h10M5 14h14M8 8l-3 13M16 8l3 13"/>',
    }
    return f'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{shapes[name]}</svg>'


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_proxy(path: str, request: Request) -> Response:
    """Forward browser API calls to the API service without hiding failures."""
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "x-api-key"}
    }
    if MINYAD_API_SECRET:
        headers["X-API-Key"] = MINYAD_API_SECRET
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
            body = await request.body()
            response = await client.request(
                request.method,
                f"/api/{path}",
                params=request.query_params,
                content=body,
                headers=headers,
            )
            if response.status_code == 404:
                response = await client.request(
                    request.method,
                    f"/{path}",
                    params=request.query_params,
                    content=body,
                    headers=headers,
                )
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "detail": "Unable to reach Minyad API service",
                "api_base_url": API_BASE_URL,
                "error": str(exc),
            },
        )

    excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in excluded_headers
    }
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return render_dashboard_page()


@app.get("/reporting", response_class=HTMLResponse)
async def reporting() -> str:
    return render_page("Reporting", reporting_body())


@app.get("/{section}", response_class=HTMLResponse)
async def section(section: str) -> str:
    title = "DSMR" if section.lower() == "dsmr" else section.replace("-", " ").title()
    if title not in MENU:
        title = "Dashboard"
    if title == "Settings":
        return render_page(title, battery_settings_body())
    if title == "Agent":
        return render_page(title, agent_body())
    if title == "Health":
        return render_page(title, health_body())
    if title == "Battery":
        return render_page(title, battery_control_body())
    if title == "Asset Steering":
        return render_page(title, asset_steering_body())
    if title == "DSMR":
        return render_page(title, dsmr_body())
    if title == "History":
        return render_page(title, history_body())
    if title == "Trade":
        return render_page(title, trade_body())
    if title == "Solar":
        return render_page(title, solar_body())
    if title == "Reporting":
        return render_page(title, reporting_body())
    content = f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
