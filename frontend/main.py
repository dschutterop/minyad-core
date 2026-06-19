"""Minyad web frontend."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

app = FastAPI(title="Minyad Frontend")
API_BASE_URL = os.getenv("API_BASE_URL", "http://minyad-api:8000")

MENU = ["Dashboard", "Solar", "Battery", "DSMR", "Asset Steering", "Reporting", "Settings"]

BRAND_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root{--paper:#EDF1F4;--paper-2:#E2E8ED;--ink:#15202A;--steel:#4A6276;--hair:rgba(21,32,42,.09);--panel:#0E151C;--panel-2:#15202B;--panel-3:#1D2A37;--p-ink:#E6EDF2;--p-mut:rgba(230,237,242,.55);--p-line:rgba(150,182,208,.13);--produce:#2E9C62;--store:#D89B2A;--import:#CE4940;--produce-d:#46C684;--store-d:#F0B441;--import-d:#F26A60;--mono:"IBM Plex Mono",ui-monospace,monospace;--sans:"Space Grotesk",ui-sans-serif,system-ui,sans-serif;--ease:cubic-bezier(.2,.7,.3,1)}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;min-height:100vh;background:var(--paper);color:var(--ink);font-family:var(--sans);letter-spacing:-.01em}a{color:inherit}.brand-shell{min-height:100vh;padding:38px clamp(16px,6vw,64px) 56px}.brand-header{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:36px}.brand-lockup{display:flex;align-items:center;gap:14px;text-decoration:none}.mark{width:30px;height:30px;overflow:visible}.mark line{stroke:var(--steel);stroke-width:1.5;stroke-linecap:round}.mark circle{fill:var(--paper);stroke:var(--steel);stroke-width:1.5}.wordmark{display:grid;gap:4px}.wordmark strong{font-size:24px;line-height:1;font-weight:700;letter-spacing:-.04em}.wordmark span,.brand-nav a,.label,.kicker,.status-pill,.scale-label,.tile-name,.window-tab,.chart-legend,.unit,.value{font-family:var(--mono);font-feature-settings:"tnum";font-variant-numeric:tabular-nums}.wordmark span{font-size:9px;color:var(--steel);letter-spacing:.32em;text-transform:uppercase}.brand-nav{display:flex;gap:18px;flex-wrap:wrap}.brand-nav a{text-decoration:none;color:var(--steel);font-size:11px;letter-spacing:.18em;text-transform:uppercase}.brand-nav a.active{color:var(--ink)}.brand-main{max-width:1180px;margin:auto}.card{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}.kicker{display:flex;align-items:center;gap:16px;color:var(--steel);font-size:11px;letter-spacing:.34em;text-transform:uppercase}.kicker:after{content:"";height:1px;width:86px;background:rgba(74,98,118,.22)}.page-title{font-size:clamp(42px,7vw,72px);line-height:.95;margin:22px 0 22px;letter-spacing:-.065em}.page-copy{max-width:800px;color:rgba(21,32,42,.68);font-size:20px;line-height:1.55}.instrument{background:var(--panel);color:var(--p-ink);border:1px solid rgba(150,182,208,.18);border-radius:18px;box-shadow:0 26px 70px rgba(14,21,28,.18);overflow:hidden}.dashboard-page{margin:0;min-height:100vh;background:var(--panel)}.dashboard-full{min-height:100vh;border:0;border-radius:0;box-shadow:none}.dashboard-nav{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 24px;border-bottom:1px solid var(--p-line);background:var(--panel)}.dashboard-nav .brand-nav a{color:var(--p-mut)}.dashboard-nav .brand-nav a.active{color:var(--p-ink)}.dashboard-nav .wordmark strong{color:var(--p-ink)}.dashboard-nav .wordmark span{color:var(--p-mut)}.dashboard-nav .mark circle{fill:var(--panel)}.dashboard-full .views{padding-bottom:32px}.dashboard-full .flow-board{height:calc(100vh - 220px);min-height:560px}.window-bar{height:62px;border-bottom:1px solid var(--p-line);display:flex;align-items:center;justify-content:space-between;padding:0 20px}.traffic{display:flex;gap:10px}.traffic i{width:10px;height:10px;border-radius:50%;background:#304455}.traffic i:nth-child(1){background:var(--import-d)}.traffic i:nth-child(2){background:var(--store-d)}.traffic i:nth-child(3){background:var(--produce-d)}.window-tab{background:#0A1016;border:1px solid var(--p-line);border-radius:7px;color:var(--p-mut);font-size:11px;letter-spacing:.08em;padding:9px 14px}.layout-toggle{display:flex;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;padding:4px}.layout-toggle button{margin:0;border:0;background:transparent;color:var(--p-mut);font:600 11px/1 var(--mono);letter-spacing:.1em;padding:9px 13px;border-radius:6px;cursor:pointer}.layout-toggle button.active{background:var(--panel-3);color:var(--p-ink)}.window-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;margin-left:auto}.dash-head{display:flex;justify-content:flex-end;gap:18px;align-items:start;padding:28px 28px 10px}.dash-title{display:flex;gap:14px;align-items:center}.dash-title .mark circle{fill:var(--panel)}.dash-title strong{font-size:22px}.dash-meta{text-align:right;color:var(--p-mut);font-family:var(--mono);font-size:13px;line-height:1.7;font-feature-settings:"tnum"}.self{color:var(--produce-d)}.views{position:relative;padding:0 26px 28px}.view{display:none;animation:fade .24s var(--ease)}.view.active{display:block}@keyframes fade{from{opacity:.25}to{opacity:1}}.tile-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.tile{background:var(--panel-2);border:1px solid var(--p-line);border-left:3px solid var(--steel);border-radius:11px;padding:18px;min-width:0}.tile.produce{border-left-color:var(--produce-d)}.tile.store{border-left-color:var(--store-d)}.tile.import{border-left-color:var(--import-d)}.tile.household{border-left-color:var(--p-ink)}.tile-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.tile-name{font-size:12px;text-transform:uppercase;letter-spacing:.16em;color:var(--p-mut);display:flex;align-items:center;gap:8px}.icon{width:22px;height:22px;fill:none;stroke:var(--steel);stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.phrase{font-family:var(--mono);font-feature-settings:"tnum";font-size:clamp(34px,5vw,54px);line-height:1;color:var(--p-ink);letter-spacing:-.04em;transition:color .24s var(--ease)}.phrase .unit{font-size:.55em;color:currentColor;letter-spacing:0}.produce-c{color:var(--produce-d)}.store-c{color:var(--store-d)}.import-c{color:var(--import-d)}.steel-c{color:var(--p-mut)}.bar{position:relative;height:8px;margin:20px 0 8px;border:1px solid var(--p-line);border-radius:999px;background:#0A1016;overflow:hidden}.bar .fill{position:absolute;top:0;bottom:0;width:0;background:var(--steel);transition:width .24s var(--ease),left .24s var(--ease),right .24s var(--ease)}.bar.center:after{content:"";position:absolute;left:50%;top:-5px;bottom:-5px;width:1px;background:rgba(230,237,242,.38)}.scale{display:flex;justify-content:space-between;gap:8px}.scale-label{font-size:10px;color:var(--p-mut);white-space:nowrap}.status-pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--p-line);border-radius:999px;padding:6px 9px;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--p-mut)}.status-pill i{width:7px;height:7px;border-radius:50%;background:currentColor}.soc{margin-top:18px}.cells{display:grid;grid-template-columns:repeat(10,1fr);gap:4px;margin:8px 0}.cells i{height:18px;border:1px solid var(--p-line);border-radius:3px;background:#0A1016}.cells i.on{background:var(--store-d);border-color:rgba(240,180,65,.5)}.thin{height:5px;background:#0A1016;border:1px solid var(--p-line);border-radius:999px;overflow:hidden}.thin i{display:block;height:100%;background:var(--produce-d)}.chart-card{margin-top:14px;background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:18px}.chart-top,.daystrip{display:flex;justify-content:space-between;gap:16px;align-items:center}.chart-legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--p-mut);font-size:11px}.chart-legend i{display:inline-block;width:18px;height:2px;margin-right:5px;vertical-align:middle;background:currentColor}.chart{width:100%;height:300px;margin-top:10px}.sparkline{width:100%;height:54px;margin-top:12px}.sparkline path{fill:none;stroke:var(--p-ink);stroke-width:2}.load-meta{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.badge.warn{border-color:rgba(240,180,65,.5);color:var(--store-d)}.axis,.gridline{stroke:var(--p-line);stroke-width:1}.zero-line{stroke:rgba(230,237,242,.38);stroke-width:1.4}.forecast-fill{fill:rgba(74,98,118,.18)}.forecast-line{fill:none;stroke:rgba(150,182,208,.48);stroke-width:2;stroke-dasharray:6 6}.prod-line{fill:none;stroke:var(--produce-d);stroke-width:2.6}.prod-fill{fill:rgba(70,198,132,.12)}.bat-line{fill:none;stroke:var(--store-d);stroke-width:2}.bat-charge-fill{fill:rgba(240,180,65,.14)}.bat-discharge-fill{fill:rgba(216,155,42,.18)}.grid-line{fill:none;stroke:var(--import-d);stroke-width:2}.grid-import-fill{fill:rgba(242,106,96,.16)}.grid-export-fill{fill:rgba(70,198,132,.14)}.imp-fill{fill:rgba(242,106,96,.16)}.exp-fill{fill:rgba(70,198,132,.14)}.now{stroke:var(--p-ink);stroke-width:1;stroke-dasharray:3 5}.daystrip{margin-top:14px;border-top:1px solid var(--p-line);padding-top:14px}.daystrip div{min-width:0}.daystrip b{display:block;font-family:var(--mono);font-feature-settings:"tnum";font-size:22px}.daystrip span{font-family:var(--mono);font-size:10px;color:var(--p-mut);letter-spacing:.1em;text-transform:uppercase}.flow-board{height:560px;position:relative;background:radial-gradient(circle at 50% 43%,rgba(29,42,55,.8),transparent 34%);border:1px solid var(--p-line);border-radius:12px;margin-top:14px}.flow-svg{position:absolute;inset:0;width:100%;height:100%}.flow-line{fill:none;stroke-width:4;stroke-linecap:round;opacity:.8}.flow-dot{animation:drift 2s linear infinite}@keyframes drift{to{offset-distance:100%}}.flow-node{position:absolute;transform:translate(-50%,-50%);background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;padding:14px;width:170px;text-align:center}.flow-node.solar{left:50%;top:18%}.flow-node.home{left:50%;top:48%;border-color:rgba(230,237,242,.3)}.flow-node.battery{left:25%;top:78%}.flow-node.grid{left:75%;top:78%}.flow-node .phrase{font-size:26px}.mobile-readout{display:none}.mobile-rows{display:grid;gap:10px}.mobile-row{display:flex;justify-content:space-between;border-top:1px solid var(--p-line);padding-top:10px}.status-card,.overview-card,.panel,.flow-panel{background:rgba(237,241,244,.72);border:1px solid rgba(74,98,118,.22);border-radius:14px;padding:24px}input{width:100%;margin-top:8px;border:1px solid rgba(74,98,118,.25);background:#fff;padding:11px 12px;font:inherit;color:var(--ink)}button{font-family:var(--mono)}pre{background:#111827;color:#eef2f7;padding:16px;overflow:auto}.grid,.metric-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:var(--hair);border:1px solid var(--hair)}.grid>*{background:var(--paper);padding:14px}.error{color:var(--import)}@media(max-width:1100px){.tile-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:860px){.dashboard-nav{align-items:flex-start;flex-direction:column;padding:14px}.brand-shell{padding:18px 12px}.brand-header{align-items:flex-start;flex-direction:column}.instrument{border-radius:14px}.dash-head,.window-bar{padding-left:14px;padding-right:14px}.tile-grid{grid-template-columns:1fr}.chart{height:220px}.daystrip{display:grid;grid-template-columns:repeat(2,1fr)}.desktop-only{display:none}.mobile-readout{display:block;padding:0 14px 18px}.flow-board{height:520px}.dashboard-full .flow-board{height:520px;min-height:520px}.flow-node{width:140px}.flow-node.battery{left:22%}.flow-node.grid{left:78%}}@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;transition-duration:.001ms!important;scroll-behavior:auto!important}.flow-dot{display:none}}
"""

