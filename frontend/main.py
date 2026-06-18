"""Minyad web frontend."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Minyad Frontend")
API_BASE_URL = os.getenv("API_BASE_URL", "http://minyad-api:8000")

MENU = ["Dashboard", "Solar", "Battery", "DSMR", "Reporting", "Settings"]

BRAND_CSS = """
:root {
  color-scheme: light;
  --paper: #fbfbfa;
  --canvas: #ffffff;
  --ink: #1f2937;
  --muted: #818793;
  --quiet: #b2b7c0;
  --rule: #eceef2;
  --rule-strong: #dfe3ea;
  --blue: #1f5eff;
  --cyan: #35b8d2;
  --green: #46b37a;
  --amber: #d9a441;
  --red: #d95b5b;
  --node: #111827;
  --shadow: 0 24px 70px rgba(31, 41, 55, .07);
  --mono: "SFMono-Regular", "Roboto Mono", "Cascadia Mono", Consolas, monospace;
  --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--paper); }
body {
  margin: 0;
  min-height: 100vh;
  background:
    linear-gradient(90deg, rgba(31,41,55,.025) 1px, transparent 1px) 0 0 / 80px 80px,
    linear-gradient(180deg, rgba(31,41,55,.02) 1px, transparent 1px) 0 0 / 80px 80px,
    var(--paper);
  color: var(--ink);
  font-family: var(--sans);
  letter-spacing: .01em;
}
a { color: inherit; }
.brand-shell { min-height: 100vh; padding: 42px 7vw 56px; }
.brand-header {
  height: 66px;
  display: flex;
  align-items: center;
  gap: 26px;
  border-bottom: 1px solid var(--rule);
}
.brand-lockup { display: flex; align-items: center; gap: 14px; min-width: 168px; text-decoration: none; }
.mark { width: 25px; height: 25px; overflow: visible; }
.mark line { stroke: var(--node); stroke-width: 1.25; }
.mark circle { fill: var(--canvas); stroke: var(--node); stroke-width: 1.25; }
.wordmark { display: grid; gap: 5px; }
.wordmark strong { font-size: 22px; line-height: 1; font-weight: 760; letter-spacing: -.03em; }
.wordmark span { color: var(--blue); font-size: 7px; font-weight: 800; letter-spacing: .44em; text-transform: uppercase; }
.brand-nav { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.brand-nav a {
  color: var(--muted);
  text-decoration: none;
  font-size: 12px;
  line-height: 1;
  letter-spacing: .035em;
  transition: color .18s ease, transform .18s ease;
}
.brand-nav a.active, .brand-nav a:hover { color: var(--ink); transform: translateY(-1px); }
.brand-main { padding-top: 46px; }
.kicker { color: var(--blue); font-size: 9px; font-weight: 850; letter-spacing: .5em; text-transform: uppercase; }
.page-title { margin: 10px 0 12px; font-size: clamp(38px, 6vw, 86px); line-height: .92; letter-spacing: -.065em; font-weight: 760; }
.page-copy { max-width: 760px; margin: 0; color: var(--muted); font-size: 15px; line-height: 1.8; }
.hero { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(330px, .9fr); gap: 38px; align-items: stretch; margin-bottom: 34px; }
.overview-card { padding: 28px; }
.overview-card h1 { margin: 0 0 18px; font-size: 15px; letter-spacing: .22em; text-transform: uppercase; }
.overview-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); }
.overview-metric { min-height: 138px; background: var(--canvas); padding: 20px; display: flex; flex-direction: column; justify-content: space-between; }
.overview-metric .metric-value { font-size: clamp(34px, 5vw, 56px); }
.status-card, .card, .panel {
  background: rgba(255,255,255,.78);
  border: 1px solid var(--rule);
  box-shadow: var(--shadow);
  backdrop-filter: blur(18px);
}
.status-card { min-height: 310px; padding: 28px; position: relative; overflow: hidden; }
.status-card:after { content:""; position:absolute; inset:auto -10% -35% 18%; height: 220px; border:1px solid var(--rule-strong); border-radius: 999px 999px 0 0; opacity:.8; }
.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); }
.status-tile { background: var(--canvas); padding: 18px; min-height: 112px; }
.label { display:block; color: var(--muted); font-size: 10px; font-weight: 800; letter-spacing: .24em; text-transform: uppercase; }
.value { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.metric-value { display:block; margin-top: 18px; font-size: 31px; line-height: 1; letter-spacing: -.05em; }
.unit { color: var(--quiet); font-size: 11px; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
.dot { width: 8px; height: 8px; display: inline-block; border: 1px solid currentColor; border-radius: 50%; background: currentColor; }
.green { color: var(--green); } .amber { color: var(--amber); } .red { color: var(--red); } .grey { color: var(--quiet); } .blue { color: var(--blue); }
.dashboard-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 18px; }
.panel { padding: 24px; min-height: 390px; display: flex; flex-direction: column; gap: 22px; }
.panel-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding-bottom: 18px; border-bottom: 1px solid var(--rule); }
h1,h2,h3,p { margin-top: 0; } h2 { margin-bottom: 0; font-size: 15px; letter-spacing: .22em; text-transform: uppercase; }
.large-row { margin-top:auto; text-align:right; }
.large-value { font-family: var(--mono); font-size: clamp(42px, 7vw, 78px); line-height: .9; letter-spacing: -.08em; font-variant-numeric: tabular-nums; }
.direction { margin-top: 9px; color: var(--blue); font-size: 11px; font-weight: 850; letter-spacing: .28em; text-transform: uppercase; }
.metric-grid, .grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); }
.metric, .grid > p, .grid > label { background: var(--canvas); padding: 15px; margin: 0; min-width:0; }
.sparkline { width: 100%; height: 130px; border: 1px solid var(--rule); background: linear-gradient(180deg, #fff, #fafafa); }
.axis { stroke: var(--rule-strong); stroke-width:1; vector-effect:non-scaling-stroke; } .spark { fill:none; stroke:var(--blue); stroke-width:2; vector-effect:non-scaling-stroke; } .zero { stroke-dasharray:4 6; }
.soc-shell { height: 12px; border: 1px solid var(--rule-strong); padding: 2px; background: var(--canvas); } .soc-fill { width:0; height:100%; background: var(--blue); transition: width .4s ease; }
.flow-panel { padding: 24px; } .flow { margin-top: 18px; display:grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.node { min-height: 110px; padding: 18px; border:1px solid var(--rule); background: var(--canvas); display:flex; flex-direction:column; justify-content:space-between; } .node.primary { border-color: rgba(31,94,255,.35); box-shadow: inset 0 0 0 1px rgba(31,94,255,.12); }
.card { padding: 28px; margin-bottom: 18px; } .card h2 { margin-bottom: 16px; }
input { width:100%; margin-top: 8px; border:1px solid var(--rule-strong); background:#fff; padding: 11px 12px; font: inherit; color: var(--ink); outline-color: var(--blue); }
button { border:1px solid var(--ink); background:var(--ink); color:#fff; padding: 11px 15px; margin: 8px 8px 0 0; font: 800 11px/1 var(--sans); letter-spacing:.18em; text-transform:uppercase; cursor:pointer; }
button.secondary { background:#fff; color:var(--ink); border-color:var(--rule-strong); }
.badge { display:inline-flex; align-items:center; border:1px solid var(--rule-strong); padding: 6px 10px; font-family:var(--mono); }
.error { color: var(--red); font-weight: 800; } meter { width: 100%; height: 12px; }
.toggle-row { display:flex; align-items:center; gap:12px; margin-bottom:12px; } .toggle-row label { display:flex; align-items:center; gap:8px; }
.status-dot { width:8px; height:8px; display:inline-block; border-radius:50%; } .dot-on { background:var(--green); } .dot-off { background:var(--quiet); }
pre, pre.debug { background:#111827; color:#eef2f7; padding:16px; overflow:auto; max-height:600px; white-space:pre-wrap; word-break:break-word; font-size:12px; }
.forecast-box { flex:1; min-height:180px; border:1px dashed var(--rule-strong); display:flex; align-items:center; justify-content:center; color:var(--quiet); }
.forecast-curve { width: 78%; height: 48%; border-left: 1px solid var(--quiet); border-bottom: 1px solid var(--quiet); position: relative; } .forecast-curve:after { content:""; position:absolute; left:8%; right:5%; bottom:20%; height:45%; border-top:2px solid var(--blue); transform:skewX(-22deg); opacity:.55; }
.todo { color: var(--amber); font-size: 11px; line-height: 1.7; }
.module-placeholder { min-height: 48vh; display:flex; align-items:end; justify-content:space-between; gap:24px; }
.module-placeholder p { max-width: 520px; color: var(--muted); line-height:1.8; }
@media (max-width: 980px) { .brand-shell { padding: 24px; } .brand-header { height:auto; align-items:flex-start; flex-direction:column; padding-bottom:22px; } .hero, .dashboard-grid { grid-template-columns:1fr; } .flow { grid-template-columns: repeat(2, 1fr); } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration:.001ms !important; transition-duration:.001ms !important; } }
"""


def brand_mark() -> str:
    return """
    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true">
      <line x1="16" y1="7" x2="7" y2="24"></line><line x1="16" y1="7" x2="25" y2="24"></line><line x1="7" y1="24" x2="25" y2="24"></line>
      <circle cx="16" cy="7" r="2.4"></circle><circle cx="7" cy="24" r="2.4"></circle><circle cx="25" cy="24" r="2.4"></circle>
    </svg>
    """


def render_page(active: str, body: str) -> str:
    links = "".join(
        f"<a class='{ 'active' if item == active else '' }' href='/{item.lower() if item != 'Dashboard' else ''}'>{item}</a>"
        for item in MENU
    )
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Minyad — {active}</title>
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
        <p>Grid net power: <strong id='battery-grid-net-power'>--</strong> W</p>
        <p>Grid delivered: <strong id='battery-grid-delivered'>--</strong> W</p>
        <p>Grid returned: <strong id='battery-grid-returned'>--</strong> W</p>
        <p>Grid status: <strong id='battery-grid-status'>--</strong></p>
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
          document.getElementById('battery-grid-net-power').textContent = displayValue(data.grid_net_power_w);
          document.getElementById('battery-grid-delivered').textContent = displayValue(data.grid_delivered_w);
          document.getElementById('battery-grid-returned').textContent = displayValue(data.grid_returned_w);
          document.getElementById('battery-grid-status').textContent = displayValue(data.grid_status);
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
          const res = await fetch('/api/dsmr/status');
          if(!res.ok) throw new Error(`DSMR status request failed (${res.status})`);
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
    # Live dashboard data is pulled through the existing production-backed API proxy.
    # TODO(MQTT): Keep DSMR P1 wiring aligned with MQTT topic `dsmr/reading` from 192.168.110.5:1883.
    # TODO(MQTT): Keep battery wiring aligned with `goodwe/battery` from 192.168.110.5:1883.
    # TODO(SOLAR): Solar live data is not yet available; keep all solar values scaffolded.
    return """
    <section class="hero" aria-labelledby="dashboard-title">
      <div class="overview-card card">
        <h1 id="dashboard-title">Metrics overview</h1>
        <div class="overview-metrics" aria-label="Current energy metrics">
          <div class="overview-metric"><span class="label">Grid net</span><span><span class="metric-value value" id="overview-grid-power">--</span><span class="unit">W</span></span></div>
          <div class="overview-metric"><span class="label">Home load</span><span><span class="metric-value value" id="overview-home-load">--</span><span class="unit">W</span></span></div>
          <div class="overview-metric"><span class="label">Battery SOC</span><span><span class="metric-value value" id="overview-battery-soc">--</span><span class="unit">%</span></span></div>
          <div class="overview-metric"><span class="label">Battery flow</span><span><span class="metric-value value" id="overview-battery-flow">--</span><span class="unit">W</span></span></div>
        </div>
      </div>
      <aside class="status-card" aria-label="Live source health">
        <div class="status-grid">
          <div class="status-tile"><span class="label">DSMR</span><span class="metric-value value" id="dash-dsmr-last-seen">--</span><span class="dot grey" id="dash-dsmr-dot"></span></div>
          <div class="status-tile"><span class="label">Battery</span><span class="metric-value value" id="dash-battery-last-seen">--</span><span class="dot grey" id="dash-battery-dot"></span></div>
          <div class="status-tile"><span class="label">Solar</span><span class="metric-value value">--</span><span class="dot grey"></span></div>
          <div class="status-tile"><span class="label">System</span><span class="metric-value value" id="dash-system-status">Loading</span><span class="dot grey" id="dash-system-dot"></span></div>
        </div>
      </aside>
    </section>

    <section class="dashboard-grid">
      <article class="panel">
        <div class="panel-head"><h2>Grid</h2><span class="label">DSMR P1</span></div>
        <svg class="sparkline" viewBox="0 0 600 150" role="img" aria-label="Recent grid import and export"><line class="axis zero" x1="0" y1="75" x2="600" y2="75"/><path class="spark" id="dash-grid-spark" d=""/></svg>
        <div class="large-row"><span class="large-value value" id="dash-grid-power">--</span> <span class="unit">W</span><div class="direction" id="dash-grid-direction">Loading</div></div>
        <div class="metric-grid"><div class="metric"><span class="label">Imported today</span><span class="value" id="dash-imported-today">--</span><span class="unit">kWh</span></div><div class="metric"><span class="label">Exported today</span><span class="value" id="dash-exported-today">--</span><span class="unit">kWh</span></div></div>
      </article>
      <article class="panel">
        <div class="panel-head"><h2>Battery</h2><span class="label">GoodWe</span></div>
        <div><span class="large-value value" id="dash-battery-soc">--</span> <span class="unit">%</span><div class="soc-shell"><div class="soc-fill" id="dash-battery-soc-fill"></div></div></div>
        <div class="metric-grid"><div class="metric"><span class="label">Current flow</span><span class="value" id="dash-battery-flow">--</span><span class="unit">W</span></div><div class="metric"><span class="label">State</span><span class="value" id="dash-battery-state">--</span></div><div class="metric"><span class="label">Est. empty</span><span class="value" id="dash-battery-runtime">--</span><span class="unit">h</span></div><div class="metric"><span class="label">Cycle count</span><span class="value" id="dash-battery-cycles">--</span><span class="unit">est.</span></div></div>
      </article>
      <article class="panel">
        <div class="panel-head"><h2>Solar forecast</h2><span class="dot grey"></span></div>
        <div class="forecast-box"><div class="forecast-curve" aria-label="Placeholder solar forecast curve"></div></div>
        <p class="todo">Pending integration: Open-Meteo GHI · Schipluiden 51.97°N 4.31°E.</p>
      </article>
    </section>

    <section class="flow-panel card">
      <span class="kicker">Data</span><h2>Power flow summary</h2>
      <div class="flow"><div class="node"><span class="label">Solar</span><span><span class="value">--</span> <span class="unit">W</span></span></div><div class="node primary"><span class="label">Home load</span><span><span class="value" id="dash-home-load">--</span> <span class="unit">W</span></span></div><div class="node"><span class="label">Grid</span><span><span class="value" id="dash-flow-grid">--</span> <span class="unit">W</span></span></div><div class="node"><span class="label">Battery</span><span><span class="value" id="dash-flow-battery">--</span> <span class="unit">W</span></span></div></div>
    </section>

    <script>
      const gridHistory = [];
      const usableBatteryKwh = 5;
      function localIso(value) { const date = value ? new Date(value) : new Date(); if (Number.isNaN(date.getTime())) return '--'; return date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
      function numberOrNull(value) { if (value === undefined || value === null || value === '') return null; const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
      function setText(id, value) { const element = document.getElementById(id); if (element) element.textContent = value; }
      function setDot(id, state) { const element = document.getElementById(id); if (element) element.className = `dot ${state}`; }
      function signedWatts(value) { if (value === null) return '--'; return `${value > 0 ? '+' : ''}${Math.round(value)}`; }
      function drawSparkline() { const path = document.getElementById('dash-grid-spark'); if (!path || gridHistory.length < 2) return; const width = 600; const height = 150; const maxAbs = Math.max(1000, ...gridHistory.map((point) => Math.abs(point))); const step = width / Math.max(1, gridHistory.length - 1); const commands = gridHistory.map((point, index) => { const x = Math.round(index * step); const y = Math.round((height / 2) - (point / maxAbs) * (height * 0.42)); return `${index === 0 ? 'M' : 'L'}${x} ${y}`; }); path.setAttribute('d', commands.join(' ')); }
      async function loadEnergyDashboard() {
        const settled = await Promise.allSettled([fetch('/api/dsmr/status').then((response) => { if (!response.ok) throw new Error(`DSMR ${response.status}`); return response.json(); }), fetch('/api/battery/status').then((response) => { if (!response.ok) throw new Error(`Battery ${response.status}`); return response.json(); })]);
        const dsmr = settled[0].status === 'fulfilled' ? settled[0].value : {}; const battery = settled[1].status === 'fulfilled' ? settled[1].value : {};
        const dsmrOk = settled[0].status === 'fulfilled' && dsmr.grid_status !== 'offline' && Object.keys(dsmr).length > 0; const batteryOk = settled[1].status === 'fulfilled' && battery.bridge_status !== 'offline' && battery.available !== false && Object.keys(battery).length > 0;
        setDot('dash-dsmr-dot', dsmrOk ? 'green' : 'red'); setDot('dash-battery-dot', batteryOk ? 'green' : 'red'); setText('dash-dsmr-last-seen', dsmr.grid_timestamp ? localIso(dsmr.grid_timestamp) : '--'); setText('dash-battery-last-seen', battery.bridge_last_seen ? localIso(battery.bridge_last_seen) : '--');
        const gridPower = numberOrNull(dsmr.grid_net_power_w ?? battery.grid_net_power_w); if (gridPower !== null) { gridHistory.push(gridPower); while (gridHistory.length > 60) gridHistory.shift(); }
        setText('dash-grid-power', signedWatts(gridPower)); setText('dash-flow-grid', signedWatts(gridPower)); setText('overview-grid-power', signedWatts(gridPower)); setText('dash-grid-direction', gridPower === null ? 'No data' : Math.abs(gridPower) < 25 ? 'Balanced' : gridPower > 0 ? 'Importing' : 'Exporting'); drawSparkline();
        const batteryPower = numberOrNull(battery.power_w); const soc = numberOrNull(battery.soc); setText('dash-battery-flow', signedWatts(batteryPower)); setText('overview-battery-flow', signedWatts(batteryPower)); setText('dash-flow-battery', batteryPower === null ? '--' : String(Math.round(Math.abs(batteryPower)))); setText('dash-battery-soc', soc === null ? '--' : String(Math.round(soc))); setText('overview-battery-soc', soc === null ? '--' : String(Math.round(soc))); const socFill = document.getElementById('dash-battery-soc-fill'); if (socFill) socFill.style.width = `${Math.max(0, Math.min(100, soc ?? 0))}%`;
        const batteryState = batteryPower === null ? (battery.state || '--') : Math.abs(batteryPower) < 25 ? 'Idle' : batteryPower > 0 ? 'Charging' : 'Discharging'; setText('dash-battery-state', batteryState);
        if (soc !== null && batteryPower !== null && Math.abs(batteryPower) >= 25) { const remainingKwh = batteryPower > 0 ? usableBatteryKwh * (100 - soc) / 100 : usableBatteryKwh * soc / 100; setText('dash-battery-runtime', (remainingKwh / (Math.abs(batteryPower) / 1000)).toFixed(1)); } else { setText('dash-battery-runtime', '--'); }
        const chargeEnergy = numberOrNull(battery.total_charge_energy); const dischargeEnergy = numberOrNull(battery.total_discharge_energy); const cycleEstimate = chargeEnergy !== null && dischargeEnergy !== null ? Math.round(Math.min(chargeEnergy, dischargeEnergy) / usableBatteryKwh) : null; setText('dash-battery-cycles', cycleEstimate === null ? '--' : String(cycleEstimate));
        const homeLoad = gridPower !== null && batteryPower !== null ? gridPower - batteryPower : null; const homeLoadText = homeLoad === null ? '--' : String(Math.max(0, Math.round(homeLoad))); setText('dash-home-load', homeLoadText); setText('overview-home-load', homeLoadText);
        setText('dash-system-status', !dsmrOk || !batteryOk ? 'Degraded' : 'Solar pending'); setDot('dash-system-dot', !dsmrOk || !batteryOk ? 'amber' : 'grey');
      }
      loadEnergyDashboard(); setInterval(loadEnergyDashboard, 10000);
    </script>
    """


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api_proxy(path: str, request: Request):
    async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
        response = await client.request(
            request.method,
            f"/{path}",
            content=await request.body(),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
    return response.json()


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return render_page("Dashboard", energy_dashboard_body())


@app.get("/{section}", response_class=HTMLResponse)
async def section(section: str) -> str:
    title = "DSMR" if section.lower() == "dsmr" else section.capitalize()
    if title not in MENU:
        title = "Dashboard"
    if title == "Settings":
        return render_page(title, battery_settings_body())
    if title == "Battery":
        return render_page(title, battery_control_body())
    if title == "DSMR":
        return render_page(title, dsmr_body())
    content = f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
