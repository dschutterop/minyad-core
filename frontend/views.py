"""Pure HTML/JS page-body builders for the Minyad frontend.

Every function here takes plain data (or nothing) and returns an HTML
string -- no FastAPI request/session, no httpx calls. Routing and the
API-proxying live in frontend/main.py.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

try:
    from frontend.assets import (
        AUTO_REFRESH_SCRIPT,
        BRAND_CSS,
        LANGUAGE_BOOT_SCRIPT,
        THEME_BOOT_SCRIPT,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the frontend Docker image layout
    from assets import (
        AUTO_REFRESH_SCRIPT,
        BRAND_CSS,
        LANGUAGE_BOOT_SCRIPT,
        THEME_BOOT_SCRIPT,
    )


MENU = ["Dashboard", "Agent", "Health", "History", "Trade", "Solar", "Battery", "DSMR", "Asset Steering", "Reporting", "Settings"]


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


def html_response(content: str) -> HTMLResponse:
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


def render_page(active: str, body: str, brand_name: str = "Minyad Core") -> str:
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
        {LANGUAGE_BOOT_SCRIPT}
        {AUTO_REFRESH_SCRIPT}
      </head>
      <body>
        <div class="brand-shell">
          <header class="brand-header">
            <a class="brand-lockup" href="/" aria-label="Minyad dashboard">
              {brand_mark()}
              <span class="wordmark"><strong>{brand_name}</strong><span>Virtual Power Plant</span></span>
            </a>
            <nav class="brand-nav" aria-label="Primary navigation">{links}</nav>
          </header>
          <main class="brand-main">{body}</main>
        </div>
      </body>
    </html>
    """


