const apiBase = window.MINYAD_API_BASE || window.location.origin;
const fmtW = (v) => `${Math.round(Number(v || 0))} W`;
const fmtTime = (v) => v ? new Date(v).toLocaleString('nl-NL', { timeZone: 'Europe/Amsterdam' }) : '—';

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

async function refresh() {
  const res = await fetch(`${apiBase}/api/status`);
  const data = await res.json();
  const grid = data.grid || {}, solar = data.solar || {}, battery = data.battery || {}, control = data.last_control || {};
  const importW = Number(grid.import_w || 0), exportW = Number(grid.export_w || 0);
  const chargeW = Number(battery.charge_w || 0), dischargeW = Number(battery.discharge_w || 0);
  const batteryNet = dischargeW - chargeW;
  const houseLoad = Math.max(0, importW - exportW + Number(solar.production_w || 0) - batteryNet);

  setText('solarW', fmtW(solar.production_w));
  setText('solarDay', `Lifetime: ${((Number(solar.lifetime_wh || 0)) / 1000).toFixed(1)} kWh`);
  setText('soc', battery.soc_pct == null ? '—%' : `${Number(battery.soc_pct).toFixed(0)}%`);
  setText('batteryMode', `${battery.mode || '—'} (${chargeW ? 'laden ' + fmtW(chargeW) : dischargeW ? 'ontladen ' + fmtW(dischargeW) : 'idle'})`);
  setText('gridW', importW >= exportW ? `Import ${fmtW(importW)}` : `Export ${fmtW(exportW)}`);
  setText('gridBalance', `Netto ${fmtW(importW - exportW)}`);
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
setInterval(() => refresh().catch(console.error), 10000);
