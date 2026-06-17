const apiBase = window.MINYAD_API_BASE || window.location.origin;
const fmtW = (v) => `${Math.round(Number(v || 0))} W`;
const fmtValue = (v, unit = '') => v == null ? '—' : `${v}${unit}`;
const fmtTime = (v) => v ? new Date(v).toLocaleString('nl-NL', { timeZone: 'Europe/Amsterdam' }) : '—';
let latestGoodWeBattery = null;

function setText(id, value) { document.getElementById(id).textContent = value; }

function drawForecast(rows) {
  const canvas = document.getElementById('forecast');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const values = rows.map(r => Number(r.predicted_w || 0));
  const max = Math.max(1000, ...values);
  ctx.strokeStyle = '#60a5fa'; ctx.lineWidth = 3; ctx.beginPath();
  values.forEach((value, i) => {
    const x = (i / Math.max(1, values.length - 1)) * (canvas.width - 40) + 20;
    const y = canvas.height - 25 - (value / max) * (canvas.height - 50);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#bfd0ee'; ctx.font = '12px system-ui';
  ctx.fillText(`max ${Math.round(max)} W`, 20, 16);
}

function renderGoodWeStatus(data) {
  latestGoodWeBattery = data.battery || null;
  renderBatteryOverview();
  const pill = document.getElementById('goodweOverall');
  const error = document.getElementById('goodweError');
  pill.textContent = data.overall === 'ok' ? 'OK' : 'Aandacht nodig';
  pill.className = `status-pill ${data.overall === 'ok' ? 'ok-bg' : 'warning-bg'}`;
  error.classList.add('hidden');

  setText('goodweBatterySoc', data.battery?.soc_pct == null ? '—%' : `${Number(data.battery.soc_pct).toFixed(0)}%`);
  setText('goodweBatteryMode', `${data.battery?.mode || '—'} · ${fmtW(data.battery?.power_w)}`);
  setText('goodweBatteryLimits', `Limieten: laden ${fmtW(data.battery?.charge_limit_w)}, ontladen ${fmtW(data.battery?.discharge_limit_w)}`);
  setText('goodweGridPower', fmtW(data.grid?.power_w));
  setText('goodweGridMode', `${data.grid?.direction || '—'} · ${data.grid?.mode || '—'}`);
  setText('goodweGridVoltage', `${fmtValue(data.grid?.voltage_v, ' V')} · ${fmtValue(data.grid?.frequency_hz, ' Hz')}`);
  setText('goodweHouseLoad', fmtW(data.load?.house_consumption_w));
  setText('goodweLoadPower', `Load: ${fmtW(data.load?.power_w)}`);
  setText('goodweInverterTemp', `Omvormer: ${fmtValue(data.inverter?.temperature_c, ' °C')}`);
  setText('goodweDiagnose', data.inverter?.diagnose || 'Geen diagnose beschikbaar');
  document.getElementById('goodweIssues').innerHTML = (data.issues?.length ? data.issues : ['Geen actieve aandachtspunten']).map(issue => `<li>${issue}</li>`).join('');
  document.getElementById('goodweRaw').textContent = JSON.stringify(data.raw || {}, null, 2);
}

async function refreshGoodWeStatus() {
  try {
    const res = await fetch(`${apiBase}/api/goodwe/status`);
    if (!res.ok) throw new Error(await res.text());
    renderGoodWeStatus(await res.json());
  } catch (err) {
    const pill = document.getElementById('goodweOverall');
    const error = document.getElementById('goodweError');
    pill.textContent = 'Offline';
    pill.className = 'status-pill error-bg';
    error.textContent = `GoodWe status ophalen mislukt: ${err.message || err}`;
    error.classList.remove('hidden');
  }
}

function getDashboardBattery(battery = {}) {
  const goodwe = latestGoodWeBattery || {};
  const goodwePower = Number(goodwe.power_w || 0);
  return {
    ...battery,
    soc_pct: battery.soc_pct ?? goodwe.soc_pct,
    mode: battery.mode ?? goodwe.mode,
    charge_w: battery.charge_w ?? (goodwePower < 0 ? Math.abs(goodwePower) : 0),
    discharge_w: battery.discharge_w ?? (goodwePower > 0 ? goodwePower : 0),
  };
}

function renderBatteryOverview(battery = {}) {
  const dashboardBattery = getDashboardBattery(battery);
  const chargeW = Number(dashboardBattery.charge_w || 0);
  const dischargeW = Number(dashboardBattery.discharge_w || 0);
  setText('soc', dashboardBattery.soc_pct == null ? '—%' : `${Number(dashboardBattery.soc_pct).toFixed(0)}%`);
  setText('batteryMode', `${dashboardBattery.mode || '—'} (${chargeW ? 'laden ' + fmtW(chargeW) : dischargeW ? 'ontladen ' + fmtW(dischargeW) : 'idle'})`);
  return { battery: dashboardBattery, chargeW, dischargeW };
}

async function refresh() {
  const res = await fetch(`${apiBase}/api/status`);
  const data = await res.json();
  const grid = data.grid || {}, solar = data.solar || {}, battery = data.battery || {}, control = data.last_control || {};
  const importW = Number(grid.import_w || 0), exportW = Number(grid.export_w || 0);
  const overview = renderBatteryOverview(battery);
  const batteryNet = overview.dischargeW - overview.chargeW;
  const houseLoad = Math.max(0, importW - exportW + Number(solar.production_w || 0) - batteryNet);

  setText('solarW', fmtW(solar.production_w));
  setText('solarDay', `Lifetime: ${((Number(solar.lifetime_wh || 0)) / 1000).toFixed(1)} kWh`);
  const gridCard = document.getElementById('gridCard');
  gridCard.classList.remove('grid-consuming-high', 'grid-consuming', 'grid-returning');
  if (exportW > 0) {
    gridCard.classList.add('grid-returning');
  } else if (importW > 1000) {
    gridCard.classList.add('grid-consuming-high');
  } else if (importW > 0) {
    gridCard.classList.add('grid-consuming');
  }
  setText('gridW', exportW > 0 ? `Export ${fmtW(exportW)}` : `Import ${fmtW(importW)}`);
  setText('gridImport', `Import: ${fmtW(importW)}`);
  setText('gridExport', `Export: ${fmtW(exportW)}`);
  setText('gridBalance', `Netto: ${fmtW(importW - exportW)}`);
  setText('controlAction', control.action || '—');
  setText('controlDetails', `${control.trigger || '—'} target ${fmtW(control.target_w)}`);
  setText('flowSolar', fmtW(solar.production_w));
  setText('flowHouse', fmtW(houseLoad));
  setText('flowBattery', batteryNet >= 0 ? `uit ${fmtW(batteryNet)}` : `in ${fmtW(-batteryNet)}`);
  setText('flowGrid', importW >= exportW ? `in ${fmtW(importW)}` : `uit ${fmtW(exportW)}`);

  document.getElementById('services').innerHTML = (data.services || []).map(s =>
    `<tr><td>${s.service}</td><td class="${s.status}">${s.status}</td><td>${fmtTime(s.updated_at)}</td><td><code>${JSON.stringify(s.details || {})}</code></td></tr>`
  ).join('');
  drawForecast(data.forecast || []);
}

refresh().catch(console.error);
refreshGoodWeStatus().catch(console.error);
setInterval(() => refresh().catch(console.error), 10000);
setInterval(() => refreshGoodWeStatus().catch(console.error), 15000);
