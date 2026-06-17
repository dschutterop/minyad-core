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
          button {{ margin:6px 6px 6px 0; padding:10px 14px; border:0; border-radius:8px; background:#2563eb; color:white; }}
          .badge {{ padding:4px 8px; border-radius:999px; background:#dbeafe; color:#1e40af; }}
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
        <label>Inverter IP <input name='inverter_ip' type='text' pattern='^([0-9]{1,3}\\.){3}[0-9]{1,3}$'></label>
        <label>Retries <input name='inverter_retries' type='number' min='1' max='10'></label>
        <label>Retry delay s <input name='inverter_delay' type='number' min='1' max='30'></label>
        <button type='submit'>Save battery settings</button>
      </form><pre id='settings-result'></pre></div>
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
      loadBatterySettings();
    </script>
    """


def battery_control_body() -> str:
    return """
    <div class='card'><h2>Battery override</h2>
      <p>State: <strong id='battery-state' class='badge'>...</strong></p>
      <p>SOC: <meter id='battery-soc-gauge' min='0' max='100' value='0'></meter> <span id='battery-soc'>--</span>%</p>
      <p>Power flow: <strong id='battery-power'>--</strong> W</p>
      <p>Override: <strong id='battery-override'>none</strong></p>
      <button onclick='forceCharge()'>Force charge</button>
      <button onclick='sendOverride({mode:"force_off"})'>Force stop</button>
      <button onclick='forceDischarge()'>Force discharge</button>
      <button onclick='sendOverride({mode:"pause", duration_seconds:3600})'>Pause (1h)</button>
      <button onclick='resumeNormal()'>Resume normal</button>
    </div>
    <script>
      async function loadBatteryStatus(){
        const res = await fetch('/api/battery/status'); const data = await res.json();
        const override = data.override_mode && data.override_mode !== 'none';
        document.getElementById('battery-state').textContent = override ? 'OVERRIDE' : (data.state || 'IDLE');
        document.getElementById('battery-soc-gauge').value = data.soc || 0;
        document.getElementById('battery-soc').textContent = data.soc ?? '--';
        document.getElementById('battery-power').textContent = data.power_w ?? '--';
        document.getElementById('battery-override').textContent = data.override_mode || 'none';
      }
      async function sendOverride(payload){
        if(!confirm('Apply battery override?')) return;
        await fetch('/api/battery/override',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        loadBatteryStatus();
      }
      function forceCharge(){ const watts = Number(prompt('Charge watts?')); if(watts) sendOverride({mode:'force_on', watts}); }
      function forceDischarge(){ const watts = Number(prompt('Discharge watts?')); if(watts) sendOverride({mode:'force_discharge', watts}); }
      async function resumeNormal(){ if(confirm('Resume normal hysteresis control?')){ await fetch('/api/battery/override',{method:'DELETE'}); loadBatteryStatus(); } }
      loadBatteryStatus(); setInterval(loadBatteryStatus, 10000);
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
    content = f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