BRAND_CSS += """
.mailbox-button{position:relative;border:1px solid var(--p-line);background:#0A1016;color:var(--p-ink);border-radius:9px;padding:9px 12px;cursor:pointer;font:600 16px/1 var(--mono)}
.mailbox-button .badge{position:absolute;right:-7px;top:-7px;min-width:18px;height:18px;border-radius:999px;background:var(--import-d);color:#fff;border:1px solid rgba(255,255,255,.25);font:700 10px/17px var(--mono);text-align:center;padding:0 4px}
.mailbox-button .badge[hidden],.mailbox-panel[hidden],.message-detail[hidden]{display:none}
.mailbox-panel{position:absolute;right:26px;top:132px;z-index:20;width:min(460px,calc(100vw - 32px));max-height:70vh;overflow:auto;background:var(--panel-2);border:1px solid var(--p-line);border-radius:12px;box-shadow:0 28px 80px rgba(0,0,0,.35);padding:14px}
.mailbox-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.mailbox-list{display:grid;gap:8px}
.mailbox-item{width:100%;text-align:left;background:#0A1016;border:1px solid var(--p-line);border-radius:9px;color:var(--p-ink);padding:10px;cursor:pointer}
.mailbox-item.unread{border-color:rgba(230,237,242,.34);font-weight:700}
.mailbox-item small{display:block;color:var(--p-mut);font:500 10px/1.5 var(--mono);letter-spacing:.08em;text-transform:uppercase}
.severity-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:var(--p-mut)}
.severity-dot.high{background:var(--import-d)}.severity-dot.normal{background:var(--store-d)}.severity-dot.low{background:var(--steel)}
.message-detail{margin-top:10px;border-top:1px solid var(--p-line);padding-top:10px;color:var(--p-ink)}
.message-detail p{white-space:pre-wrap;color:var(--p-mut);line-height:1.45}
.reply-box textarea{width:100%;min-height:82px;margin-top:8px;border:1px solid var(--p-line);border-radius:8px;background:#0A1016;color:var(--p-ink);padding:10px;font:inherit}
.reply-box button,.mailbox-head button{border:1px solid var(--p-line);background:#0A1016;color:var(--p-ink);border-radius:8px;padding:8px 10px;cursor:pointer}
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
      </head>
      <body>
        <div class="brand-shell">
          <header class="brand-header">
            <a class="brand-lockup" href="/" aria-label="Minyad dashboard">
              {brand_mark()}
              <span class="wordmark"><strong>Minyad</strong><span>Brand Interface</span></span>
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
      </head>
      <body class="dashboard-page">
        {energy_dashboard_body()}
      </body>
    </html>
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


def battery_settings_body() -> str:
    return """
    <div class='card'><h2>Battery control</h2><p>Effective values from /battery/settings.</p>
      <form id='battery-settings' class='grid'>
        <label>Start surplus W <input name='start_w' type='number' min='100' max='5000'></label>
        <label>Stop surplus W <input name='stop_w' type='number' min='0'></label>
        <label>Start duration s <input name='start_duration' type='number' min='10' max='3600'></label>
        <label>Stop duration s <input name='stop_duration' type='number' min='10' max='3600'></label>
        <label>Cooldown s <input name='cooldown' type='number' min='60' max='7200'></label>
        <label>Max charge W <input name='max_charge_w' type='number' min='100' max='5000'></label>
        <label>Max discharge W <input name='max_discharge_w' type='number' min='0' max='5000'></label>
        <label>Inverter IP <input name='inverter_ip' type='text' pattern='^([0-9]{1,3}\\.){3}[0-9]{1,3}$'></label>
        <label>Retries <input name='inverter_retries' type='number' min='1' max='10'></label>
        <label>Retry delay s <input name='inverter_delay' type='number' min='1' max='30'></label>
        <button type='submit'>Save battery settings</button>
      </form><pre id='settings-result'></pre></div>

    <div class='card'>
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
    </div>

    <script>
      async function loadBatterySettings(){
        const res = await fetch('/api/battery/settings'); const data = await res.json();
        for (const [k,v] of Object.entries(data)){ const el = document.querySelector(`[name="${k}"]`); if(el) el.value = v; }
        document.getElementById('settings-result').textContent = JSON.stringify(data, null, 2);
      }
      document.getElementById('battery-settings').addEventListener('submit', async (event)=>{
        event.preventDefault(); const data = {};
        new FormData(event.target).forEach((v,k)=>{ data[k] = k === 'inverter_ip' ? v : Number(v); });
        const res = await fetch('/api/battery/settings',{method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
        document.getElementById('settings-result').textContent = JSON.stringify(await res.json(), null, 2);
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
        applyDebugState(data.debug_logging);
      }

      loadBatterySettings();
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
      function forceCharge(){ const watts = Number(prompt('Charge watts?')); if(watts) sendOverride({mode:'force_on', watts}); }
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
      <div class="dashboard-nav"><a class="brand-lockup" href="/" aria-label="Minyad dashboard">__MARK__<span class="wordmark"><strong>Minyad</strong><span>Brand Interface</span></span></a><nav class="brand-nav" aria-label="Primary navigation">__NAV__</nav></div>
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
        <div id="mailbox-list" class="mailbox-list"><span class="scale-label">Loading…</span></div>
        <div id="message-detail" class="message-detail" hidden></div>
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
              <div class="tile-head"><span class="tile-name">__SOLAR__ Solar</span><span class="status-pill produce-c"><i></i><span id="solar-status">Producing</span></span></div>
              <div class="phrase produce-c"><span id="solar-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar"><span id="solar-bar" class="fill" style="background:var(--produce-d)"></span></div><div class="scale"><span class="scale-label">0</span><span class="scale-label">~5 kWp peak</span></div>
            </article>
            <article class="tile store" aria-label="Battery live tile">
              <div class="tile-head"><span class="tile-name">__BATTERY__ Battery</span><span class="status-pill store-c"><i></i><span id="battery-status-word">Standby</span></span></div>
              <div class="phrase store-c"><span id="battery-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar center"><span id="battery-bar" class="fill" style="background:var(--store-d);left:50%"></span></div><div class="scale"><span class="scale-label scale-power" data-kw="−3 charge" data-w="−3000 charge">−3 charge</span><span class="scale-label scale-power" data-kw="discharge +3" data-w="discharge +3000">discharge +3</span></div>
              <div class="soc"><div class="scale"><span class="scale-label">SoC</span><span class="scale-label"><span id="soc-text">--</span></span></div><div class="cells" id="soc-cells"></div><div class="scale"><span class="scale-label">SoH</span><span class="scale-label"><span id="soh-text">98% · 9.8 / 10 kWh</span></span></div><div class="thin"><i id="soh-bar" style="width:98%"></i></div></div>
            </article>
            <article class="tile import" id="grid-tile" aria-label="Grid live tile">
              <div class="tile-head"><span class="tile-name">__GRID__ Grid</span><span class="status-pill" id="grid-pill"><i></i><span id="grid-status-word">Importing</span></span></div>
              <div class="phrase" id="grid-phrase"><span id="grid-value">--</span> <span class="unit power-unit">kW</span></div>
              <div class="bar center"><span id="grid-bar" class="fill" style="left:50%"></span></div><div class="scale"><span class="scale-label scale-power" data-kw="−3 import" data-w="−3000 import">−3 import</span><span class="scale-label scale-power" data-kw="export +3" data-w="export +3000">export +3</span></div>
            </article>
            <article class="tile household" aria-label="Household load live tile">
              <div class="tile-head"><span class="tile-name">Home Consumption</span><span class="status-pill" id="household-pill"><i></i><span id="household-status-word">Live</span></span></div>
              <div class="phrase"><span id="household-value">--</span> <span class="unit power-unit">kW</span></div>
              <svg id="household-spark" class="sparkline" viewBox="0 0 240 54" role="img" aria-label="Household load for the last hour"></svg>
              <div class="load-meta"><span class="scale-label"><span id="household-kwh">--</span> kWh today</span><span class="status-pill badge" id="household-badge" hidden>⚠ mismatch</span></div>
            </article>
          </div>
          <div class="chart-card desktop-only"><div class="chart-top"><span class="tile-name">Combined day graph · kW</span><div class="chart-legend"><span style="color:var(--steel)"><i></i>Forecast</span><span style="color:var(--produce-d)"><i></i>Production</span><span style="color:var(--store-d)"><i></i>Battery</span><span style="color:var(--import-d)"><i></i>Grid</span></div></div><svg id="day-chart" class="chart" viewBox="0 0 960 300" role="img" aria-label="Forecast, production, battery and grid series for today"></svg><div class="daystrip"><div><b class="produce-c" id="kwh-produced">--</b><span>kWh produced</span></div><div><b id="kwh-used">--</b><span>kWh self used</span></div><div><b class="produce-c" id="kwh-exported">--</b><span>kWh exported</span></div><div><b class="import-c" id="kwh-imported">--</b><span>kWh imported</span></div></div></div>
        </div>
        <div id="flow-view" class="view"><div class="flow-board"><svg class="flow-svg" viewBox="0 0 1000 560" aria-hidden="true"><path id="flow-solar-home" class="flow-line" d="M500 135 L500 245"/><path id="flow-home-battery" class="flow-line" d="M450 290 L260 420"/><path id="flow-home-grid" class="flow-line" d="M550 290 L740 420"/></svg><div class="flow-node solar"><span class="tile-name">Solar</span><div class="phrase produce-c"><span id="f-solar">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node home"><span class="tile-name">Home</span><div class="phrase"><span id="f-home">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node battery"><span class="tile-name">Battery</span><div class="phrase store-c"><span id="f-battery">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node grid"><span class="tile-name">Grid</span><div class="phrase" id="f-grid-phrase"><span id="f-grid">--</span> <span class="unit power-unit">kW</span></div></div></div></div>
        <div class="mobile-readout"><div class="mobile-rows"><div class="mobile-row"><span class="tile-name">Battery</span><b class="value store-c" id="m-battery">-- kW</b></div><div class="mobile-row"><span class="tile-name">Grid</span><b class="value" id="m-grid">-- kW</b></div><div class="mobile-row"><span class="tile-name">Self-sufficiency</span><b class="value produce-c" id="m-self">--%</b></div></div></div>
      </div>
    </section>
    <script>
      const solarMax=5, signedMax=3, nominalKwh=10; let powerUnit='kw'; let last={solar:0,battery:0,grid:0,household:0,soc:82,soh:98}; let curves=null; let curvesLoadedAt=0; let mailboxMessages=[];
      const $=id=>document.getElementById(id); const n=v=>{const x=Number(v);return Number.isFinite(x)?x:null}; const fmtPower=(v,signed=false)=>{if(v==null)return '--'; const value=powerUnit==='w'?Math.round(Math.abs(v)*1000):Math.abs(v).toFixed(2); return signed?(v>0?'+':'−')+value:String(value)}; const unitLabel=()=>powerUnit==='w'?'W':'kW';
      async function refreshMailboxCount(){try{const res=await fetch('/api/messages/unread-count'); if(!res.ok)return; const data=await res.json(); const count=Number(data.unread_count||0); const badge=$('mailbox-badge'); badge.textContent=count>99?'99+':String(count); badge.hidden=count<1;}catch(e){}}
      async function loadMailbox(){const list=$('mailbox-list'); list.innerHTML='<span class="scale-label">Loading…</span>'; try{const res=await fetch('/api/messages?sender=agent&limit=30'); mailboxMessages=res.ok?await res.json():[];}catch(e){mailboxMessages=[];} if(!mailboxMessages.length){list.innerHTML='<span class="scale-label">No agent messages yet.</span>'; return;} list.innerHTML=mailboxMessages.map(m=>`<button class="mailbox-item ${m.read_at?'':'unread'}" type="button" onclick="openMessage(${m.id})"><small><span class="severity-dot ${m.severity}"></span>${m.category} · ${new Date(m.created_at).toLocaleString()}</small>${escapeHtml(m.subject)}</button>`).join('');}
      function toggleMailbox(open){const panel=$('mailbox-panel'); const shouldOpen=open===undefined?panel.hidden:open; panel.hidden=!shouldOpen; if(shouldOpen){loadMailbox(); refreshMailboxCount();}}
      function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
      async function openMessage(id){const detail=$('message-detail'); let payload=null; try{const res=await fetch(`/api/messages/${id}`); if(res.ok)payload=await res.json();}catch(e){} if(!payload)return; const m=payload.message; detail.hidden=false; detail.innerHTML=`<small class="tile-name"><span class="severity-dot ${m.severity}"></span>${m.category} · ${m.severity}</small><h3>${escapeHtml(m.subject)}</h3><p>${escapeHtml(m.body)}</p>${m.related_decision_id?`<p><span class="scale-label">Related decision #${m.related_decision_id}</span></p>`:''}<div class="reply-box"><textarea id="reply-body" placeholder="Reply to the agent…"></textarea><button type="button" onclick="sendReply(${m.thread_id||m.id})">Send reply</button></div>`; if(!m.read_at){await fetch(`/api/messages/${id}/read`,{method:'PATCH'}); refreshMailboxCount(); loadMailbox();}}
      async function sendReply(threadId){const body=$('reply-body').value.trim(); if(!body)return; await fetch('/api/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender:'operator',category:'reply',subject:'Operator reply',body,thread_id:threadId,severity:'normal'})}); $('reply-body').value='';}
      function setLayout(name){$('cluster-view').classList.toggle('active',name==='cluster');$('flow-view').classList.toggle('active',name==='flow');$('cluster-toggle').classList.toggle('active',name==='cluster');$('flow-toggle').classList.toggle('active',name==='flow')}
      function setPowerUnit(unit){powerUnit=unit; $('watts-toggle').classList.toggle('active',unit==='w'); $('kilowatts-toggle').classList.toggle('active',unit==='kw'); document.querySelectorAll('.power-unit').forEach(el=>el.textContent=unitLabel()); document.querySelectorAll('.scale-power').forEach(el=>el.textContent=el.dataset[unit]); renderReadings();}
      function renderReadings(){const home=Math.max(0,last.household||last.solar+last.battery-last.grid), gExport=last.grid>=0; $('solar-value').textContent=fmtPower(last.solar); $('m-solar').textContent=fmtPower(last.solar); $('battery-value').textContent=fmtPower(last.battery,true); $('grid-value').textContent=fmtPower(last.grid,true); $('household-value').textContent=fmtPower(home); $('f-solar').textContent=fmtPower(last.solar); $('f-battery').textContent=fmtPower(last.battery,true); $('f-grid').textContent=fmtPower(last.grid,true); $('f-home').textContent=fmtPower(home); $('m-battery').textContent=fmtPower(last.battery,true)+' '+unitLabel(); $('m-grid').textContent=fmtPower(last.grid,true)+' '+unitLabel(); $('f-grid-phrase').className='phrase '+(gExport?'produce-c':'import-c');}
      function setBar(id,v,max,color){const el=$(id); if(!el)return; const pct=Math.min(100,Math.abs(v)/max*50); el.style.background=color; if(v<0){el.style.left=(50-pct)+'%';el.style.width=pct+'%'}else{el.style.left='50%';el.style.width=pct+'%'}}
      function setSoc(soc){$('soc-text').textContent=Math.round(soc)+'%'; const c=$('soc-cells'); c.innerHTML=''; for(let i=0;i<10;i++){const cell=document.createElement('i'); if(i<Math.round(soc/10))cell.className='on'; c.appendChild(cell)}}
      async function loadCurves(){const now=Date.now(); if(curves&&now-curvesLoadedAt<60000)return curves; try{const res=await fetch('/api/dashboard/curves?window=day'); if(res.ok){curves=await res.json(); curvesLoadedAt=now;}}catch(e){} return curves;}
      function appendCurrentSolarPoint(){if(!curves)curves={series:{solar:[],battery:[],grid:[]}}; if(!curves.series)curves.series={}; const solar=curves.series.solar||(curves.series.solar=[]), ts=new Date(), minute=ts.toISOString().slice(0,16), point={timestamp:ts.toISOString(),power_w:Math.round(Math.max(0,last.solar)*1000)}; const idx=solar.findIndex(p=>String(p.timestamp||'').slice(0,16)===minute); if(idx>=0)solar[idx]=point; else solar.push(point); solar.sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function householdDayKwh(items){let total=0; for(let i=1;i<items.length;i++){const a=items[i-1],b=items[i],dt=(new Date(b.timestamp)-new Date(a.timestamp))/3600000; if(dt>0&&dt<1.1)total+=((a.power_w||0)+(b.power_w||0))/2/1000*dt;} return total;}
      function householdMismatchText(household){if(!household?.mismatch)return ''; const pct=n(household.deviation_pct), a=n(household.method_a_w), b=n(household.method_b_w); const parts=['Mismatch: de berekende Home Consumption komt niet overeen tussen de solar/battery-only check en de DSMR-netmeter check.']; if(pct!=null)parts.push(`Afwijking ${pct.toFixed(1)}%.`); if(a!=null&&b!=null)parts.push(`Zonder DSMR: ${Math.round(a)} W; met DSMR: ${Math.round(b)} W.`); parts.push('Controleer of DSMR, solar en batterijmetingen actueel zijn en dezelfde richting/eenheden gebruiken.'); return parts.join(' ');}
      function drawHouseholdSpark(items){const svg=$('household-spark'), W=240,H=54, pad=3; if(!items||items.length<2){svg.innerHTML='';return;} const now=Date.now(), recent=items.filter(p=>new Date(p.timestamp)>=now-3600000); const data=recent.length>1?recent:items.slice(-60); const max=Math.max(1000,...data.map(p=>p.power_w||0)); const min=0; const first=new Date(data[0].timestamp).getTime(), lastTs=new Date(data[data.length-1].timestamp).getTime(), span=Math.max(1,lastTs-first); const x=p=>pad+(W-pad*2)*(new Date(p.timestamp).getTime()-first)/span; const y=p=>H-pad-(H-pad*2)*((p.power_w||0)-min)/(max-min||1); svg.innerHTML=`<path d="${data.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)} ${y(p).toFixed(1)}`).join(' ')}"/>`;}
      function drawChart(){const svg=$('day-chart'), W=960,H=300, left=42,right=16,top=16,bot=28, mid=150, now=new Date(), hour=now.getHours()+now.getMinutes()/60; const x=t=>left+(W-left-right)*t/24, y=kw=>mid-kw/5*(mid-top); let out=''; for(let h=0;h<=24;h+=6)out+=`<line class="gridline" x1="${x(h)}" y1="${top}" x2="${x(h)}" y2="${H-bot}"/><text x="${x(h)}" y="${H-7}" fill="var(--p-mut)" font-family="var(--mono)" font-size="11" text-anchor="middle">${String(h).padStart(2,'0')}:00</text>`; for(let kw=-5;kw<=5;kw+=2.5)out+=`<text x="8" y="${y(kw)+4}" fill="var(--p-mut)" font-family="var(--mono)" font-size="10">${kw}</text>`; out+=`<line class="zero-line" x1="${left}" y1="${mid}" x2="${W-right}" y2="${mid}"/>`; const pts=[...Array(49)].map((_,i)=>i/2); const bell=t=>Math.max(0,Math.sin((t-6)/12*Math.PI)); const toHour=iso=>{const d=new Date(iso);return d.getHours()+d.getMinutes()/60+d.getSeconds()/3600}; const pathPoints=items=>items&&items.length?items.map((p,i)=>`${i?'L':'M'}${x(toHour(p.timestamp)).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '):''; const path=(fn)=>pts.map((t,i)=>`${i?'L':'M'}${x(t).toFixed(1)} ${y(fn(t)).toFixed(1)}`).join(' '); const area=(fn,base=0)=>`M${x(0)} ${y(base)} `+pts.map(t=>`L${x(t).toFixed(1)} ${y(fn(t)).toFixed(1)}`).join(' ')+` L${x(24)} ${y(base)} Z`; const forecastPath=pathPoints(curves?.forecast); const prodPath=pathPoints(curves?.series?.solar); const batteryItems=[...(curves?.series?.battery||[]),...(curves?.battery_forecast||[])]; const gridItems=(curves?.series?.grid||[]).map(p=>({...p,power_w:-(p.net_w??p.power_w??0)})); const batPath=pathPoints(batteryItems); const gridPath=pathPoints(gridItems); const signedArea=(items,positive,klass)=>items&&items.length?`<path class="${klass}" d="M${x(toHour(items[0].timestamp)).toFixed(1)} ${y(0)} `+items.map(p=>{const kw=(p.power_w||0)/1000; return `L${x(toHour(p.timestamp)).toFixed(1)} ${y(positive?Math.max(0,kw):Math.min(0,kw)).toFixed(1)}`}).join(' ')+` L${x(toHour(items[items.length-1].timestamp)).toFixed(1)} ${y(0)} Z"/>`:''; out+=forecastPath?`<path class="forecast-line" d="${forecastPath}"/>`:''; out+=prodPath?`<path class="prod-line" d="${prodPath}"/>`:''; out+=batPath?signedArea(batteryItems,true,'bat-charge-fill')+signedArea(batteryItems,false,'bat-discharge-fill')+`<path class="bat-line" d="${batPath}"/>`:`<path class="bat-line" d="${path(t=>1.2*Math.sin((t-15)/24*Math.PI*4))}"/>`; out+=gridPath?signedArea(gridItems,true,'grid-import-fill')+signedArea(gridItems,false,'grid-export-fill')+`<path class="grid-line" d="${gridPath}"/>`:`<path class="imp-fill" d="${area(t=>Math.min(0,1.2*Math.sin((t-12)/24*Math.PI*4)),0)}"/><path class="exp-fill" d="${area(t=>Math.max(0,1.0*Math.sin((t-10)/24*Math.PI*3)),0)}"/>`; out+=`<line class="now" x1="${x(hour)}" y1="${top}" x2="${x(hour)}" y2="${H-bot}"/><circle cx="${x(hour)}" cy="${y(last.solar)}" r="4" fill="var(--produce-d)"/><text x="${x(hour)+7}" y="${top+12}" fill="var(--p-ink)" font-family="var(--mono)" font-size="10">NOW</text>`; svg.innerHTML=out}
      async function update(){const d=new Date(); $('clock').textContent=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); $('date').textContent=d.toLocaleDateString([], {day:'2-digit',month:'short',year:'numeric'}); let battery={},grid={},household={}; try{[grid,battery,household]=await Promise.all([fetch('/api/grid/status').then(r=>r.ok?r.json():{}),fetch('/api/battery/status').then(r=>r.ok?r.json():{}),fetch('/api/household/status').then(r=>r.ok?r.json():{})])}catch(e){}
        const solarW=n(grid.solar_power_w); last.solar=solarW==null?0:solarW/1000; last.battery=(n(battery.power_w)??0)/1000; const rawGrid=(n(grid.grid_net_power_w)??650)/1000; last.grid=-rawGrid; last.household=(n(household.power_w)??Math.max(0,last.solar*1000+last.battery*1000-last.grid*1000))/1000; last.soc=n(battery.soc)??last.soc; last.soh=n(battery.soh)??98; const home=Math.max(0,last.household);
        $('household-status-word').textContent=household.approx?'Approx':'Live'; $('household-pill').className='status-pill '+(household.approx?'store-c':''); const mismatchText=householdMismatchText(household); const badge=$('household-badge'); badge.hidden=!household.mismatch; badge.className='status-pill badge '+(household.mismatch?'warn':''); badge.title=mismatchText; badge.setAttribute('aria-label', mismatchText||'Geen household mismatch');
        renderReadings(); $('solar-bar').style.width=Math.min(100,last.solar/solarMax*100)+'%'; $('solar-status').textContent=last.solar>0.05?'Producing':'Standby';
        $('battery-status-word').textContent=Math.abs(last.battery)<.03?'Standby':last.battery>0?'Discharging':'Charging'; setBar('battery-bar',last.battery,signedMax,'var(--store-d)'); setSoc(last.soc); $('soh-text').textContent=`${Math.round(last.soh)}% · ${(nominalKwh*last.soh/100).toFixed(1)} / 10 kWh`; $('soh-bar').style.width=last.soh+'%';
        const gExport=last.grid>=0; $('grid-status-word').textContent=Math.abs(last.grid)<.03?'Standby':gExport?'Exporting':'Importing'; $('grid-phrase').className='phrase '+(gExport?'produce-c':'import-c'); $('grid-pill').className='status-pill '+(gExport?'produce-c':'import-c'); $('grid-tile').className='tile '+(gExport?'produce':'import'); setBar('grid-bar',last.grid,signedMax,gExport?'var(--produce-d)':'var(--import-d)');
        $('flow-solar-home').style.stroke='var(--produce-d)'; $('flow-solar-home').style.strokeWidth=2+Math.min(10,last.solar*2); $('flow-home-battery').style.stroke='var(--store-d)'; $('flow-home-battery').style.strokeWidth=2+Math.min(10,Math.abs(last.battery)*3); $('flow-home-grid').style.stroke=gExport?'var(--produce-d)':'var(--import-d)'; $('flow-home-grid').style.strokeWidth=2+Math.min(10,Math.abs(last.grid)*3);
        const produced=last.solar*5.8, exported=Math.max(0,last.grid)*2.4, imported=Math.max(0,-last.grid)*2.2, used=Math.max(0,produced-exported); $('kwh-produced').textContent=produced.toFixed(1); $('kwh-exported').textContent=exported.toFixed(1); $('kwh-imported').textContent=imported.toFixed(1); $('kwh-used').textContent=used.toFixed(1); const self=Math.round(100*Math.max(0,used)/(used+imported||1)); $('self-top').textContent=self+'%'; $('m-self').textContent=self+'%'; await loadCurves(); appendCurrentSolarPoint(); const hItems=curves?.series?.household||[]; drawHouseholdSpark(hItems); $('household-kwh').textContent=householdDayKwh(hItems).toFixed(1); drawChart(); }
      refreshMailboxCount(); setInterval(refreshMailboxCount,45000); update(); setInterval(update,4000);
    </script>
    """.replace("__MARK__", brand_mark()).replace("__NAV__", render_nav("Dashboard")).replace("__SOLAR__", icon("solar")).replace("__BATTERY__", icon("battery")).replace("__GRID__", icon("grid"))


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
        if k.lower() not in {"host", "content-length"}
    }
    try:
        async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
            response = await client.request(
                request.method,
                f"/{path}",
                params=request.query_params,
                content=await request.body(),
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


@app.get("/{section}", response_class=HTMLResponse)
async def section(section: str) -> str:
    title = "DSMR" if section.lower() == "dsmr" else section.replace("-", " ").title()
    if title not in MENU:
        title = "Dashboard"
    if title == "Settings":
        return render_page(title, battery_settings_body())
    if title == "Battery":
        return render_page(title, battery_control_body())
    if title == "Asset Steering":
        return render_page(title, asset_steering_body())
    if title == "DSMR":
        return render_page(title, dsmr_body())
    content = f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