def render_dashboard_page(brand_name: str = "Minyad Core") -> str:
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
        {LANGUAGE_BOOT_SCRIPT}
        {AUTO_REFRESH_SCRIPT}
      </head>
      <body class="dashboard-page">
        {energy_dashboard_body(brand_name)}
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
    <div class='health-shell'>
      <section class='card'>
        <span class='kicker'>Health</span>
        <h1 class='page-title'>Health</h1>
        <div class='health-summary'>
          <div class='health-summary-main'>
            <span class='health-status health-warn' id='overall-pill'><i></i><span id='overall-status'>--</span></span>
            <span class='health-updated'>Last checked <span id='health-checked'>--</span></span>
          </div>
          <div class='health-actions'>
            <button type='button' class='health-refresh' onclick='loadHealth()'>Refresh now</button>
          </div>
        </div>
      </section>
      <section class='health-table-wrap' aria-label='Service health status'>
        <table class='health-table'>
          <thead>
            <tr>
              <th scope='col'>Service</th>
              <th scope='col'>Status</th>
              <th scope='col'>Detail</th>
              <th scope='col'>Endpoint</th>
              <th scope='col'>Last seen</th>
            </tr>
          </thead>
          <tbody id='health-rows'>
            <tr><td colspan='5' class='health-empty'>Loading...</td></tr>
          </tbody>
        </table>
      </section>
    </div>
    <script>
      const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      const fmtTime=value=>{
        if(!value)return '--';
        const date=new Date(value);
        return Number.isNaN(date.getTime())?String(value):date.toLocaleString();
      };
      const statusText=status=>status==='ok'?'OK':'NOK';
      const statusClass=status=>status==='ok'?'health-ok':status==='warning'?'health-warn':'health-nok';
      function setOverall(status){
        const pill=document.getElementById('overall-pill');
        pill.className='health-status '+statusClass(status);
        document.getElementById('overall-status').textContent=statusText(status);
      }
      function row(item){
        const status=item.status||'error';
        const lastSeen=item.last_seen||item.generated_at||'';
        return `<tr>
          <td class='health-service'>${esc(item.name||'Unknown service')}</td>
          <td><span class='health-status ${statusClass(status)}'><i></i>${statusText(status)}</span></td>
          <td class='health-detail'>${esc(item.detail||'--')}</td>
          <td class='health-meta'>${esc(item.endpoint||'--')}</td>
          <td class='health-meta'>${esc(fmtTime(lastSeen))}</td>
        </tr>`;
      }
      async function loadHealth(){
        try{
          const res=await fetch('/api/health/status'); if(!res.ok) throw new Error('Health request failed ('+res.status+')');
          const data=await res.json();
          const components=data.components||[];
          setOverall(data.status);
          document.getElementById('health-checked').textContent=fmtTime(data.generated_at);
          document.getElementById('health-rows').innerHTML=components.length?components.map(row).join(''):`<tr><td colspan='5' class='health-empty'>No service health checks returned.</td></tr>`;
        }catch(e){
          setOverall('error');
          document.getElementById('health-checked').textContent=fmtTime(new Date().toISOString());
          document.getElementById('health-rows').innerHTML=`<tr><td colspan='5' class='health-empty error'>${esc(e.message||'Unable to load health')}</td></tr>`;
        }
      }
      loadHealth(); setInterval(loadHealth, 15000);
    </script>
    """


def battery_settings_body() -> str:
    return """
    <div class='settings-layout'>
      <nav class='settings-nav' role='tablist' aria-label='Settings sections'>
        <button type='button' role='tab' class='active' data-settings-section='battery' aria-controls='settings-battery' aria-selected='true'><strong>Battery</strong><span>Charging, discharge and inverter limits</span></button>
        <button type='button' role='tab' tabindex='-1' data-settings-section='trade' aria-controls='settings-trade' aria-selected='false'><strong>Energy trade</strong><span>Day-ahead price collection and retry behavior</span></button>
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
        <label>GoodWe poll interval grace s <input name='goodwe_poll_interval_grace_s' type='number' min='0' max='3600'></label>
        <p style='grid-column:1/-1;color:var(--steel);font-size:14px;margin:0'>Effective charge cap = min(max_charge_w, max_charge_a × nominal_v): <strong id='effective-charge-cap'>-- W</strong></p>
        <button type='submit'>Save battery settings</button>
      </form><pre id='settings-result'></pre></section>

    <section id='settings-trade' role='tabpanel' class='card settings-section' data-settings-panel='trade' hidden><h2>Energy trade</h2><p>EPEX day-ahead collection settings. Changes are published to MQTT and picked up without restarting the trade price collector.</p>
      <form id='trade-settings' class='grid'>
        <label>Bidding zone <input name='bidding_zone' type='text'></label>
        <label>Poll time Europe/Amsterdam <input name='poll_time_local' type='time'></label>
        <label>Retry attempts <input name='retry_attempts' type='number' min='1' max='24'></label>
        <label>Retry interval minutes <input name='retry_interval_minutes' type='number' min='1' max='240'></label>
        <label>Day-ahead price API URL <input name='entsoe_api_url' type='url' placeholder='https://web-api.tp.entsoe.eu/api'></label>
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
        <label class='theme-option'><input type='radio' name='theme' value='system'><b>System default</b><span>Follow this device</span></label>
        <label class='theme-option'><input type='radio' name='theme' value='light'><b>Light</b><span>Bright interface</span></label>
        <label class='theme-option'><input type='radio' name='theme' value='dark'><b>Dark</b><span>Low-light interface</span></label>
      </div>
      <pre id='theme-result'></pre>
      <h3>Language</h3>
      <p style='color:var(--steel);font-size:14px;margin:0 0 12px'>Choose the display language for Minyad.</p>
      <div class='theme-options' role='radiogroup' aria-label='Language'>
        <label class='theme-option'><input type='radio' name='language' value='en'><b>English</b><span>EN</span></label>
        <label class='theme-option'><input type='radio' name='language' value='nl'><b>Dutch</b><span>NL</span></label>
      </div>
      <pre id='language-result'></pre>
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

      document.querySelectorAll('input[name="language"]').forEach((input) => {
        input.addEventListener('change', async (e) => {
          if (!e.target.checked) return;
          try {
            const settings = await window.minyadI18n.save(e.target.value);
            document.getElementById('language-result').textContent = JSON.stringify({language: settings.language}, null, 2);
            window.location.reload();
          } catch (err) {
            document.getElementById('language-result').textContent = 'Error: ' + err.message;
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
        const language = data.language || 'en';
        localStorage.setItem(window.minyadI18n.key, language);
        window.minyadI18n.apply(language);
        const languageInput = document.querySelector(`input[name="language"][value="${language}"]`);
        if (languageInput) languageInput.checked = true;
        document.getElementById('language-result').textContent = JSON.stringify({language}, null, 2);
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
      function forceCharge(){ const watts = Number(prompt('Charge watts?')); if(watts) sendOverride({mode:'force_charge', watts, override_soc_limits:confirm('SOC limit voor één charge-cyclus overriden?')}); }
      function forceDischarge(){ const watts = Number(prompt('Discharge watts naar huis/net via GoodWe bridge?')); if(watts) sendOverride({mode:'force_discharge', watts, override_soc_limits:confirm('SOC limit voor één discharge-cyclus overriden?')}); }
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


def segmented_control(aria_label: str, buttons: list[tuple[str, str, str, bool]]) -> str:
    rendered = "".join(
        f'<button id="{button_id}" class="{"active" if active else ""}" type="button" onclick="{onclick}">{label}</button>'
        for button_id, label, onclick, active in buttons
    )
    return f'<div class="layout-toggle segmented-control" role="tablist" aria-label="{aria_label}">{rendered}</div>'


def status_pill(
    pill_id: str,
    label: str,
    variant: str,
    *,
    label_id: str | None = None,
    extra_class: str = "",
    hidden: bool = False,
) -> str:
    classes = f"status-pill status--{variant}"
    if extra_class:
        classes += f" {extra_class}"
    hidden_attr = " hidden" if hidden else ""
    label_attr = f' id="{label_id}"' if label_id else ""
    return f'<span class="{classes}" id="{pill_id}"{hidden_attr}><i></i><span{label_attr}>{label}</span></span>'


def metric_card(
    kind: str,
    title: str,
    icon_html: str,
    pill_html: str,
    value_id: str,
    *,
    card_id: str | None = None,
    phrase_id: str | None = None,
    value_class: str = "",
    subtitle_html: str = "",
    visual_html: str = "",
    footer_html: str = "",
    aria_label: str = "",
) -> str:
    value_classes = f"phrase {value_class}".strip()
    id_attr = f' id="{card_id}"' if card_id else ""
    phrase_id_attr = f' id="{phrase_id}"' if phrase_id else ""
    return f"""
            <article class="tile metric-card {kind}"{id_attr} aria-label="{aria_label or title}">
              <div class="tile-head metric-card-head"><span class="tile-name">{icon_html} {title}</span>{pill_html}</div>
              <div class="metric-value-row">
                <div class="{value_classes}"{phrase_id_attr}><span id="{value_id}">--</span> <span class="unit power-unit">kW</span></div>
                {subtitle_html}
              </div>
              <div class="metric-visual">{visual_html}</div>
              <div class="metric-footer">{footer_html}</div>
            </article>
    """


def battery_pack() -> str:
    return """
                <div class="soc">
                  <div class="scale"><span class="scale-label">State of charge</span><span class="scale-label">usable window</span></div>
                  <div class="battery-pack-row">
                    <div id="battery-pack" class="battery-pack" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Battery state of charge">
                      <div class="battery-shell">
                        <div class="cells" id="soc-cells"></div>
                        <span id="soc-min-line" class="soc-limit min" title="Minimum SoC" hidden></span>
                        <span id="soc-max-line" class="soc-limit max" title="Maximum SoC" hidden></span>
                      </div>
                      <span class="battery-terminal" aria-hidden="true"></span>
                    </div>
                    <span id="soc-text" class="battery-soc-text">--%</span>
                  </div>
                  <div class="soc-limit-labels">
                    <span id="soc-min-label" class="soc-limit-label min" hidden>min --%</span>
                    <span id="soc-max-label" class="soc-limit-label max" hidden>max --%</span>
                  </div>
                </div>
    """


def kpi_tile(value_id: str, label: str, *, value: str = "--", accent_class: str = "") -> str:
    value_classes = f' class="{accent_class}"' if accent_class else ""
    return f'<div class="kpi-tile"><b id="{value_id}"{value_classes}>{value}</b><span>{label}</span></div>'


def energy_dashboard_body(brand_name: str = "Minyad Core") -> str:
    unit_toggle = segmented_control(
        "Power unit",
        [
            ("watts-toggle", "Watts", "setPowerUnit('w')", False),
            ("kilowatts-toggle", "Kilowatts", "setPowerUnit('kw')", True),
        ],
    )
    layout_toggle = segmented_control(
        "Dashboard layout",
        [
            ("cluster-toggle", "Cluster", "setLayout('cluster')", True),
            ("flow-toggle", "Flow", "setLayout('flow')", False),
        ],
    )
    solar_card = metric_card(
        "produce",
        "Solar",
        icon("solar"),
        status_pill("solar-pill", "Producing", "producing", label_id="solar-status"),
        "solar-value",
        value_class="produce-c",
        visual_html="""
                <div class="visual-stack">
                  <div class="bar"><span id="solar-bar" class="fill" style="background:var(--produce-d)"></span></div>
                  <div class="scale"><span class="scale-label">0</span><span class="scale-label">~5 kWp peak</span></div>
                  <svg id="solar-spark" class="sparkline" viewBox="0 0 240 58" role="img" aria-label="Solar production today"></svg>
                </div>
        """,
        footer_html='<span class="footer-stat footer-stat-strong"><span class="footer-label">Generated today</span><b><span id="solar-kwh">--</span> kWh</b></span>',
        aria_label="Solar live tile",
    )
    battery_card = metric_card(
        "store battery-card",
        "Battery",
        icon("battery"),
        status_pill("battery-pill", "IDLE", "idle", label_id="battery-status-word"),
        "battery-value",
        value_class="store-c",
        visual_html=f"""
                <div class="visual-stack">
                  <div class="bar center"><span id="battery-bar" class="fill" style="background:var(--battery-accent);left:50%"></span></div>
                  <div class="scale three-up"><span class="scale-label scale-power" data-kw="-3 charge" data-w="-3000 charge">-3 charge</span><span class="scale-label">0</span><span class="scale-label scale-power" data-kw="+3 discharge" data-w="+3000 discharge">+3 discharge</span></div>
                  {battery_pack()}
                </div>
        """,
        footer_html='<span class="footer-stat"><span class="footer-label">Capacity</span><b id="battery-capacity-text">-- / 10 kWh</b></span><span class="footer-stat"><span class="footer-label">Health</span><b id="soh-text">--%</b></span><div class="thin"><i id="soh-bar" style="width:98%"></i></div>',
        aria_label="Battery live tile",
    )
    grid_card = metric_card(
        "import",
        "Grid",
        icon("grid"),
        status_pill("grid-pill", "Importing", "importing", label_id="grid-status-word"),
        "grid-value",
        card_id="grid-tile",
        phrase_id="grid-phrase",
        value_class="import-c",
        subtitle_html='<div class="metric-subtitle" id="grid-direction-label">importing from grid</div>',
        visual_html="""
                <div class="visual-stack">
                  <div class="bar center"><span id="grid-bar" class="fill" style="left:50%"></span></div>
                  <div class="scale three-up"><span class="scale-label scale-power" data-kw="-3 import" data-w="-3000 import">-3 import</span><span class="scale-label">0</span><span class="scale-label scale-power" data-kw="+3 export" data-w="+3000 export">+3 export</span></div>
                  <svg id="grid-spark" class="sparkline" viewBox="0 0 240 58" role="img" aria-label="Grid power today"></svg>
                </div>
        """,
        footer_html='<span class="footer-stat"><span class="footer-label">Imported today</span><b><span id="grid-import-kwh">--</span> kWh</b></span><span class="footer-stat"><span class="footer-label">Exported</span><b><span id="grid-export-kwh">--</span> kWh</b></span>',
        aria_label="Grid live tile",
    )
    household_card = metric_card(
        "household",
        "Home Consumption",
        icon("home"),
        status_pill("household-pill", "Live", "live", label_id="household-status-word"),
        "household-value",
        value_class="household-c",
        visual_html="""
                <div class="visual-stack">
                  <div class="bar"><span id="household-bar" class="fill" style="background:var(--home-d)"></span></div>
                  <div class="scale"><span class="scale-label">0</span><span class="scale-label">~5 kW load</span></div>
                  <svg id="household-spark" class="sparkline" viewBox="0 0 240 58" role="img" aria-label="Household load for the last hour"></svg>
                </div>
        """,
        footer_html='<span class="footer-stat"><span class="footer-label">Consumed today</span><b><span id="household-kwh">--</span> kWh</b></span>' + status_pill("household-badge", "mismatch", "mismatch", extra_class="status-pill-small", hidden=True),
        aria_label="Household load live tile",
    )
    kpi_strip = "".join(
        [
            kpi_tile("summary-self", "Self-sufficiency", value="--%", accent_class="produce-c"),
            kpi_tile("kwh-produced", "Total generated", accent_class="produce-c"),
            kpi_tile("summary-consumed", "Total consumed"),
            kpi_tile("kwh-imported", "Imported", accent_class="import-c"),
            kpi_tile("kwh-exported", "Exported", accent_class="produce-c"),
            kpi_tile("summary-cycles", "Battery cycles", accent_class="store-c"),
            kpi_tile("summary-co2", "CO2 saved", accent_class="produce-c"),
        ]
    )
    return """
    <section class="instrument dashboard-full" aria-label="Minyad live dashboard">
      <div class="dashboard-nav"><a class="brand-lockup" href="/" aria-label="Minyad dashboard">__MARK__<span class="wordmark"><strong>__BRAND__</strong><span>Virtual Power Plant</span></span></a><nav class="brand-nav" aria-label="Primary navigation">__NAV__</nav></div>
      <div class="window-bar">
        <div class="window-actions">
          __UNIT_TOGGLE__
          __LAYOUT_TOGGLE__
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
            __METRIC_CARDS__
          </div>
          <div class="chart-card desktop-only"><div class="chart-top"><span class="tile-name">Combined day graph · kW / EUR/kWh</span><span id="plan-status-badge" class="status-pill" hidden></span><div class="chart-legend" aria-label="Toggle day graph series"><button type="button" data-chart-series="forecast" aria-pressed="true" style="color:var(--steel)"><i></i>Solar forecast</button><button type="button" data-chart-series="solar" aria-pressed="true" style="color:var(--produce-d)"><i></i>Production</button><button type="button" data-chart-series="battery" aria-pressed="true" style="color:var(--store-d)"><i></i>Battery</button><button type="button" data-chart-series="grid" aria-pressed="true" style="color:var(--import-d)"><i></i>Grid</button><button type="button" data-chart-series="household" aria-pressed="true" style="color:var(--home-d)"><i></i>Home</button><button type="button" data-chart-series="load_forecast" aria-pressed="true" style="color:var(--home-d)"><i></i>Load forecast</button><button type="button" data-chart-series="grid_forecast" aria-pressed="true" style="color:var(--import-d)"><i></i>Grid forecast</button><button type="button" data-chart-series="curtailment" aria-pressed="false" style="color:#E8B04A"><i></i>Curtailment</button><button type="button" data-chart-series="prices" aria-pressed="false" style="color:#70A7D7"><i style="height:8px;width:8px;border-radius:2px"></i>Day-ahead prices</button></div><div class="chart-range" aria-label="Chart range"><button type="button" class="active" data-chart-range="24h">24H</button><button type="button" data-chart-range="12h">12H</button><button type="button" data-chart-range="7d">7D</button><button type="button" data-chart-range="30d">30D</button></div></div><div class="chart-wrap"><svg id="day-chart" class="chart" viewBox="0 0 960 300" role="img" aria-label="Solar forecast, production, battery, grid, home consumption and day-ahead price series for today"></svg><div id="day-chart-tooltip" class="chart-tooltip" hidden></div></div><div class="daystrip">__KPI_STRIP__</div><div id="forecast-quality-block" class="load-meta" hidden></div></div>
        </div>
        <div id="flow-view" class="view"><div class="flow-board"><svg class="flow-svg" viewBox="0 0 1000 560" aria-hidden="true"><path id="flow-solar-home" class="flow-line" d="M500 135 L500 245"/><path id="flow-home-battery" class="flow-line" d="M450 290 L260 420"/><path id="flow-home-grid" class="flow-line" d="M550 290 L740 420"/></svg><div class="flow-node solar"><span class="tile-name">Solar</span><div class="phrase produce-c"><span id="f-solar">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node home"><span class="tile-name">Home</span><div class="phrase"><span id="f-home">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node battery"><span class="tile-name">Battery</span><div class="phrase store-c"><span id="f-battery">--</span> <span class="unit power-unit">kW</span></div></div><div class="flow-node grid"><span class="tile-name">Grid</span><div class="phrase" id="f-grid-phrase"><span id="f-grid">--</span> <span class="unit power-unit">kW</span></div></div></div></div>
        <div class="mobile-readout"><div class="mobile-rows"><div class="mobile-row"><span class="tile-name">Battery</span><b class="value store-c" id="m-battery">-- kW</b></div><div class="mobile-row"><span class="tile-name">Grid</span><b class="value" id="m-grid">-- kW</b></div><div class="mobile-row"><span class="tile-name">Self-sufficiency</span><b class="value produce-c" id="m-self">--%</b></div></div></div>
      </div>
    </section>
    <script>
      const solarMax=5, signedMax=3, batteryMaxW=3000, nominalKwh=10; let powerUnit='kw'; let last={solar:0,battery:0,grid:0,household:0,soc:82,soh:98}; let batteryLimits={min:null,max:null,overrideSoc:false}; let batteryVisualConfig={trajDeadbandPct:3}; let curves=null; let curvesLoadedAt=0; let chartRange='24h'; let mailboxMessages=[]; let mailboxTab='messages'; let selectedMessageId=null; let tradePrices=[]; let tradePricesLoadedAt=0; let forecastQuality=null; let forecastQualityLoadedAt=0; const chartSeriesVisible={forecast:true,solar:true,battery:true,grid:true,household:true,load_forecast:true,grid_forecast:true,curtailment:false,prices:false};
      const $=id=>document.getElementById(id); const n=v=>{const x=Number(v);return Number.isFinite(x)?x:null}; const fmtPower=(v,signed=false)=>{if(v==null)return '--'; const value=powerUnit==='w'?Math.round(Math.abs(v)*1000):Math.abs(v).toFixed(2); return signed?(v>0?'+':'-')+value:String(value)}; const unitLabel=()=>powerUnit==='w'?'W':'kW';
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
      function initChartRange(){document.querySelectorAll('[data-chart-range]').forEach(el=>el.addEventListener('click',async()=>{chartRange=el.dataset.chartRange||'24h'; document.querySelectorAll('[data-chart-range]').forEach(btn=>btn.classList.toggle('active',btn===el)); curves=null; curvesLoadedAt=0; await update();}));}
      function setPowerUnit(unit){powerUnit=unit; $('watts-toggle').classList.toggle('active',unit==='w'); $('kilowatts-toggle').classList.toggle('active',unit==='kw'); document.querySelectorAll('.power-unit').forEach(el=>el.textContent=unitLabel()); document.querySelectorAll('.scale-power').forEach(el=>el.textContent=el.dataset[unit]); renderReadings();}
      function setStatusPill(id,variant,isActive=false){const el=$(id); if(!el)return; const small=el.classList.contains('status-pill-small')?' status-pill-small':''; el.className=`status-pill status--${variant}${small}${isActive?' is-active':''}`;}
      function renderReadings(){const home=Math.max(0,last.household||last.solar+last.battery-last.grid), gExport=last.grid>=0; $('solar-value').textContent=fmtPower(last.solar); $('m-solar').textContent=fmtPower(last.solar); $('battery-value').textContent=fmtPower(last.battery,true); $('grid-value').textContent=fmtPower(last.grid,true); $('household-value').textContent=fmtPower(home); $('f-solar').textContent=fmtPower(last.solar); $('f-battery').textContent=fmtPower(last.battery,true); $('f-grid').textContent=fmtPower(last.grid,true); $('f-home').textContent=fmtPower(home); $('m-battery').textContent=fmtPower(last.battery,true)+' '+unitLabel(); $('m-grid').textContent=fmtPower(last.grid,true)+' '+unitLabel(); $('f-grid-phrase').className='phrase '+(gExport?'produce-c':'import-c'); const gridLabel=Math.abs(last.grid)<.03?'standing by':gExport?'exporting to grid':'importing from grid'; $('grid-direction-label').textContent=gridLabel; $('household-bar').style.width=Math.min(100,home/solarMax*100)+'%';}
      function setBar(id,v,max,color){const el=$(id); if(!el)return; const pct=Math.min(100,Math.abs(v)/max*50); el.style.backgroundColor=color; if(v<0){el.style.left=(50-pct)+'%';el.style.width=pct+'%'}else{el.style.left='50%';el.style.width=pct+'%'}}
      function truthyFlag(value){return value===true||value===1||['1','true','yes','on','active','fault','error'].includes(String(value||'').toLowerCase());}
      function deriveBatteryVisualState(battery){const powerW=n(battery.power_w)??Math.round(last.battery*1000), soc=n(battery.soc)??last.soc, minSoc=Math.max(15,n(batteryLimits.min)??15), deadbandPct=n(batteryVisualConfig.trajDeadbandPct)??3, deadbandW=deadbandPct/100*batteryMaxW; const statusText=[battery.mode,battery.mode_label,battery.state,battery.control_state,battery.bridge_status,battery.inverter_status,battery.fault,battery.error,battery.guard_reason,battery.adjustment_reason].filter(v=>v!=null).join(' ').toLowerCase(); const socNearMin=soc!=null&&soc<=minSoc+3; const guardActive=['guard_active','guard_intervention_active','guard_intervention','guard_layer_active','soc_guard_active'].some(key=>truthyFlag(battery[key]))||statusText.includes('guard:'); const inverterFault=['inverter_fault','fault_active','hard_fault'].some(key=>truthyFlag(battery[key]))||/\b(fault|error)\b/.test(statusText); if(socNearMin||guardActive||inverterFault)return {state:'alert',label:'ALERT',color:'#EF9F27'}; if(powerW<-deadbandW)return {state:'charging',label:'CHARGING',color:'var(--produce-d)'}; if(powerW>deadbandW)return {state:'discharging',label:'DISCHARGING',color:'#378ADD'}; return {state:'idle',label:'IDLE',color:'#888780'};}
      function applyBatteryAccent(visual){const card=document.querySelector('.battery-card'); if(card)card.style.setProperty('--battery-accent',visual.color);}
      function setSoc(soc){const pct=clampPct(n(soc)??0), rounded=Math.round(pct), c=$('soc-cells'), pack=$('battery-pack'), blocks=10; $('soc-text').textContent=rounded+'%'; if(pack){pack.className='battery-pack '+(pct<15?'low':pct>=90?'high':''); pack.setAttribute('aria-valuenow',String(rounded));} c.style.gridTemplateColumns=`repeat(${blocks},1fr)`; c.innerHTML=''; for(let i=0;i<blocks;i++){const cell=document.createElement('i'); if(i<Math.round(pct/100*blocks)){const cellColor=i===0?'#E24B4A':i===1?'#EF9F27':'var(--produce-d)'; cell.className='on'; cell.style.backgroundImage='linear-gradient(90deg,#E24B4A 0%,#E24B4A 10%,#EF9F27 10%,#EF9F27 20%,var(--produce-d) 20%,var(--produce-d) 100%)'; cell.style.backgroundSize=`${blocks*100}% 100%`; cell.style.backgroundPosition=`${(i/(blocks-1))*100}% 0`; cell.style.borderColor=cellColor; cell.style.boxShadow=`0 0 8px color-mix(in srgb, ${cellColor} 32%, transparent)`; } c.appendChild(cell)} renderSocLimits();}
      function clampPct(value){return Math.max(0,Math.min(100,value));}
      function renderSocLimits(){const min=batteryLimits.overrideSoc?0:n(batteryLimits.min), max=batteryLimits.overrideSoc?100:n(batteryLimits.max); const limits=[['min',min],['max',max]]; for(const [kind,value] of limits){const line=$(`soc-${kind}-line`), label=$(`soc-${kind}-label`); if(!line||!label)continue; const hasValue=value!=null; line.hidden=!hasValue; label.hidden=!hasValue; if(!hasValue)continue; const pct=clampPct(value); line.style.left=pct+'%'; label.style.left=pct+'%'; label.textContent=`${kind} ${Math.round(value)}%${batteryLimits.overrideSoc?' override':''}`;}}
      async function loadBatteryLimits(){try{const res=await fetch('/api/battery/settings'); if(!res.ok)return; const settings=await res.json(); batteryLimits={...batteryLimits,min:n(settings.soc_floor),max:n(settings.soc_ceiling)}; renderSocLimits();}catch(e){}}
      async function loadBatteryVisualConfig(){try{const res=await fetch('/api/asset-steering/settings'); if(!res.ok)return; const settings=await res.json(); const pct=n(settings.strategy3?.traj_deadband_pct); batteryVisualConfig.trajDeadbandPct=pct==null?3:pct;}catch(e){batteryVisualConfig.trajDeadbandPct=3;}}
      function curveWindow(){return chartRange==='7d'?'week':chartRange==='30d'?'month':'day';}
      async function loadCurves(){const now=Date.now(); if(curves&&curves.window===curveWindow()&&now-curvesLoadedAt<60000)return curves; try{const res=await fetch(`/api/dashboard/curves?window=${curveWindow()}`); if(res.ok){curves=await res.json(); curvesLoadedAt=now;}}catch(e){} return curves;}
      async function loadTradePrices(){const now=Date.now(); if(tradePrices.length&&now-tradePricesLoadedAt<300000)return tradePrices; try{const res=await fetch('/api/trade/prices'); const data=res.ok?await res.json():{prices:[]}; tradePrices=(data.prices||[]).filter(p=>p.starts_at&&Number.isFinite(new Date(p.starts_at).getTime())&&Number.isFinite(Number(p.price_eur_kwh))).map(p=>({...p,source:'prices',price_eur_kwh:Number(p.price_eur_kwh)})).sort((a,b)=>new Date(a.starts_at)-new Date(b.starts_at)); tradePricesLoadedAt=now;}catch(e){} return tradePrices;}
      async function loadForecastQuality(){const now=Date.now(); if(forecastQuality&&now-forecastQualityLoadedAt<600000)return forecastQuality; try{const res=await fetch('/api/dashboard/forecast-quality'); if(res.ok){forecastQuality=await res.json(); forecastQualityLoadedAt=now;}}catch(e){} return forecastQuality;}
      function renderForecastQuality(q){const el=$('forecast-quality-block'); if(!el)return; const pv24=q?.curves?.pv?.['24h']; if(!q||!q.for_date||!pv24){el.hidden=true; return;} const bias=pv24.bias>=0?`+${pv24.bias}`:`${pv24.bias}`; el.hidden=false; el.textContent=`Forecast ${q.for_date}: PV MAE 24h = ${Math.round(pv24.mae)} W, bias ${bias} W (n=${pv24.sample_count})`;}
      function upsertCurvePoint(source,powerKw){if(!curves)curves={series:{solar:[],battery:[],grid:[],household:[]}}; if(!curves.series)curves.series={}; const items=curves.series[source]||(curves.series[source]=[]), ts=new Date(), minute=ts.toISOString().slice(0,16), point={timestamp:ts.toISOString(),power_w:Math.round(Math.max(0,powerKw)*1000)}; const idx=items.findIndex(p=>String(p.timestamp||'').slice(0,16)===minute); if(idx>=0)items[idx]=point; else items.push(point); items.sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function appendCurrentChartPoints(){upsertCurvePoint('solar',last.solar); upsertCurvePoint('household',last.household);}
      function dayKwh(items, valueFn=p=>p.power_w||0){let total=0; for(let i=1;i<items.length;i++){const a=items[i-1],b=items[i],dt=(new Date(b.timestamp)-new Date(a.timestamp))/3600000; if(dt>0&&dt<1.1)total+=(valueFn(a)+valueFn(b))/2/1000*dt;} return total;}
      function householdDayKwh(items){return dayKwh(items,p=>Math.max(0,p.power_w||0));}
      function solarDayKwh(items){return dayKwh(items,p=>Math.max(0,p.power_w||0));}
      function gridDayKwh(items, direction){return dayKwh(items,p=>{const w=p.net_w??p.power_w??0; return direction==='import'?Math.max(0,w):Math.max(0,-w);});}
      function householdMismatchText(household){if(!household?.mismatch)return ''; const pct=n(household.deviation_pct), a=n(household.method_a_w), b=n(household.method_b_w); const parts=['Mismatch: Home Consumption is inconsistent after accounting for solar, battery charge/discharge, grid import, and grid export.']; if(pct!=null)parts.push(`Deviation ${pct.toFixed(1)}%.`); if(a!=null&&b!=null)parts.push(`Local supply check: ${Math.round(a)} W; full DSMR balance: ${Math.round(b)} W.`); parts.push('Check whether DSMR, solar, and battery measurements are current and use the same direction/sign convention.'); return parts.join(' ');}
      function drawSparkline(id,items,{signed=false,recentMs=null}={}){const svg=$(id), W=240,H=58, pad=3; if(!svg)return; if(!items||items.length<2){svg.innerHTML='';return;} const now=Date.now(), source=recentMs?items.filter(p=>new Date(p.timestamp)>=now-recentMs):items, data=(source.length>1?source:items).slice(-96); const values=data.map(p=>signed?(p.power_w||0):Math.max(0,p.power_w||0)), max=Math.max(1000,...values.map(v=>Math.abs(v))), min=signed?-max:0; const first=new Date(data[0].timestamp).getTime(), lastTs=new Date(data[data.length-1].timestamp).getTime(), span=Math.max(1,lastTs-first); const x=p=>pad+(W-pad*2)*(new Date(p.timestamp).getTime()-first)/span; const yVal=v=>H-pad-(H-pad*2)*(v-min)/(max-min||1); const d=data.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)} ${yVal(signed?(p.power_w||0):Math.max(0,p.power_w||0)).toFixed(1)}`).join(' '); const fill=`M${x(data[0]).toFixed(1)} ${yVal(0).toFixed(1)} ${data.map(p=>`L${x(p).toFixed(1)} ${yVal(signed?(p.power_w||0):Math.max(0,p.power_w||0)).toFixed(1)}`).join(' ')} L${x(data[data.length-1]).toFixed(1)} ${yVal(0).toFixed(1)} Z`; svg.innerHTML=`<path class="spark-fill" d="${fill}"/><path d="${d}"/>`;}
      function drawHouseholdSpark(items){drawSparkline('household-spark',items,{recentMs:3600000});}
      function normalizeChartItems(items, source){return (items||[]).map(p=>{const power=source==='grid'?-(p.net_w??p.power_w??0):(p.power_w||0); return {...p,source,power_w:power};}).filter(p=>p.timestamp&&Number.isFinite(new Date(p.timestamp).getTime())&&Number.isFinite(p.power_w));}
      function isSameChartDay(timestamp, day){const d=new Date(timestamp); return d.getFullYear()===day.getFullYear()&&d.getMonth()===day.getMonth()&&d.getDate()===day.getDate();}
      function prepareChartItems(items, day=new Date()){const byMinute=new Map(); for(const item of items||[]){if(!isSameChartDay(item.timestamp,day))continue; const key=new Date(item.timestamp).toISOString().slice(0,16); byMinute.set(key,item);} return [...byMinute.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function chartDomain(){const end=chartRange==='12h'?Date.now():new Date(curves?.end||Date.now()).getTime(); const start=chartRange==='12h'?end-12*3600000:new Date(curves?.start||new Date().setHours(0,0,0,0)).getTime(); return [start,end];}
      function prepareChartRangeItems(items,start,end){const byBucket=new Map(); const bucketLen=chartRange==='30d'?3600000:chartRange==='7d'?900000:60000; for(const item of items||[]){const ts=new Date(item.timestamp).getTime(); if(ts<start||ts>end)continue; const key=Math.floor(ts/bucketLen)*bucketLen; byBucket.set(key,item);} return [...byBucket.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function chartTickLabel(ts){const d=new Date(ts); if(chartRange==='7d'||chartRange==='30d')return d.toLocaleDateString([], {day:'2-digit',month:'short'}); return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});}
      function mergeChartItems(...groups){const byMinute=new Map(); for(const group of groups){for(const item of group||[]){const key=new Date(item.timestamp).toISOString().slice(0,16); if(!byMinute.has(key))byMinute.set(key,item);}} return [...byMinute.values()].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));}
      function chartPointMeta(point){const kw=(point.power_w||0)/1000, absKw=Math.abs(kw).toFixed(2), time=new Date(point.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); if(point.source==='battery'){const state=Math.abs(point.power_w||0)<30?'Standby':point.power_w>0?'Discharging':'Charging'; const delivered=point.power_w>0?point.power_w:(point.delivered_w??0); const accepted=point.power_w<0?Math.abs(point.power_w):(point.returned_w??0); const soc=n(point.soc)??last.soc; return {label:'Battery', color:'var(--store-d)', time, lines:[`State: ${state}`, `Power delivered: ${Math.round(Math.max(0,delivered))} W (${absKw} kW)`, `Charge power: ${Math.round(Math.max(0,accepted))} W`, `Charge state: ${Math.round(soc)}%`]};} if(point.source==='solar')return {label:'Production', color:'var(--produce-d)', time, lines:[`Power: ${Math.round(point.power_w||0)} W (${absKw} kW)`]}; if(point.source==='grid'){const state=point.power_w>=0?'Exporting':'Importing'; return {label:'Grid', color:point.power_w>=0?'var(--produce-d)':'var(--import-d)', time, lines:[`State: ${state}`, `Power: ${Math.round(Math.abs(point.power_w||0))} W (${absKw} kW)`]};} if(point.source==='household')return {label:'Home Consumption', color:'var(--home-d)', time, lines:[`Power: ${Math.round(Math.max(0,point.power_w||0))} W (${absKw} kW)`]}; if(point.source==='load_forecast')return {label:'Load forecast', color:'var(--home-d)', time, lines:[`Expected consumption: ${Math.round(point.power_w||0)} W (${absKw} kW)`]}; if(point.source==='grid_forecast'){const state=point.power_w>=0?'Planned export':'Planned import'; return {label:'Grid forecast', color:'var(--import-d)', time, lines:[`State: ${state}`, `Power: ${Math.round(Math.abs(point.power_w||0))} W (${absKw} kW)`]};} if(point.source==='curtailment')return {label:'Curtailment', color:'#E8B04A', time, lines:[`Curtailed: ${Math.round(point.power_w||0)} W (${absKw} kW)`]}; if(point.source==='prices')return {label:'Day-ahead price', color:'#70A7D7', time:new Date(point.starts_at||point.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}), lines:[`Price: ${Number(point.price_eur_kwh).toFixed(4)} EUR/kWh`]}; return {label:'Solar forecast', color:'var(--steel)', time, lines:[`Expected production: ${Math.round(point.power_w||0)} W (${absKw} kW)`]};}
      function showChartTooltip(event, point, xPos, yPos){const tip=$('day-chart-tooltip'), svg=$('day-chart'); if(!tip||!svg)return; const meta=chartPointMeta(point); tip.innerHTML=`<b style="color:${meta.color}">${meta.label} · ${meta.time}</b>${meta.lines.map(line=>`<span>${escapeHtml(line)}</span>`).join('')}`; const dot=$('day-chart-hover-dot'); if(dot){dot.setAttribute('cx',xPos); dot.setAttribute('cy',yPos); dot.setAttribute('fill',meta.color); dot.style.display='block';} const rect=svg.getBoundingClientRect(), wrap=svg.parentElement.getBoundingClientRect(); tip.style.left=(rect.left-wrap.left+(xPos/960)*rect.width)+'px'; tip.style.top=(rect.top-wrap.top+(yPos/300)*rect.height)+'px'; tip.hidden=false;}
      function hideChartTooltip(){const tip=$('day-chart-tooltip'), dot=$('day-chart-hover-dot'); if(tip)tip.hidden=true; if(dot)dot.style.display='none';}
      function updatePlanStatusBadge(){const badge=$('plan-status-badge'); if(!badge)return; const status=curves?.plan_status; if(!status||status==='ok'){badge.hidden=true; return;} badge.hidden=false; const labels={stale:'Plan stale (>30m)',fallback:'Planner fallback'}, titles={stale:'older than 30 minutes',fallback:'in FALLBACK mode (solver could not produce a real forecast, e.g. Open-Meteo was unreachable)'}; badge.textContent=labels[status]||'No plan'; badge.title='Planner v3 plan is '+(titles[status]||'unavailable')+' — forecast curves are hidden rather than invented.';}
      function drawChart(){
        updatePlanStatusBadge();
        const svg=$('day-chart'), W=960,H=300, left=42,right=58,top=16,bot=28, mid=150, nowMs=Date.now(), [startMs,endMs]=chartDomain(), visible=chartSeriesVisible;
        const xTime=ts=>left+(W-left-right)*(ts-startMs)/(endMs-startMs||1), y=kw=>mid-kw/5*(mid-top);
        let out='';
        for(let i=0;i<=4;i++){const ts=startMs+i*(endMs-startMs)/4, xx=xTime(ts); out+=`<line class="gridline gridline-v" x1="${xx}" y1="${top}" x2="${xx}" y2="${H-bot}"/><text class="axis-label" x="${xx}" y="${H-7}" text-anchor="middle">${chartTickLabel(ts)}</text>`;}
        for(let kw=-5;kw<=5;kw+=2.5){const yy=y(kw); out+=`<line class="gridline gridline-h" x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}"/><text class="axis-label" x="8" y="${yy+4}">${kw}</text>`;}
        if(visible.prices){for(let price=-0.10;price<=0.3001;price+=0.10){const yy=H-bot-(H-bot-top)*(price+0.10)/0.40; out+=`<text class="axis-label" x="${W-8}" y="${yy+4}" fill="#70A7D7" text-anchor="end">${price.toFixed(2)}</text>`;}}
        out+=`<text class="axis-label" x="${left}" y="${top-4}">kW</text>${visible.prices?`<text class="axis-label" x="${W-8}" y="${top-4}" fill="#70A7D7" text-anchor="end">EUR/kWh</text>`:''}`;
        out+=`<line class="zero-line" x1="${left}" y1="${mid}" x2="${W-right}" y2="${mid}"/>`;
        const pointPath=items=>items&&items.length?items.map((p,i)=>`${i?'L':'M'}${xTime(new Date(p.timestamp).getTime()).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '):'';
        const forecastItems=prepareChartRangeItems(normalizeChartItems(curves?.forecast,'forecast'),startMs,endMs), solarItems=prepareChartRangeItems(normalizeChartItems(curves?.series?.solar,'solar'),startMs,endMs), batteryItems=mergeChartItems(prepareChartRangeItems(normalizeChartItems(curves?.series?.battery,'battery'),startMs,endMs),prepareChartRangeItems(normalizeChartItems(curves?.battery_forecast,'battery'),startMs,endMs)), gridItems=prepareChartRangeItems(normalizeChartItems(curves?.series?.grid,'grid'),startMs,endMs), householdItems=prepareChartRangeItems(normalizeChartItems(curves?.series?.household,'household'),startMs,endMs), priceItems=(tradePrices||[]).filter(p=>{const ts=new Date(p.starts_at).getTime(); return ts>=startMs&&ts<=endMs;});
        const loadForecastItems=prepareChartRangeItems(normalizeChartItems(curves?.load_forecast,'load_forecast'),startMs,endMs), gridForecastItems=prepareChartRangeItems(normalizeChartItems((curves?.grid_forecast||[]).map(p=>({...p,power_w:-(p.power_w||0)})),'grid_forecast'),startMs,endMs), curtailmentItems=prepareChartRangeItems(normalizeChartItems(curves?.curtailment_forecast,'curtailment'),startMs,endMs);
        const pv10Items=prepareChartRangeItems(normalizeChartItems(curves?.pv_p10_forecast,'pv_p10'),startMs,endMs), pv90Items=prepareChartRangeItems(normalizeChartItems(curves?.pv_p90_forecast,'pv_p90'),startMs,endMs);
        const bandPath=(loItems,hiItems)=>{if(!loItems||!hiItems||loItems.length<2||hiItems.length!==loItems.length)return ''; const top=hiItems.map((p,i)=>`${i?'L':'M'}${xTime(new Date(p.timestamp).getTime()).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '); const bottom=[...loItems].reverse().map(p=>`L${xTime(new Date(p.timestamp).getTime()).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '); return `${top} ${bottom} Z`;};
        const priceSourceAt=ts=>{const points=curves?.price_source; if(!points||!points.length)return 'fallback'; let nearest=points[0], best=Infinity; for(const point of points){const delta=Math.abs(new Date(point.timestamp).getTime()-ts); if(delta<best){best=delta; nearest=point;}} return nearest.source||'fallback';};
        const signedArea=(items,positive,klass)=>items&&items.length?`<path class="${klass}" d="M${xTime(new Date(items[0].timestamp).getTime()).toFixed(1)} ${y(0)} `+items.map(p=>{const kw=(p.power_w||0)/1000; return `L${xTime(new Date(p.timestamp).getTime()).toFixed(1)} ${y(positive?Math.max(0,kw):Math.min(0,kw)).toFixed(1)}`}).join(' ')+` L${xTime(new Date(items[items.length-1].timestamp).getTime()).toFixed(1)} ${y(0)} Z"/>`:'';
        const paths=[['forecast-line',forecastItems,visible.forecast],['prod-line',solarItems,visible.solar],['bat-line',batteryItems,visible.battery],['grid-line',gridItems,visible.grid],['home-line',householdItems,visible.household],['load-forecast-line',loadForecastItems,visible.load_forecast],['grid-forecast-line',gridForecastItems,visible.grid_forecast],['curtailment-line',curtailmentItems,visible.curtailment]];
        if(visible.prices&&priceItems.length){const vals=priceItems.map(p=>p.price_eur_kwh), minP=Math.min(...vals), maxP=Math.max(...vals), lo=Math.min(0,minP), hi=maxP===lo?lo+0.01:maxP, barW=Math.max(2,(W-left-right)/Math.max(24,priceItems.length)*.24), yPrice=v=>H-bot-(H-bot-top)*(v-lo)/(hi-lo||1), priceColor=v=>{const t=(v-minP)/(maxP-minP||1), from=[141,179,205], to=[72,129,170], c=from.map((n,i)=>Math.round(n+(to[i]-n)*t)); return `rgb(${c[0]},${c[1]},${c[2]})`;}; for(const p of priceItems){const x0=xTime(new Date(p.starts_at).getTime())-barW/2, y0=yPrice(Math.max(lo,p.price_eur_kwh)), h0=Math.max(2,H-bot-y0), isFallback=priceSourceAt(new Date(p.starts_at).getTime())==='fallback'; out+=`<rect x="${x0.toFixed(1)}" y="${y0.toFixed(1)}" width="${barW.toFixed(1)}" height="${h0.toFixed(1)}" rx="2" fill="${priceColor(p.price_eur_kwh)}" opacity="0.56" ${isFallback?'stroke="#70A7D7" stroke-width="1" stroke-dasharray="2 2"':''} onmouseleave="hideChartTooltip()" onmousemove="handleChartHover(event,'price-bars')"/>`; } out+=`<text class="axis-label" x="${W-right-2}" y="${top+10}" fill="#70A7D7" text-anchor="end">${maxP.toFixed(3)} EUR/kWh</text>`;}
        out+=visible.forecast&&pv10Items.length&&pv90Items.length?`<path class="pv-uncertainty-band" d="${bandPath(pv10Items,pv90Items)}"/>`:'';
        out+=visible.forecast&&pointPath(forecastItems)?`<path class="forecast-line" d="${pointPath(forecastItems)}"/>`:'';
        out+=visible.solar&&pointPath(solarItems)?`<path class="prod-line" d="${pointPath(solarItems)}"/>`:'';
        out+=visible.battery&&pointPath(batteryItems)?signedArea(batteryItems,true,'bat-charge-fill')+signedArea(batteryItems,false,'bat-discharge-fill')+`<path class="bat-line" d="${pointPath(batteryItems)}"/>`:'';
        out+=visible.grid&&pointPath(gridItems)?signedArea(gridItems,true,'grid-import-fill')+signedArea(gridItems,false,'grid-export-fill')+`<path class="grid-line" d="${pointPath(gridItems)}"/>`:'';
        out+=visible.household&&pointPath(householdItems)?`<path class="home-line" d="${pointPath(householdItems)}"/>`:'';
        out+=visible.load_forecast&&pointPath(loadForecastItems)?`<path class="load-forecast-line" d="${pointPath(loadForecastItems)}"/>`:'';
        out+=visible.grid_forecast&&pointPath(gridForecastItems)?`<path class="grid-forecast-line" d="${pointPath(gridForecastItems)}"/>`:'';
        out+=visible.curtailment&&pointPath(curtailmentItems)?`<path class="curtailment-line" d="${pointPath(curtailmentItems)}"/>`:'';
        if(nowMs>=startMs&&nowMs<=endMs){const nowX=xTime(nowMs), labelW=42, labelX=Math.max(left,Math.min(W-right-labelW,nowX-labelW/2)); out+=`<g class="now-marker"><line class="now" x1="${nowX.toFixed(1)}" y1="${top+8}" x2="${nowX.toFixed(1)}" y2="${H-bot}"/><rect class="now-label-bg" x="${labelX.toFixed(1)}" y="3" width="${labelW}" height="16" rx="8"/><text class="now-label" x="${(labelX+labelW/2).toFixed(1)}" y="14" text-anchor="middle">NOW</text></g>${visible.solar?`<circle cx="${nowX.toFixed(1)}" cy="${y(last.solar).toFixed(1)}" r="4" fill="var(--produce-d)"/>`:''}`;}
        out+=`<circle id="day-chart-hover-dot" class="chart-dot" r="5" style="display:none"/>`; for(const [klass,items,isVisible] of paths){if(!isVisible)continue;const d=pointPath(items); if(!d)continue; out+=`<path class="chart-hover" d="${d}" onmouseleave="hideChartTooltip()" onmousemove="handleChartHover(event,'${klass}')"/>`;}
        svg.innerHTML=out;
        window.chartHoverSeries={'forecast-line':forecastItems,'prod-line':solarItems,'bat-line':batteryItems,'grid-line':gridItems,'home-line':householdItems,'load-forecast-line':loadForecastItems,'grid-forecast-line':gridForecastItems,'curtailment-line':curtailmentItems,'price-bars':priceItems};
      }
      function handleChartHover(event,key){const svg=$('day-chart'), items=window.chartHoverSeries?.[key]||[]; if(!items.length)return; const pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); const [startMs,endMs]=chartDomain(), targetTs=startMs+Math.max(0,Math.min(1,(loc.x-42)/(960-42-58)))*(endMs-startMs); let nearest=items[0], best=Infinity; for(const item of items){const ts=new Date(key==='price-bars'?item.starts_at:item.timestamp).getTime(), delta=Math.abs(ts-targetTs); if(delta<best){best=delta; nearest=item;}} const isPrice=key==='price-bars', ts=new Date(isPrice?nearest.starts_at:nearest.timestamp).getTime(), yPos=isPrice?Math.max(24,Math.min(272,loc.y)):150-((nearest.power_w||0)/1000)/5*(150-16); showChartTooltip(event,nearest,42+(960-42-58)*(ts-startMs)/(endMs-startMs||1),yPos);}
      async function update(){const d=new Date(); $('clock').textContent=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); $('date').textContent=d.toLocaleDateString([], {day:'2-digit',month:'short',year:'numeric'}); let battery={},grid={},household={}; try{[grid,battery,household]=await Promise.all([fetch('/api/grid/status').then(r=>r.ok?r.json():{}),fetch('/api/battery/status').then(r=>r.ok?r.json():{}),fetch('/api/household/status').then(r=>r.ok?r.json():{})])}catch(e){}
        const solarW=n(grid.solar_power_w); last.solar=solarW==null?0:solarW/1000; last.battery=(n(battery.power_w)??0)/1000; const rawGrid=(n(grid.grid_net_power_w)??650)/1000; last.grid=-rawGrid; last.household=(n(household.power_w)??Math.max(0,last.solar*1000+last.battery*1000-last.grid*1000))/1000; last.soc=n(battery.soc)??last.soc; last.soh=n(battery.soh)??98; batteryLimits.overrideSoc=!!battery.override_soc_limits; const home=Math.max(0,last.household);
        $('household-status-word').textContent=household.approx?'Approx':'Live'; setStatusPill('household-pill',household.approx?'warning':'live',home>.03); const mismatchText=householdMismatchText(household); const badge=$('household-badge'); badge.hidden=!household.mismatch; setStatusPill('household-badge','mismatch',!!household.mismatch); badge.title=mismatchText; badge.setAttribute('aria-label', mismatchText||'Geen household mismatch');
        renderReadings(); const solarActive=last.solar>0.05; $('solar-bar').style.width=Math.min(100,last.solar/solarMax*100)+'%'; $('solar-status').textContent=solarActive?'Producing':'Standby'; setStatusPill('solar-pill',solarActive?'producing':'standby',solarActive);
        const batteryVisual=deriveBatteryVisualState(battery); applyBatteryAccent(batteryVisual); $('battery-status-word').textContent=batteryVisual.label; setStatusPill('battery-pill',batteryVisual.state,batteryVisual.state!=='idle'); setBar('battery-bar',batteryVisual.state==='idle'?0:last.battery,signedMax,'var(--battery-accent)'); setSoc(last.soc); $('soh-text').textContent=Math.round(last.soh)+'%'; $('battery-capacity-text').textContent=`${(nominalKwh*last.soc/100).toFixed(1)} / ${nominalKwh} kWh`; $('soh-bar').style.width=last.soh+'%';
        const gExport=last.grid>=0, gridActive=Math.abs(last.grid)>=.03, gridVariant=!gridActive?'standby':gExport?'exporting':'importing'; $('grid-status-word').textContent=!gridActive?'Standby':gExport?'Exporting':'Importing'; $('grid-phrase').className='phrase '+(gExport?'produce-c':'import-c'); setStatusPill('grid-pill',gridVariant,gridActive); $('grid-tile').className='tile metric-card '+(gExport?'produce':'import'); setBar('grid-bar',last.grid,signedMax,gExport?'var(--produce-d)':'var(--import-d)');
        $('flow-solar-home').style.stroke='var(--produce-d)'; $('flow-solar-home').style.strokeWidth=2+Math.min(10,last.solar*2); $('flow-home-battery').style.stroke='var(--battery-accent)'; $('flow-home-battery').style.strokeWidth=2+Math.min(10,Math.abs(last.battery)*3); $('flow-home-grid').style.stroke=gExport?'var(--produce-d)':'var(--import-d)'; $('flow-home-grid').style.strokeWidth=2+Math.min(10,Math.abs(last.grid)*3);
        await Promise.all([loadCurves(),loadTradePrices()]); renderForecastQuality(await loadForecastQuality()); appendCurrentChartPoints(); const hItems=curves?.series?.household||[], sItems=curves?.series?.solar||[], gItems=curves?.series?.grid||[]; const produced=solarDayKwh(sItems), imported=gridDayKwh(gItems,'import'), exported=gridDayKwh(gItems,'export'), householdKwh=householdDayKwh(hItems), used=Math.max(0,produced-exported), cycles=nominalKwh?dayKwh(curves?.series?.battery||[],p=>Math.abs(p.power_w||0))/nominalKwh:0, co2=produced*.39; $('solar-kwh').textContent=produced.toFixed(1); $('grid-import-kwh').textContent=imported.toFixed(1); $('grid-export-kwh').textContent=exported.toFixed(1); $('kwh-produced').textContent=produced.toFixed(1); $('kwh-exported').textContent=exported.toFixed(1); $('kwh-imported').textContent=imported.toFixed(1); $('summary-consumed').textContent=householdKwh.toFixed(1); $('summary-cycles').textContent=cycles.toFixed(2); $('summary-co2').textContent=co2.toFixed(1)+' kg'; const self=Math.round(100*Math.max(0,used)/(used+imported||1)); $('self-top').textContent=self+'%'; $('summary-self').textContent=self+'%'; $('m-self').textContent=self+'%'; drawSparkline('solar-spark',sItems); drawSparkline('grid-spark',normalizeChartItems(gItems,'grid'),{signed:true}); drawHouseholdSpark(hItems); $('household-kwh').textContent=householdKwh.toFixed(1); drawChart(); }
      initChartLegend(); initChartRange(); refreshMailboxCount(); setInterval(refreshMailboxCount,45000); loadBatteryLimits(); loadBatteryVisualConfig(); setInterval(loadBatteryLimits,60000); setInterval(loadBatteryVisualConfig,60000); update(); setInterval(update,4000);
    </script>
    """.replace("__MARK__", brand_mark()).replace("__BRAND__", brand_name).replace("__NAV__", render_nav("Dashboard")).replace("__UNIT_TOGGLE__", unit_toggle).replace("__LAYOUT_TOGGLE__", layout_toggle).replace("__METRIC_CARDS__", solar_card + battery_card + grid_card + household_card).replace("__KPI_STRIP__", kpi_strip)


def history_body() -> str:
    return """
    <section class='card'>
      <div class='history-tabs' role='tablist' aria-label='History granularity'>
        <button class='history-tab active' type='button' role='tab' aria-selected='true' data-history-window='day'>Dag</button>
        <button class='history-tab' type='button' role='tab' aria-selected='false' data-history-window='week'>Week</button>
        <button class='history-tab' type='button' role='tab' aria-selected='false' data-history-window='month'>Maand</button>
        <button class='history-tab' type='button' role='tab' aria-selected='false' data-history-window='year'>Jaar</button>
      </div>
      <div class='history-chart-card'>
        <div class='history-toolbar'>
          <div><span class='tile-name' id='history-title'>Dag overzicht · kW</span><div class='history-hint' id='history-range'>Laden…</div></div>
          <div class='history-period-controls' aria-label='Browse history periods'>
            <button id='history-prev' type='button' aria-label='Vorige periode'>‹</button>
            <span id='history-period-label' class='history-period-label'>Vandaag</span>
            <button id='history-today' type='button'>Vandaag</button>
            <button id='history-next' type='button' aria-label='Volgende periode' disabled>›</button>
          </div>
          <div class='chart-legend' aria-label='Toggle history series'>
            <button type='button' data-history-series='forecast' aria-pressed='true' style='color:var(--steel)'><i></i>Solar forecast</button>
            <button type='button' data-history-series='solar' aria-pressed='true' style='color:var(--produce-d)'><i></i>Production</button>
            <button type='button' data-history-series='battery' aria-pressed='true' style='color:var(--store-d)'><i></i>Battery</button>
            <button type='button' data-history-series='grid' aria-pressed='true' style='color:var(--import-d)'><i></i>Grid</button>
            <button type='button' data-history-series='household' aria-pressed='true' style='color:var(--steel)'><i></i>Home</button>
            <button type='button' data-history-series='load_forecast' aria-pressed='true' style='color:var(--home-d)'><i></i>Load forecast</button>
            <button type='button' data-history-series='grid_forecast' aria-pressed='true' style='color:var(--import-d)'><i></i>Grid forecast</button>
            <button type='button' data-history-series='curtailment' aria-pressed='false' style='color:#E8B04A'><i></i>Curtailment</button>
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
      const H={window:'day', offset:0, data:null, zoom:null, dragging:null, visible:{forecast:true,solar:true,battery:true,grid:true,household:true,load_forecast:true,grid_forecast:true,curtailment:false}};
      const $=id=>document.getElementById(id), n=v=>{const x=Number(v);return Number.isFinite(x)?x:null};
      const colors={forecast:'var(--steel)',solar:'var(--produce-d)',battery:'var(--store-d)',grid:'var(--import-d)',household:'var(--steel)',load_forecast:'var(--home-d)',grid_forecast:'var(--import-d)',curtailment:'#E8B04A'};
      function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
      function normalize(items,source){return (items||[]).map(p=>{const power=source==='grid'?-(p.net_w??p.power_w??0):(p.power_w||0); return {...p,source,power_w:power,t:new Date(p.timestamp).getTime()};}).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.power_w)).sort((a,b)=>a.t-b.t);}
      function allSeries(){const d=H.data||{}; return {forecast:normalize(d.forecast,'forecast'),solar:normalize(d.series?.solar,'solar'),battery:normalize([...(d.series?.battery||[]),...(d.battery_forecast||[])],'battery'),grid:normalize(d.series?.grid,'grid'),household:normalize(d.series?.household,'household'),load_forecast:normalize(d.load_forecast,'load_forecast'),grid_forecast:normalize((d.grid_forecast||[]).map(p=>({...p,power_w:-(p.power_w||0)})),'grid_forecast'),curtailment:normalize(d.curtailment_forecast,'curtailment')};}
      function domain(series){const points=Object.values(series).flat(); const start=new Date(H.data?.start||Date.now()).getTime(), end=new Date(H.data?.end||Date.now()).getTime(); return H.zoom||[Math.min(start,...points.map(p=>p.t)),Math.max(end,...points.map(p=>p.t))];}
      function fmtDate(ts){const opts=H.window==='day'?{weekday:'short',hour:'2-digit',minute:'2-digit'}:H.window==='week'||H.window==='month'?{day:'2-digit',month:'short'}:{month:'short',year:'numeric'}; return new Date(ts).toLocaleString([],opts);}
      function periodLabel(){const start=new Date(H.data?.start||Date.now()), end=new Date(H.data?.end||Date.now()); if(H.window==='day')return start.toLocaleDateString([], {weekday:'short',day:'2-digit',month:'short',year:'numeric'}); if(H.window==='week')return `${start.toLocaleDateString([], {day:'2-digit',month:'short'})} → ${end.toLocaleDateString([], {day:'2-digit',month:'short',year:'numeric'})}`; if(H.window==='month')return start.toLocaleDateString([], {month:'long',year:'numeric'}); return start.toLocaleDateString([], {year:'numeric'});}
      function refreshPeriodControls(){const label=$('history-period-label'), next=$('history-next'), today=$('history-today'); if(label)label.textContent=periodLabel(); if(next)next.disabled=H.offset>=0; if(today)today.textContent=({'day':'Vandaag','week':'Deze week','month':'Deze maand','year':'Dit jaar'}[H.window]||'Vandaag');}
      function kwh(items,fn=p=>p.power_w||0){let total=0; for(let i=1;i<items.length;i++){const a=items[i-1],b=items[i],dt=(b.t-a.t)/3600000; if(dt>0&&dt<900)total+=(fn(a)+fn(b))/2/1000*dt;} return total;}
      function updateStats(series){const produced=kwh(series.solar,p=>Math.max(0,p.power_w||0)), imported=kwh(series.grid,p=>Math.max(0,-p.power_w||0)), exported=kwh(series.grid,p=>Math.max(0,p.power_w||0)), used=Math.max(0,produced-exported); $('hist-produced').textContent=produced.toFixed(1); $('hist-imported').textContent=imported.toFixed(1); $('hist-exported').textContent=exported.toFixed(1); $('hist-used').textContent=used.toFixed(1);}
      function draw(){const svg=$('history-chart'), mini=$('history-mini'), W=960,Hh=420,left=56,right=18,top=22,bot=42; refreshPeriodControls(); const s=allSeries(); updateStats(s); const [minT,maxT]=domain(s); const visible=Object.entries(s).filter(([k])=>H.visible[k]).flatMap(([,v])=>v.filter(p=>p.t>=minT&&p.t<=maxT)); if(!visible.length){svg.innerHTML='<foreignObject width="960" height="420"><div class="history-empty">Geen historische punten beschikbaar voor deze periode.</div></foreignObject>'; mini.innerHTML=''; $('history-range').textContent=`${fmtDate(minT)} → ${fmtDate(maxT)}`; return;} const maxKw=Math.max(1,...visible.map(p=>Math.abs(p.power_w)/1000))*1.15; const x=t=>left+(W-left-right)*(t-minT)/(maxT-minT||1), y=kw=>top+(Hh-top-bot)*(1-(kw+maxKw)/(maxKw*2)); let out=''; for(let i=0;i<=4;i++){const kw=-maxKw+i*(maxKw/2), yy=y(kw); out+=`<line class="gridline" x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}"/><text x="10" y="${yy+4}" fill="var(--steel)" font-family="var(--mono)" font-size="10">${kw.toFixed(1)}</text>`;} for(let i=0;i<=6;i++){const t=minT+i*(maxT-minT)/6; out+=`<text x="${x(t)}" y="${Hh-12}" fill="var(--steel)" font-family="var(--mono)" font-size="10" text-anchor="middle">${fmtDate(t)}</text>`;} out+=`<line class="zero-line" x1="${left}" y1="${y(0)}" x2="${W-right}" y2="${y(0)}"/>`; for(const [key,items] of Object.entries(s)){if(!H.visible[key])continue; const pts=items.filter(p=>p.t>=minT&&p.t<=maxT); if(pts.length<2)continue; const d=pts.map((p,i)=>`${i?'L':'M'}${x(p.t).toFixed(1)} ${y((p.power_w||0)/1000).toFixed(1)}`).join(' '); const cls=key==='solar'?'prod-line':key==='battery'?'bat-line':key==='grid'?'grid-line':key==='household'?'home-line':key==='load_forecast'?'load-forecast-line':key==='grid_forecast'?'grid-forecast-line':key==='curtailment'?'curtailment-line':'forecast-line'; out+=`<path class="${cls}" d="${d}"/><path class="chart-hover" d="${d}" onmousemove="showTip(event,'${key}')" onmouseleave="hideTip()"/>`; } svg.innerHTML=out; drawMini(s,minT,maxT); const planStatusNotes={stale:' · plan verouderd (>30m), forecast verborgen',fallback:' · planner in fallback-modus, forecast verborgen'}, planNote=H.data?.plan_status&&H.data.plan_status!=='ok'?(planStatusNotes[H.data.plan_status]||' · geen plan beschikbaar, forecast verborgen'):''; $('history-range').textContent=`${fmtDate(minT)} → ${fmtDate(maxT)} · sleep onderaan om te zoomen${planNote}`;}
      function drawMini(series,minT,maxT){const mini=$('history-mini'), W=960,Hh=78,left=56,right=18,top=8,bot=12; const all=Object.values(series).flat(), fullMin=Math.min(...all.map(p=>p.t)), fullMax=Math.max(...all.map(p=>p.t)), max=Math.max(1,...all.map(p=>Math.abs(p.power_w)/1000)); const x=t=>left+(W-left-right)*(t-fullMin)/(fullMax-fullMin||1), y=kw=>top+(Hh-top-bot)*(1-kw/max); const pts=series.solar.length?series.solar:all; const d=pts.map((p,i)=>`${i?'L':'M'}${x(p.t).toFixed(1)} ${y(Math.abs(p.power_w)/1000).toFixed(1)}`).join(' '); mini.innerHTML=`<path class="forecast-fill" d="${d}"/><rect class="history-window" x="${x(minT)}" y="${top}" width="${Math.max(2,x(maxT)-x(minT))}" height="${Hh-top-bot}"/><rect id="history-brush" class="history-brush" hidden y="${top}" height="${Hh-top-bot}"/>`;}
      function showTip(event,key){const items=allSeries()[key]||[]; const svg=$('history-chart'), pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); const [minT,maxT]=domain(allSeries()); const ts=minT+(loc.x-56)/(960-56-18)*(maxT-minT); let nearest=items[0], best=Infinity; for(const item of items){const d=Math.abs(item.t-ts); if(d<best){best=d; nearest=item;}} if(!nearest)return; const tip=$('history-tooltip'), rect=svg.getBoundingClientRect(), wrap=svg.parentElement.getBoundingClientRect(); const historyLabels={forecast:'Solar forecast',solar:'Production',battery:'Battery',grid:'Grid',household:'Home',load_forecast:'Load forecast',grid_forecast:'Grid forecast',curtailment:'Curtailment'}; tip.innerHTML=`<b style="color:${colors[key]}">${historyLabels[key]||key} · ${fmtDate(nearest.t)}</b><br><span>${Math.round(nearest.power_w||0)} W (${((nearest.power_w||0)/1000).toFixed(2)} kW)</span>`; tip.style.left=(event.clientX-wrap.left)+'px'; tip.style.top=(event.clientY-wrap.top)+'px'; tip.hidden=false;}
      function hideTip(){ $('history-tooltip').hidden=true; }
      async function loadHistory(win=H.window, offset=H.offset){H.window=win; H.offset=offset; H.zoom=null; $('history-title').textContent=({'day':'Dag','week':'Week','month':'Maand','year':'Jaar'}[win])+' overzicht · kW'; $('history-range').textContent='Laden…'; refreshPeriodControls(); const res=await fetch(`/api/dashboard/curves?window=${win}&offset=${offset}`); H.data=res.ok?await res.json():{series:{}}; draw();}
      document.querySelectorAll('[data-history-window]').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('[data-history-window]').forEach(b=>{b.classList.toggle('active',b===btn); b.setAttribute('aria-selected',b===btn?'true':'false')}); loadHistory(btn.dataset.historyWindow,0);}));
      $('history-prev').addEventListener('click',()=>loadHistory(H.window,H.offset-1));
      $('history-next').addEventListener('click',()=>{if(H.offset<0)loadHistory(H.window,H.offset+1);});
      $('history-today').addEventListener('click',()=>loadHistory(H.window,0));
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
      <h1 class='page-title'>Day-ahead prices</h1>
      <p class='page-copy'>Live dashboard for the trade price collector. It reads the retained day-ahead price payload and graphs hourly EUR/kWh values.</p>
      <div class='history-chart-card'>
        <div class='history-toolbar'>
          <div><span class='tile-name'>Day-ahead price · EUR/kWh</span><div class='history-hint' id='trade-range'>Loading…</div></div>
          <button class='secondary' type='button' onclick='loadTradePrices()'>Refresh</button>
        </div>
        <div class='chart-wrap'>
          <svg id='trade-chart' class='history-chart' viewBox='0 0 960 420' role='img' aria-label='Day-ahead electricity price curve'></svg>
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
      function drawTradeChart(){const svg=$('trade-chart'), W=960,H=420,left=64,right=20,top=28,bot=48; if(!tradePoints.length){svg.innerHTML='<foreignObject width="960" height="420"><div class="history-empty">No retained day-ahead prices are available yet. Check the trade price collector configuration.</div></foreignObject>'; return;} const min=Math.min(...tradePoints.map(p=>p.price_eur_kwh)), max=Math.max(...tradePoints.map(p=>p.price_eur_kwh)), pad=Math.max(.01,(max-min)*.15), lo=min-pad, hi=max+pad; const first=new Date(tradePoints[0].starts_at).getTime(), last=new Date(tradePoints[tradePoints.length-1].starts_at).getTime(); const x=p=>left+(W-left-right)*(new Date(p.starts_at).getTime()-first)/(last-first||1), y=v=>top+(H-top-bot)*(1-(v-lo)/(hi-lo||1)); let out=''; for(let i=0;i<=4;i++){const v=lo+i*(hi-lo)/4, yy=y(v); out+=`<line class="gridline" x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}"/><text x="10" y="${yy+4}" fill="var(--steel)" font-family="var(--mono)" font-size="10">${v.toFixed(3)}</text>`;} for(const p of tradePoints.filter((_,i)=>i%3===0)){out+=`<text x="${x(p)}" y="${H-14}" fill="var(--steel)" font-family="var(--mono)" font-size="10" text-anchor="middle">${fmtTime(p.starts_at)}</text>`;} const d=tradePoints.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)} ${y(p.price_eur_kwh).toFixed(1)}`).join(' '); out+=`<path class="forecast-line" d="${d}"/><path class="chart-hover" d="${d}" onmousemove="showTradeTip(event)" onmouseleave="$('trade-tooltip').hidden=true"/>`; svg.innerHTML=out;}
      function showTradeTip(event){const svg=$('trade-chart'), pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse()); let nearest=tradePoints[0], best=Infinity; for(const p of tradePoints){const dx=Math.abs(loc.x-(64+(960-64-20)*(new Date(p.starts_at)-new Date(tradePoints[0].starts_at))/(new Date(tradePoints.at(-1).starts_at)-new Date(tradePoints[0].starts_at)||1))); if(dx<best){best=dx; nearest=p;}} const tip=$('trade-tooltip'), wrap=svg.parentElement.getBoundingClientRect(); tip.innerHTML=`<b>Day-ahead · ${fmtTime(nearest.starts_at)}</b><span>${nearest.price_eur_kwh.toFixed(4)} EUR/kWh</span>`; tip.style.left=(event.clientX-wrap.left)+'px'; tip.style.top=(event.clientY-wrap.top)+'px'; tip.hidden=false;}
      async function loadTradePrices(){const res=await fetch('/api/trade/prices'); const data=res.ok?await res.json():{prices:[]}; tradePoints=(data.prices||[]).filter(p=>Number.isFinite(Number(p.price_eur_kwh))).map(p=>({...p,price_eur_kwh:Number(p.price_eur_kwh)})); $('trade-range').textContent=tradePoints.length?`${data.date||tradePoints[0].date} · ${tradePoints.length} hourly prices from ${data.source||'day-ahead'}`:'No retained data'; const vals=tradePoints.map(p=>p.price_eur_kwh); $('trade-min').textContent=vals.length?Math.min(...vals).toFixed(4):'--'; $('trade-max').textContent=vals.length?Math.max(...vals).toFixed(4):'--'; $('trade-avg').textContent=vals.length?(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(4):'--'; $('trade-count').textContent=String(tradePoints.length||'--'); $('trade-json').textContent=JSON.stringify(data,null,2); drawTradeChart();}
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
        'home': '<path d="M4 11.5 12 5l8 6.5"/><path d="M6.5 10.5V20h11v-9.5"/><path d="M10 20v-5h4v5"/>',
    }
    return f'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{shapes[name]}</svg>'
