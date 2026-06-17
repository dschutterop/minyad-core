"""Traditional Minyad web UI scaffold."""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Minyad Frontend")
API_BASE_URL = os.getenv("API_BASE_URL", "http://minyad-api:8000")

MENU = ["Dashboard", "Control", "Solar", "Battery", "DSMR", "Reporting", "Settings"]


def render_page(active: str, body: str) -> str:
    links = "".join(f"<a class='{ 'active' if item == active else '' }' href='/{item.lower() if item != 'Dashboard' else ''}'>{item}</a>" for item in MENU)
    return f"""
    <html>
      <head>
        <title>Minyad - {active}</title>
        <style>
          body {{ margin:0; font-family: system-ui, sans-serif; display:flex; min-height:100vh; background:#f6f8fb; color:#162033; }}
          nav {{ width:220px; background:#111827; padding:24px 16px; }}
          nav h1 {{ color:#fff; font-size:24px; }}
          nav a {{ display:block; color:#cbd5e1; padding:10px 12px; text-decoration:none; border-radius:8px; }}
          nav a.active, nav a:hover {{ background:#2563eb; color:#fff; }}
          main {{ flex:1; padding:32px; }}
          .card {{ background:#fff; border-radius:16px; padding:24px; box-shadow:0 8px 24px rgba(15,23,42,.08); margin-bottom:18px; }}
          .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; }}
          label {{ display:flex; flex-direction:column; gap:6px; font-weight:600; }}
          input {{ padding:8px; border:1px solid #cbd5e1; border-radius:8px; }}
          button {{ margin:6px 6px 6px 0; padding:10px 14px; border:0; border-radius:8px; background:#2563eb; color:white; cursor:pointer; }}
          button.secondary {{ background:#64748b; }}
          .badge {{ padding:4px 8px; border-radius:999px; background:#dbeafe; color:#1e40af; }}
          .error {{ color:#b91c1c; font-weight:700; }}
          .toggle-row {{ display:flex; align-items:center; gap:12px; margin-bottom:12px; }}
          .toggle-row label {{ flex-direction:row; align-items:center; gap:8px; margin:0; font-weight:600; }}
          .status-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
          .dot-on {{ background:#22c55e; }}
          .dot-off {{ background:#94a3b8; }}
          pre.debug {{ background:#0f172a; color:#e2e8f0; border-radius:12px; padding:16px; font-size:12px; overflow:auto; max-height:600px; white-space:pre-wrap; word-break:break-all; }}
        </style>
      </head>
      <body><nav><h1>Minyad</h1>{links}</nav><main>{body}</main></body>
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
    return render_page("Dashboard", "<div class='card'><h2>Energy Flow</h2><p>Solar → Home → Battery → Grid, health, and forecast placeholders.</p></div>")


@app.get("/{section}", response_class=HTMLResponse)
async def section(section: str) -> str:
    title = "DSMR" if section.lower() == "dsmr" else section.capitalize()
    if title not in MENU:
        title = "Dashboard"
    if title == "Settings":
        return render_page(title, battery_settings_body())
    if title == "Control":
        return render_page(title, battery_control_body())
    if title == "DSMR":
        return render_page(title, dsmr_body())
    content = f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
