"""Energy Command Center page: markup, styles and script.

Self-contained so the page stays separate from the classic dashboard. Source strings are
English; the shared i18n dictionary in assets.py translates them for the Dutch interface.
Everything shown comes from /api/dashboard/energy-center and /api/dashboard/curves; values
the API cannot provide are rendered as "Not available" instead of being invented.
"""

from __future__ import annotations

ICONS = {
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "tower": '<path d="M12 3l-4 18M12 3l4 18M8.5 9h7M7 15h10M10 6h4"/>',
    "bolt": '<path d="M13 2L5 14h6l-1 8 8-12h-6z"/>',
    "swap": '<path d="M4 8h14l-3-3M20 16H6l3 3"/>',
    "leaf": '<path d="M5 19c0-9 6-14 15-14 0 9-5 15-14 15"/><path d="M5 19l8-8"/>',
    "battery": '<rect x="3" y="7" width="16" height="10" rx="2"/><path d="M21 10v4"/>',
    "heart": '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2 4 4 0 0 1 7 2c0 5.5-7 10-7 10z"/>',
    "thermo": '<path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/>',
    "robot": '<rect x="5" y="8" width="14" height="10" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M3 12v3M21 12v3"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "bell": '<path d="M6 17h12l-1.5-2.5V10a4.5 4.5 0 0 0-9 0v4.5z"/><path d="M10 20h4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-5 5-6 8-6s7 1 8 6"/>',
    "chart": '<path d="M3 20h18M6 16l4-5 3 3 5-7"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    "rocket": '<path d="M4 20l5-1 9-9a5 5 0 0 0-5-5L5 14z"/><path d="M9 15l-2 2"/>',
    "file": '<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4M10 12h6M10 16h6"/>',
    "panel": '<path d="M3 17l3-9h12l3 9z"/><path d="M9 8l-1 9M15 8l1 9M4.5 12.5h15"/>',
    "meter": '<circle cx="12" cy="13" r="8"/><path d="M12 13l4-4"/>',
    "check": '<path d="M5 12l5 5L20 7"/>',
    "chevron": '<path d="M9 5l7 7-7 7"/>',
    "cloud": '<path d="M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 16 18z"/>',
    "sunrise": '<path d="M3 19h18M7 19a5 5 0 0 1 10 0M12 4v6M12 4L9.5 6.5M12 4l2.5 2.5"/>',
    "sunset": '<path d="M3 19h18M7 19a5 5 0 0 1 10 0M12 10V4M12 10l-2.5-2.5M12 10l2.5-2.5"/>',
    "co2": '<circle cx="12" cy="12" r="9"/><path d="M12 7v7M9 11.5l3 3 3-3"/>',
    "theme": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
}


def icon(name: str, cls: str = "") -> str:
    return f'<svg class="ec-i {cls}" viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


NAV_ITEMS = [
    ("Dashboard", "/", "home"),
    ("Energy Center", "/energy-center", "bolt"),
    ("Agent", "/agent", "robot"),
    ("Health", "/health", "heart"),
    ("History", "/history", "chart"),
    ("Trade", "/trade", "rocket"),
    ("Assets", "/asset-steering", "gear"),
    ("Reporting", "/reporting", "file"),
    ("Settings", "/settings", "gear"),
]
RAIL_ITEMS = [
    ("Energy Center", "/energy-center", "home"),
    ("Solar", "/solar", "panel"),
    ("History", "/history", "chart"),
    ("Battery", "/battery", "battery"),
    ("DSMR", "/dsmr", "meter"),
    ("Settings", "/settings", "gear"),
]


def _nav() -> str:
    return "".join(
        f'<a href="{href}" class="{"active" if label == "Energy Center" else ""}"'
        f'{" aria-current=page" if label == "Energy Center" else ""}>{icon(ic)}<span>{label}</span></a>'
        for label, href, ic in NAV_ITEMS
    )


def _rail() -> str:
    return "".join(
        f'<a href="{href}" title="{label}" aria-label="{label}" class="{"active" if label == "Energy Center" else ""}">{icon(ic)}</a>'
        for label, href, ic in RAIL_ITEMS
    )


ENERGY_CENTER_CSS = r"""
.ec-page{--ec-bg:#07111a;--ec-card:#0e1a26;--ec-card2:#132333;--ec-line:rgba(120,165,200,.17);--ec-text:#eaf2f8;--ec-mut:#8ea4b5;--ec-green:#3ddc84;--ec-yellow:#f5b82e;--ec-blue:#4aa3ff;--ec-red:#ff5a4f;--ec-teal:#3ccfcf;--ec-amber:#f5b82e;background:radial-gradient(circle at 60% -10%,#12283a 0,transparent 42rem),var(--ec-bg);color:var(--ec-text);font-family:var(--sans);margin:0;min-height:100vh}
html[data-theme=light] .ec-page{--ec-bg:#edf1f4;--ec-card:#fff;--ec-card2:#f2f6f9;--ec-line:rgba(74,98,118,.2);--ec-text:#15202a;--ec-mut:#4a6276;--ec-green:#16965a;--ec-yellow:#b87f00;--ec-blue:#1f6fc4;--ec-red:#c8372d;--ec-teal:#0f8a8a;--ec-amber:#b87f00;background:var(--ec-bg)}
.ec-page *{box-sizing:border-box}
.ec-i{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;flex:none}
.ec-app{display:grid;grid-template-columns:76px minmax(0,1fr);grid-template-rows:auto 1fr;min-height:100vh}
.ec-top{grid-column:1/-1;display:flex;align-items:center;gap:28px;padding:0 24px;min-height:56px;border-bottom:1px solid var(--ec-line);background:color-mix(in srgb,var(--ec-card) 88%,transparent)}
.ec-brand{display:flex;align-items:center;gap:12px;color:var(--ec-text);text-decoration:none;font:600 17px/1 var(--mono);letter-spacing:.26em;text-transform:uppercase;white-space:nowrap}
.ec-brand .mark{width:30px;height:30px}.ec-brand .mark line,.ec-brand .mark circle{stroke:var(--ec-green)}.ec-brand .mark circle{fill:var(--ec-bg)}
.ec-nav{display:flex;gap:4px;flex:1;min-width:0;overflow-x:auto;scrollbar-width:none;justify-content:center}
.ec-nav::-webkit-scrollbar{display:none}
.ec-nav a{display:inline-flex;align-items:center;gap:8px;min-height:56px;padding:0 14px;color:var(--ec-mut);text-decoration:none;font:500 15px/1 var(--sans);border-bottom:2px solid transparent;white-space:nowrap}
.ec-nav a:hover{color:var(--ec-text)}
.ec-nav a.active{color:var(--ec-text);border-bottom-color:var(--ec-green)}
.ec-nav a.active .ec-i{color:var(--ec-green)}
.ec-actions{display:flex;align-items:center;gap:12px}
.ec-btn{position:relative;display:inline-grid;place-items:center;width:44px;height:44px;border:1px solid var(--ec-line);border-radius:999px;background:var(--ec-card2);color:var(--ec-text);cursor:pointer;text-decoration:none}
.ec-btn .dot{position:absolute;right:9px;top:9px;width:9px;height:9px;border-radius:50%;background:var(--ec-red);border:2px solid var(--ec-card2)}
.ec-btn .dot[hidden]{display:none}
.ec-rail{display:flex;flex-direction:column;gap:10px;align-items:center;padding:18px 0;border-right:1px solid var(--ec-line);background:color-mix(in srgb,var(--ec-card) 70%,transparent)}
.ec-rail a{display:grid;place-items:center;width:46px;height:46px;border-radius:12px;color:var(--ec-mut);text-decoration:none}
.ec-rail a:hover{color:var(--ec-text);background:var(--ec-card2)}
.ec-rail a.active{color:var(--ec-green);background:color-mix(in srgb,var(--ec-green) 16%,transparent)}
.ec-main{padding:16px 22px 32px;min-width:0;display:grid;gap:16px;align-content:start}
.ec-status{display:flex;align-items:center;gap:22px;flex-wrap:wrap;min-height:46px;font-size:15px}
.ec-date{display:flex;align-items:center;gap:14px;font-weight:500}
.ec-live{display:inline-flex;align-items:center;gap:7px;min-height:28px;padding:0 14px;border-radius:999px;border:1px solid currentColor;font:600 14px/1 var(--sans);color:var(--ec-green);background:color-mix(in srgb,currentColor 12%,transparent)}
.ec-live.delayed{color:var(--ec-amber)}.ec-live.offline{color:var(--ec-red)}
.ec-fresh{color:var(--ec-mut);font-size:12px}
.ec-selfpill{display:inline-flex;align-items:center;gap:12px;margin:0 auto;min-height:44px;padding:0 20px;border-radius:999px;border:1px solid color-mix(in srgb,var(--ec-green) 55%,transparent);background:color-mix(in srgb,var(--ec-green) 10%,transparent);color:var(--ec-text);text-decoration:none}
.ec-selfpill .ec-i{color:var(--ec-green);width:22px;height:22px}
.ec-selfpill b{font:700 19px/1 var(--sans);color:var(--ec-green)}
.ec-stat{display:inline-flex;align-items:center;gap:10px;color:var(--ec-text)}
.ec-stat .ec-i{color:var(--ec-green);width:24px;height:24px}
.ec-stat b{font:600 17px/1 var(--sans);color:var(--ec-green)}
.ec-stat.weather .ec-i,.ec-stat.weather b{color:var(--ec-yellow)}
.ec-stat.sun .ec-i{color:var(--ec-yellow)}.ec-stat.sun b{color:var(--ec-text);font-weight:500}
.ec-stat .na{color:var(--ec-mut);font-weight:500}
.ec-card{background:var(--ec-card);border:1px solid var(--ec-line);border-radius:14px;padding:16px 18px;min-width:0;display:flex;flex-direction:column}
.ec-card>h2{margin:0 0 12px;font:600 19px/1.2 var(--sans);display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--ec-text)}
.ec-card>h2 small{font:500 13px/1 var(--sans);color:var(--ec-mut)}
.ec-card>h2 .ec-i{color:var(--ec-mut);width:22px;height:22px}
.ec-row1{display:grid;gap:16px;grid-template-columns:3.2fr 1.25fr 1fr 1fr}
.ec-row2{display:grid;gap:16px;grid-template-columns:3fr 1fr}
.ec-side{display:grid;gap:16px;align-content:start}
.ec-row3{display:grid;gap:16px;grid-template-columns:repeat(4,1fr)}
.ec-row3 .ec-card>h2{font-size:17px}
.ec-flow-svg{width:100%;height:auto;display:block}
.ec-flow-svg .bx{fill:color-mix(in srgb,var(--ec-card2) 90%,transparent);stroke-width:1.6}
.ec-flow-svg .nm{font:600 16px var(--sans);fill:var(--ec-text)}
.ec-flow-svg .vl{font:700 30px var(--sans);fill:var(--ec-text);font-variant-numeric:tabular-nums}
.ec-flow-svg .un{font:600 15px var(--sans);fill:var(--ec-text)}
.ec-flow-svg .sm{font:500 12px var(--sans);fill:var(--ec-mut)}
.ec-flow-svg .ln{fill:none;stroke-width:3.5;stroke-linecap:round;stroke-linejoin:round}
.ec-flow-svg .ln.idle{stroke-width:2;stroke-dasharray:3 6;opacity:.45}
.ec-flow-svg .ln.on{filter:drop-shadow(0 0 5px currentColor)}
.ec-flow-svg .xmk{font:700 14px var(--sans);fill:var(--ec-mut)}
.ec-flow-text{display:none}
.ec-flow-text div{display:flex;justify-content:space-between;align-items:baseline;border-top:1px solid var(--ec-line);padding:10px 0;font-size:15px}.ec-flow-text b{font:700 22px var(--sans);font-variant-numeric:tabular-nums}.ec-flow-text small{font:500 13px var(--sans);color:var(--ec-mut);margin-left:4px}
.ec-flow-note{margin:6px 0 0;font-size:12px;color:var(--ec-mut)}
.ec-flow-warn{margin:6px 0 0;font-size:12px;color:var(--ec-amber)}
.ec-flow-warn[hidden]{display:none}
.ec-list{display:grid;margin:0;padding:0;list-style:none}
.ec-list li{display:flex;align-items:center;gap:10px;min-height:46px;border-top:1px solid var(--ec-line);font-size:14px}
.ec-list li:first-child{border-top:0}
.ec-list li .ec-i{width:22px;height:22px}
.ec-list li span{flex:1;color:var(--ec-text);white-space:nowrap}
.ec-list li b{font:600 15px var(--sans);font-variant-numeric:tabular-nums}
.ec-list li.hl b,.ec-list li.hl span{color:var(--ec-green);font-weight:700}
.ec-na{color:var(--ec-mut);font-weight:500;font-size:13px;white-space:nowrap}
.ec-gauge{display:grid;place-items:center;flex:1}
.ec-gauge svg{width:100%;max-width:190px;height:auto}
.ec-gauge .tr{fill:none;stroke:var(--ec-card2);stroke-width:16}
.ec-gauge .fl{fill:none;stroke:var(--ec-green);stroke-width:16;stroke-linecap:round}
.ec-gauge .pc{font:700 36px var(--sans);fill:var(--ec-text)}.ec-gauge .sb{font:500 14px var(--sans);fill:var(--ec-mut)}
.ec-goal{display:flex;align-items:center;gap:12px;min-height:46px;border-top:1px solid var(--ec-line);font-size:15px}
.ec-goal:first-child{border-top:0}
.ec-goal .ck{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;border:1.6px solid var(--ec-mut);color:transparent;flex:none}
.ec-goal .ck .ec-i{width:14px;height:14px;stroke-width:3}
.ec-goal.met .ck{background:var(--ec-green);border-color:var(--ec-green);color:#06210f}
.ec-goal.miss .ck{border-color:var(--ec-red)}
.ec-goal span{flex:1}
.ec-legend{display:flex;gap:18px;flex-wrap:wrap;align-items:center;font-size:14px;color:var(--ec-text)}
.ec-legend button{display:inline-flex;align-items:center;gap:8px;min-height:28px;padding:0 4px;border:0;background:transparent;color:inherit;font:inherit;cursor:pointer;border-radius:6px}
.ec-legend button::before{content:"";width:10px;height:10px;border-radius:50%;background:var(--c)}
.ec-legend button.fc::before{background:none;border:2px dashed var(--c);width:12px;height:12px}
.ec-legend button[aria-pressed="false"]{opacity:.4}
.ec-legend button[hidden]{display:none}
.ec-pills{display:inline-flex;gap:4px;padding:4px;border-radius:999px;background:var(--ec-card2);border:1px solid var(--ec-line)}
.ec-pills button{min-height:32px;min-width:48px;padding:0 14px;border:0;border-radius:999px;background:transparent;color:var(--ec-text);font:600 14px var(--sans);cursor:pointer}
.ec-pills button.active{background:var(--ec-green);color:#06210f}
.ec-charthead{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:6px}
.ec-charthead h2{margin:0;font:600 19px var(--sans)}
.ec-chartwrap{position:relative}
.ec-chart{width:100%;height:340px;display:block}
.ec-chart .gl{stroke:var(--ec-line);stroke-width:1}.ec-chart .zero{stroke:color-mix(in srgb,var(--ec-text) 40%,transparent);stroke-width:1}
.ec-chart .ax{font:12px var(--sans);fill:var(--ec-mut)}
.ec-chart .ln{fill:none;stroke-width:2}
.ec-chart .fcl{fill:none;stroke-width:2;stroke-dasharray:6 5;opacity:.8}
.ec-chart .now{stroke:var(--ec-text);stroke-width:1;stroke-dasharray:4 4}
.ec-chart .nowbx{fill:var(--ec-card2);stroke:var(--ec-line)}.ec-chart .nowtx{font:600 13px var(--sans);fill:var(--ec-text)}
.ec-chart .hov{fill:none;stroke:transparent;stroke-width:14;pointer-events:stroke}
.ec-chart-msg{margin:4px 0 0;font-size:12px;color:var(--ec-amber)}
.ec-chart-msg[hidden]{display:none}
.ec-tip{position:absolute;z-index:5;min-width:170px;pointer-events:none;background:var(--ec-card2);border:1px solid var(--ec-line);border-radius:9px;padding:9px 12px;font-size:12px;box-shadow:0 12px 30px rgba(0,0,0,.35)}
.ec-tip b{display:block;margin-bottom:3px}.ec-tip span{display:block;color:var(--ec-mut)}
.ec-tip[hidden]{display:none}
.ec-batt{display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:center}
.ec-batt-left{display:flex;align-items:center;gap:16px}
.ec-batt-svg{width:60px;height:100px}
.ec-batt-svg .sh{fill:none;stroke:var(--ec-text);stroke-width:2}
.ec-batt-svg .cap{fill:var(--ec-text)}
.ec-batt-svg .fl{fill:var(--ec-green)}.ec-batt-svg.low .fl{fill:var(--ec-amber)}
.ec-batt-svg .mk{stroke:var(--ec-text);stroke-width:2}
.ec-batt-pct{font:700 38px/1 var(--sans);font-variant-numeric:tabular-nums}
.ec-batt-sub{font-size:13px;color:var(--ec-mut);margin-top:4px}
.ec-batt-lim{font-size:12px;color:var(--ec-mut);margin-top:6px}
.ec-kv{display:grid;margin:0}
.ec-kv div{display:flex;align-items:center;gap:10px;min-height:34px;border-top:1px solid var(--ec-line);font-size:13px}
.ec-kv div:first-child{border-top:0}
.ec-kv .ec-i{width:18px;height:18px;color:var(--ec-mut)}
.ec-kv dt{flex:1;color:var(--ec-text);white-space:nowrap}.ec-kv dd{margin:0;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.ec-pill{display:inline-flex;align-items:center;min-height:28px;padding:0 14px;border-radius:999px;border:1px solid currentColor;font:600 14px var(--sans);color:var(--ec-green);background:color-mix(in srgb,currentColor 12%,transparent)}
.ec-pill.off{color:var(--ec-mut)}
.ec-agent{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:center}
.ec-agent .bot{display:grid;place-items:center;width:66px;height:66px;border-radius:14px;color:var(--ec-green)}
.ec-agent .bot .ec-i{width:56px;height:56px;stroke-width:1.4}
.ec-agent-note{margin:8px 0 0;font-size:12px;color:var(--ec-mut);line-height:1.4}
.ec-stack{display:flex;height:22px;border-radius:6px;overflow:hidden;background:var(--ec-card2);margin:4px 0 14px}
.ec-stack i{display:block;height:100%}
.ec-mixrow{display:flex;align-items:center;gap:10px;min-height:34px;font-size:14px}
.ec-mixrow::before{content:"";width:11px;height:11px;border-radius:50%;background:var(--c)}
.ec-mixrow span{flex:1}.ec-mixrow b{width:80px;text-align:right;font-variant-numeric:tabular-nums}.ec-mixrow em{width:48px;text-align:right;font-style:normal;color:var(--ec-mut)}
.ec-mixnote{margin:6px 0 0;font-size:12px;color:var(--ec-mut)}
.ec-fc{display:flex;flex-direction:column;flex:1}
.ec-fc svg{width:100%;height:auto;display:block}
.ec-fc .ax{font:11px var(--sans);fill:var(--ec-mut)}.ec-fc .gl{stroke:var(--ec-line)}
.ec-fc-legend{display:flex;gap:14px;font-size:12px;color:var(--ec-text);margin:0 0 6px}
.ec-fc-legend span::before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;background:var(--c);vertical-align:-1px}
.ec-empty{display:grid;place-items:center;flex:1;min-height:120px;color:var(--ec-mut);font-size:14px;text-align:center;border:1px dashed var(--ec-line);border-radius:10px;padding:12px}
.ec-alert-ok{display:flex;align-items:center;gap:12px;min-height:50px;color:var(--ec-green);font:700 18px var(--sans)}
.ec-alert-ok .ec-i{width:26px;height:26px;border:2px solid currentColor;border-radius:50%;padding:4px}
.ec-alert-ok.quiet{color:var(--ec-mut);font-size:14px;font-weight:500}
.ec-alerts{display:grid;gap:8px}
.ec-alertrow{--sev:var(--ec-amber);display:grid;grid-template-columns:auto 1fr auto;gap:4px 12px;align-items:center;padding:10px 12px;border:1px solid var(--ec-line);border-left:3px solid var(--sev);border-radius:10px;color:var(--ec-text);text-decoration:none;font-size:14px}
.ec-alertrow.critical{--sev:var(--ec-red)}.ec-alertrow.warning{--sev:var(--ec-amber)}.ec-alertrow.info{--sev:var(--ec-blue)}
.ec-alertrow .sv{display:inline-flex;align-items:center;min-height:20px;padding:0 8px;border:1px solid var(--sev);border-radius:999px;color:var(--sev);font:700 10px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase}
.ec-alertrow b{font-weight:600}
.ec-alertrow .meta,.ec-alertrow .next{grid-column:1/-1;margin:0;font-size:12px;color:var(--ec-mut)}
.ec-alertrow .meta b{color:var(--ec-text);font-weight:500}.ec-alertrow .next{color:var(--ec-text)}
.ec-alertrow .ec-i{width:18px;height:18px;color:var(--ec-mut)}
@media(max-width:1439px){.ec-row1{grid-template-columns:1fr 1fr}.ec-row1>.flow{grid-column:1/-1}.ec-row3{grid-template-columns:repeat(2,1fr)}.ec-row2{grid-template-columns:1fr}.ec-side{grid-template-columns:1fr 1fr}}
@media(max-width:1023px){.ec-app{grid-template-columns:minmax(0,1fr)}.ec-rail{display:none}.ec-top{gap:4px 12px;flex-wrap:wrap;padding-top:6px}.ec-brand{flex:1}.ec-nav{order:3;flex:1 1 100%;justify-content:flex-start}.ec-nav a{min-height:44px;padding:0 12px}.ec-selfpill{margin:0}}
@media(max-width:767px){.ec-flow-text{display:block}.ec-batt{grid-template-columns:1fr}.ec-main{padding:12px 12px 28px}.ec-row1,.ec-row3,.ec-side{grid-template-columns:1fr}.ec-brand{font-size:14px;letter-spacing:.18em}.ec-status{gap:12px}.ec-chart{height:260px}.ec-pills button,.ec-legend button{min-height:44px}.ec-top{padding:0 12px}.ec-nav{justify-content:flex-start}}
@media(prefers-reduced-motion:reduce){.ec-page *{animation:none!important;transition:none!important}}
"""


def _flow_svg() -> str:
    arrows = "".join(
        f'<marker id="ec-ah-{k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto"><path d="M0 0L8 4L0 8z" fill="{c}"/></marker>'
        for k, c in (("solar", "var(--ec-yellow)"), ("battery", "var(--ec-green)"), ("home", "var(--ec-blue)"), ("import", "var(--ec-red)"), ("export", "var(--ec-teal)"))
    )
    return f"""
<svg class="ec-flow-svg" id="ec-flow-svg" viewBox="0 0 800 270" role="img" aria-labelledby="ec-flow-t ec-flow-d">
  <title id="ec-flow-t">Live energy flow</title><desc id="ec-flow-d">Loading values.</desc>
  <defs>{arrows}
    <clipPath id="ec-roofclip"><polygon points="62,104 140,48 218,104"/></clipPath>
    <linearGradient id="ec-glow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--ec-yellow)" stop-opacity=".35"/><stop offset="1" stop-color="var(--ec-yellow)" stop-opacity="0"/></linearGradient>
  </defs>
  <!-- house illustration (decorative) -->
  <g transform="translate(250,30)" aria-hidden="true">
    <ellipse cx="140" cy="212" rx="120" ry="12" fill="#000" opacity=".35"/>
    <rect x="48" y="100" width="184" height="104" rx="4" fill="#1b2d3f" stroke="#2c4660"/>
    <polygon points="38,106 140,40 242,106" fill="#22384e" stroke="#33526f"/>
    <g clip-path="url(#ec-roofclip)" transform="translate(0,0)">
      <g fill="#1d5aa8" stroke="#6fb3ff" stroke-width=".6" opacity=".95">
        <polygon points="76,98 98,84 112,92 90,106"/><polygon points="102,82 124,68 138,76 116,90"/><polygon points="128,66 150,53 164,61 142,75"/>
        <polygon points="116,96 138,82 152,90 130,104"/><polygon points="142,80 164,67 178,75 156,89"/><polygon points="168,64 190,52 204,60 182,73"/>
      </g>
    </g>
    <rect x="190" y="56" width="16" height="34" fill="#2a4259"/>
    <g fill="var(--ec-yellow)"><rect x="68" y="122" width="34" height="34" rx="3"/><rect x="118" y="122" width="34" height="34" rx="3"/><rect x="168" y="122" width="40" height="34" rx="3"/></g>
    <rect x="68" y="122" width="34" height="34" rx="3" fill="url(#ec-glow)"/>
    <g stroke="#1b2d3f" stroke-width="2"><path d="M85 122v34M68 139h34M135 122v34M118 139h34M188 122v34M168 139h40"/></g>
    <rect x="112" y="166" width="30" height="38" rx="2" fill="#13222f"/>
    <rect x="48" y="200" width="184" height="6" fill="#0f1b27"/>
  </g>
  <!-- flow lines -->
  <path id="ec-ln-solar" class="ln idle" d="M215 93 H265 Q300 93 322 70" style="color:var(--ec-yellow);stroke:var(--ec-yellow)"/>
  <path id="ec-ln-battery" class="ln idle" d="M215 198 H275 Q310 198 334 172" style="color:var(--ec-green);stroke:var(--ec-green)"/>
  <path id="ec-ln-home" class="ln idle" d="M470 70 H520 V98" style="color:var(--ec-blue);stroke:var(--ec-blue)"/>
  <path id="ec-ln-grid" class="ln idle" d="M628 186 H520" style="color:var(--ec-red);stroke:var(--ec-red)"/>
  <text id="ec-x-solar" class="xmk" x="270" y="86" text-anchor="middle">✕</text>
  <text id="ec-x-battery" class="xmk" x="278" y="190" text-anchor="middle">✕</text>
  <!-- nodes -->
  <g><rect class="bx" x="20" y="54" width="195" height="78" rx="10" style="stroke:var(--ec-yellow)"/>
    <g transform="translate(36,66)" style="color:var(--ec-yellow)"><svg class="ec-i" viewBox="0 0 24 24" width="28" height="28" style="stroke:var(--ec-yellow);fill:none;stroke-width:1.7;stroke-linecap:round">__ICON_SUN__</svg></g>
    <text class="nm" x="76" y="78">Solar</text><text class="vl" id="ec-fl-pv" x="76" y="112">--</text><text class="un" id="ec-fl-pv-u" x="140" y="112">kW</text><text class="sm" id="ec-fl-pv-s" x="203" y="78" text-anchor="end"></text></g>
  <g><rect class="bx" x="20" y="160" width="195" height="78" rx="10" style="stroke:var(--ec-green)"/>
    <g transform="translate(36,172)"><svg class="ec-i" viewBox="0 0 24 24" width="28" height="28" style="stroke:var(--ec-green);fill:none;stroke-width:1.7;stroke-linecap:round">__ICON_BATTERY__</svg></g>
    <text class="nm" x="76" y="184">Battery</text><text class="vl" id="ec-fl-bat" x="76" y="218">--</text><text class="un" id="ec-fl-bat-u" x="140" y="218">kW</text><text class="sm" id="ec-fl-bat-soc" x="203" y="224" text-anchor="end"></text><text class="sm" id="ec-fl-bat-s" x="203" y="184" text-anchor="end"></text></g>
  <g><rect class="bx" x="485" y="24" width="150" height="74" rx="10" style="stroke:var(--ec-blue)"/>
    <g transform="translate(499,34)"><svg class="ec-i" viewBox="0 0 24 24" width="24" height="24" style="stroke:var(--ec-blue);fill:none;stroke-width:1.7;stroke-linecap:round">__ICON_HOME__</svg></g>
    <text class="nm" x="534" y="52">Home</text><text class="vl" id="ec-fl-home" x="499" y="84">--</text><text class="un" id="ec-fl-home-u" x="563" y="84">kW</text></g>
  <g><rect class="bx" x="630" y="128" width="155" height="112" rx="10" style="stroke:var(--ec-red)"/>
    <g transform="translate(644,138)"><svg class="ec-i" viewBox="0 0 24 24" width="26" height="26" style="stroke:var(--ec-red);fill:none;stroke-width:1.7;stroke-linecap:round">__ICON_TOWER__</svg></g>
    <text class="nm" x="682" y="158">Grid</text><text class="vl" id="ec-fl-grid" x="644" y="196">--</text><text class="un" id="ec-fl-grid-u" x="708" y="196">kW</text><text class="sm" id="ec-fl-grid-s" x="644" y="222" style="font-size:14px;font-weight:600"></text></g>
</svg>"""


def energy_center_body(brand_name: str, mark_html: str) -> str:
    flow = _flow_svg()
    for key, name in (("SUN", "sun"), ("BATTERY", "battery"), ("HOME", "home"), ("TOWER", "tower")):
        flow = flow.replace(f"__ICON_{key}__", ICONS[name])
    today_rows = "".join(
        f'<li id="ec-r-{rid}"{" class=hl" if hl else ""}>{icon(ic)}<span>{label}</span><b id="ec-t-{rid}">--</b></li>'
        for rid, label, ic, hl in (
            ("pv", "Production (solar)", "sun", False),
            ("home", "Consumption (home)", "home", False),
            ("import", "Import (grid)", "tower", False),
            ("export", "Export (grid)", "swap", False),
            ("self", "Self-sufficient", "leaf", True),
        )
    )
    html = f"""
<div class="ec-app">
  <header class="ec-top">
    <a class="ec-brand" href="/" aria-label="Minyad dashboard">{mark_html}<span>{brand_name}</span></a>
    <nav class="ec-nav" aria-label="Primary navigation">{_nav()}</nav>
    <div class="ec-actions">
      <a class="ec-btn" href="/agent" id="ec-bell" title="Agent mailbox" aria-label="Agent mailbox">{icon("bell")}<span class="dot" id="ec-bell-dot" hidden></span></a>
      <button class="ec-btn" type="button" id="ec-theme" title="Switch theme" aria-label="Switch theme">{icon("sun")}</button>
      <a class="ec-btn" href="/settings" title="Settings" aria-label="Settings">{icon("user")}</a>
    </div>
  </header>
  <aside class="ec-rail" aria-label="Quick navigation">{_rail()}</aside>
  <main class="ec-main" aria-label="Minyad Energy Command Center">
    <div class="ec-status">
      <div class="ec-date"><span id="ec-datetime">--</span><span class="ec-live offline" id="ec-conn"><span id="ec-conn-label">Offline</span></span><span class="ec-fresh"><span>Last measurement</span> <span id="ec-updated">--</span> <span id="ec-ago">ago</span></span></div>
      <a class="ec-selfpill" href="/history" title="Self-sufficiency today">{icon("leaf")}<span>Self-sufficient today</span><b id="ec-self-top">--</b>{icon("chevron")}</a>
      <div class="ec-stat" id="ec-co2" title="Estimated at 0.39 kg CO2 per kWh of solar production">{icon("co2")}<span>CO₂ saved</span><b id="ec-co2-v">--</b></div>
      <div class="ec-stat weather" id="ec-weather">{icon("cloud")}<b class="na" id="ec-temp">Not available</b></div>
      <div class="ec-stat sun" title="Sunrise">{icon("sunrise")}<b id="ec-sunrise">--:--</b></div>
      <div class="ec-stat sun" title="Sunset">{icon("sunset")}<b id="ec-sunset">--:--</b></div>
    </div>

    <div class="ec-row1">
      <section class="ec-card flow" aria-label="Live energy flow"><h2>Live energy flow</h2>{flow}
        <div class="ec-flow-text" id="ec-flow-text" aria-hidden="true"></div>
        <p class="ec-flow-note">Accounting view from meter readings, not a measured physical energy split.</p><p class="ec-flow-warn" id="ec-flow-warn" hidden></p></section>
      <section class="ec-card" aria-label="Today"><h2>Today</h2><ul class="ec-list">{today_rows}</ul></section>
      <section class="ec-card" aria-label="Self-sufficient"><h2>Self-sufficient</h2><div class="ec-gauge">
        <svg viewBox="0 0 160 160" role="img" aria-labelledby="ec-g-t"><title id="ec-g-t">Self-sufficient today</title>
          <circle class="tr" cx="80" cy="80" r="62"/><circle class="fl" id="ec-gauge-arc" cx="80" cy="80" r="62" transform="rotate(-90 80 80)" stroke-dasharray="0 400"/>
          <text class="pc" id="ec-gauge-v" x="80" y="88" text-anchor="middle">--</text><text class="sb" x="80" y="110" text-anchor="middle">today</text></svg></div></section>
      <section class="ec-card" aria-label="Daily goals"><h2>Daily goals {icon("target")}</h2><div id="ec-goals"><span class="ec-na">Loading…</span></div></section>
    </div>

    <div class="ec-row2">
      <section class="ec-card" aria-label="Today power chart">
        <div class="ec-charthead"><h2>Today – Power (kW)</h2>
          <div class="ec-legend" aria-label="Show or hide series">
            <button type="button" data-s="pv" aria-pressed="true" style="--c:var(--ec-green)">Production (solar)</button>
            <button type="button" data-s="home" aria-pressed="true" style="--c:var(--ec-blue)">Consumption (home)</button>
            <button type="button" data-s="battery" aria-pressed="true" style="--c:var(--ec-yellow)">Battery (±)</button>
            <button type="button" data-s="grid" aria-pressed="true" style="--c:var(--ec-red)">Grid (±)</button>
            <button type="button" class="fc" data-s="forecast" aria-pressed="true" style="--c:var(--ec-green)" id="ec-leg-fc" hidden>Solar forecast</button>
            <button type="button" class="fc" data-s="load_forecast" aria-pressed="true" style="--c:var(--ec-blue)" id="ec-leg-lf" hidden>Load forecast</button>
          </div>
          <div class="ec-pills" role="group" aria-label="Range"><button type="button" class="active" data-r="24h">24h</button><button type="button" data-r="12h">12h</button><button type="button" data-r="7d">7d</button><button type="button" data-r="30d">30d</button></div>
        </div>
        <p class="ec-chart-msg" id="ec-chart-msg" hidden></p>
        <div class="ec-chartwrap"><svg id="ec-chart" class="ec-chart" viewBox="0 0 960 340" role="img" aria-label="Solar, home, battery and grid power today, measured and forecast"></svg><div class="ec-tip" id="ec-tip" hidden></div></div>
      </section>
      <div class="ec-side">
        <section class="ec-card" aria-label="Battery"><h2>Battery {icon("battery")}</h2>
          <div class="ec-batt"><div class="ec-batt-left">
            <svg class="ec-batt-svg" id="ec-batt-svg" viewBox="0 0 60 100" aria-hidden="true"><rect class="cap" x="20" y="0" width="20" height="6" rx="2"/><rect class="sh" x="4" y="8" width="52" height="88" rx="8"/><rect class="fl" id="ec-batt-fill" x="8" y="92" width="44" height="0" rx="5"/><line class="mk" id="ec-batt-min" x1="2" x2="58" y1="0" y2="0" hidden/><line class="mk" id="ec-batt-max" x1="2" x2="58" y1="0" y2="0" hidden/></svg>
            <div><div class="ec-batt-pct" id="ec-batt-pct">--%</div><div class="ec-batt-sub" id="ec-batt-cap">-- / -- kWh</div><div class="ec-batt-lim" id="ec-batt-lim"></div></div></div>
            <dl class="ec-kv"><div>{icon("bolt")}<dt>Power</dt><dd id="ec-b-power">--</dd></div><div>{icon("swap")}<dt>Status</dt><dd id="ec-b-state">--</dd></div><div>{icon("heart")}<dt>Battery health</dt><dd id="ec-b-health">--</dd></div><div>{icon("thermo")}<dt>Temp.</dt><dd id="ec-b-temp">--</dd></div></dl></div></section>
        <section class="ec-card" aria-label="VPP and agent"><h2>VPP / Agent <span class="ec-pill off" id="ec-agent-pill">Unknown</span></h2>
          <div class="ec-agent"><div class="bot">{icon("robot")}</div><dl class="ec-kv"><div><dt>Mode</dt><dd id="ec-a-mode">--</dd></div><div><dt>SoC limits</dt><dd id="ec-a-soc">--</dd></div><div><dt>Cooldown</dt><dd id="ec-a-cd">--</dd></div></dl></div>
          <p class="ec-agent-note" id="ec-a-note"></p></section>
      </div>
    </div>

    <div class="ec-row3">
      <section class="ec-card" aria-label="Energy today"><h2>Energy today <small id="ec-mix-total">--</small></h2><div id="ec-mix"><span class="ec-na">Loading…</span></div></section>
      <section class="ec-card" aria-label="Forecast"><h2>Forecast – Production &amp; consumption <small>kWh</small></h2><div class="ec-fc" id="ec-fc"><div class="ec-empty">Forecast not available</div></div></section>
      <section class="ec-card" aria-label="Battery plan"><h2>Battery plan <small>(next 24h)</small></h2><div class="ec-fc" id="ec-plan"><div class="ec-empty">No battery plan available</div></div></section>
      <section class="ec-card" aria-label="Alerts and actions"><h2>Alerts &amp; actions</h2><div id="ec-alerts"><span class="ec-na">Loading…</span></div></section>
    </div>
  </main>
</div>
"""
    return html


ENERGY_CENTER_SCRIPT = r"""
(function(){
  const $=id=>document.getElementById(id);
  const n=v=>{const x=Number(v);return Number.isFinite(x)?x:null};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tr=t=>(window.minyadI18n&&window.minyadI18n.t)?window.minyadI18n.t(t):t;
  const fmtKw=(v,signed=false)=>{if(v==null)return '--'; const r=Math.round(Math.abs(v)*100)/100; if(r===0)return '0.00'; return (signed&&v<0?'-':'')+r.toFixed(2);};
  const ageText=s=>{if(s==null)return 'unknown'; s=Math.round(s); if(s<90)return s+' s'; const m=Math.round(s/60); if(m<90)return m+' min'; return Math.round(m/60)+' h';};
  const hhmm=iso=>{if(!iso)return '--:--'; const d=new Date(iso); return Number.isNaN(d.getTime())?'--:--':d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});};
  const NA='<span class="ec-na">Not available</span>';
  const DEAD=0.03;
  const SERIES={pv:'var(--ec-green)',home:'var(--ec-blue)',battery:'var(--ec-yellow)',grid:'var(--ec-red)',forecast:'var(--ec-green)',load_forecast:'var(--ec-blue)'};
  const SERIES_LABEL={pv:'Production (solar)',home:'Consumption (home)',battery:'Battery (±)',grid:'Grid (±)',forecast:'Solar forecast',load_forecast:'Load forecast'};
  const visible={pv:true,home:true,battery:true,grid:true,forecast:true,load_forecast:true};
  let range='24h', dayCurves=null, longCurves=null, longWindow=null, loadedAt=0, longLoadedAt=0, lastData=null, chartW=960;

  // ---- status bar ----
  function renderStatus(data){
    const d=new Date();
    $('ec-datetime').textContent=d.toLocaleDateString([], {weekday:'short',day:'numeric',month:'short',year:'numeric'})+' · '+d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    const conn=data?data.connection:'offline';
    const el=$('ec-conn'); el.className='ec-live '+conn;
    $('ec-conn-label').textContent={live:'Live',delayed:'Delayed',offline:'Offline'}[conn]||'Offline';
    const known=data&&data.telemetryAgeSeconds!=null; $('ec-updated').textContent=known?ageText(data.telemetryAgeSeconds):'unknown'; $('ec-ago').hidden=!known;
    $('ec-updated').title=(data&&data.updatedAt)?'Last measurement: '+new Date(data.updatedAt).toLocaleString():'';
    if(!data)return;
    const s=data.today.selfSufficiencyPct;
    $('ec-self-top').textContent=s.value==null?'Not available':Math.round(s.value)+'%';
    const co2=data.co2SavedKg;
    $('ec-co2-v').textContent=(co2&&co2.value!=null)?co2.value.toFixed(1).replace('.',',')+' kg':'Not available';
    const w=data.weather;
    $('ec-temp').textContent=(w&&w.temperatureC!=null)?Math.round(w.temperatureC)+' °C':'Not available';
    $('ec-sunrise').textContent=data.sun?hhmm(data.sun.sunrise):'--:--';
    $('ec-sunset').textContent=data.sun?hhmm(data.sun.sunset):'--:--';
    $('ec-bell-dot').hidden=!(data.alerts&&data.alerts.length);
  }

  // ---- live energy flow ----
  function setLine(id,d,color,active){
    const el=$(id); if(!el)return;
    el.setAttribute('d',d);
    el.setAttribute('class','ln '+(active?'on':'idle'));
    if(active)el.setAttribute('marker-end','url(#ec-ah-'+color+')'); else el.removeAttribute('marker-end');
  }
  function renderFlow(data){
    const i=data.instantaneous, set=(id,t)=>{const e=$(id); if(e)e.textContent=t;}, set_s=id=>($(id)&&$(id).textContent)||'';
    const pv=n(i.pvKw.value), bat=n(i.batteryKw.value), grid=n(i.gridKw.value), home=n(i.homeKw.value);
    set('ec-fl-pv',fmtKw(pv)); set('ec-fl-bat',fmtKw(bat,true)); set('ec-fl-grid',fmtKw(grid)); set('ec-fl-home',fmtKw(home));
    const pvStale=i.pvKw.quality==='stale';
    set('ec-fl-pv-s',pv==null?'Unknown':pvStale?'Stale':pv>DEAD?'Producing':'Standby');
    set('ec-fl-bat-s',{charge:'Charging',discharge:'Discharging',idle:'Standby',unknown:'Unknown'}[i.batteryDirection]);
    const soc=n(data.battery.socPct.value); set('ec-fl-bat-soc',soc==null?'':Math.round(soc)+'%');
    set('ec-fl-grid-s',{import:'Import',export:'Export',neutral:'Standby',unknown:'Unknown'}[i.gridDirection]);
    const gridColor=i.gridDirection==='export'?'var(--ec-teal)':'var(--ec-red)';
    const gs=$('ec-fl-grid-s'); if(gs)gs.style.fill=gridColor;
    // Arrows only above the deadband; inactive flows get a dotted line and a cross.
    const pvOn=pv!=null&&pv>DEAD;
    setLine('ec-ln-solar','M215 93 H265 Q300 93 322 70','solar',pvOn); $('ec-x-solar').style.display=pvOn?'none':'';
    const charging=i.batteryDirection==='charge', discharging=i.batteryDirection==='discharge';
    setLine('ec-ln-battery',charging?'M334 172 Q310 198 275 198 H215':'M215 198 H275 Q310 198 334 172','battery',charging||discharging); $('ec-x-battery').style.display=(charging||discharging)?'none':'';
    setLine('ec-ln-home','M470 70 H520 V98','home',home!=null&&home>DEAD);
    if(i.gridDirection==='export')setLine('ec-ln-grid','M520 186 H628','export',true);
    else setLine('ec-ln-grid','M628 186 H520','import',i.gridDirection==='import');
    const d=$('ec-flow-d'); if(d)d.textContent='Solar '+fmtKw(pv)+' kW. Battery '+fmtKw(bat,true)+' kW, '+({charge:'charging',discharge:'discharging',idle:'standby',unknown:'unknown'}[i.batteryDirection])+'. Grid '+fmtKw(grid)+' kW, '+({import:'import',export:'export',neutral:'standby',unknown:'unknown'}[i.gridDirection])+'. Home '+fmtKw(home)+' kW.';
    const ft=$('ec-flow-text'); if(ft)ft.innerHTML=[['Solar',fmtKw(pv),set_s('ec-fl-pv-s')],['Battery',fmtKw(bat,true),set_s('ec-fl-bat-s')],['Grid',fmtKw(grid),set_s('ec-fl-grid-s')],['Home',fmtKw(home),'']].map(r=>'<div><span>'+r[0]+' <small>'+r[2]+'</small></span><b>'+r[1]+'<small>kW</small></b></div>').join('');
    const mm=(data.alerts||[]).find(a=>a.id==='household-meter-mismatch'), w=$('ec-flow-warn');
    if(mm){w.hidden=false; w.innerHTML='<span>Meter readings disagree:</span> '+esc(mm.description);} else w.hidden=true;
  }

  // ---- today, gauge, goals ----
  function setTotal(id,r,unit){
    const el=$(id); if(!el)return;
    const miss=!r||r.value==null;
    if(miss){el.innerHTML=NA; el.title='No measurements available for today.'; return;}
    el.textContent=(r.quality==='estimated'?'~':'')+r.value.toFixed(1)+' '+unit; el.title=r.note||'';
  }
  function renderToday(data){
    const t=data.today;
    setTotal('ec-t-pv',t.pvKwh,'kWh'); setTotal('ec-t-home',t.homeKwh,'kWh'); setTotal('ec-t-import',t.gridImportKwh,'kWh'); setTotal('ec-t-export',t.gridExportKwh,'kWh');
    const s=t.selfSufficiencyPct.value;
    if(s==null)$('ec-t-self').innerHTML=NA; else $('ec-t-self').textContent=Math.round(s)+'%';
    const C=2*Math.PI*62, frac=s==null?0:Math.max(0,Math.min(1,s/100));
    $('ec-gauge-arc').setAttribute('stroke-dasharray',(frac*C).toFixed(1)+' '+C.toFixed(1));
    $('ec-gauge-v').textContent=s==null?'--':Math.round(s)+'%';
    $('ec-g-t').textContent='Self-sufficient today'+(t.selfSufficiencyMethod?'. '+t.selfSufficiencyMethod:'');
  }
  function goal(state,html){
    return '<div class="ec-goal '+state+'"><span class="ck"><svg class="ec-i" viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg></span><span>'+html+'</span></div>';
  }
  function renderGoals(data){
    const g=data.goals||{}, t=data.today, b=data.battery, soc=n(b.socPct.value);
    const self=t.selfSufficiencyPct.value, exp=t.gridExportKwh.value, home=t.homeKwh.value;
    const st=(known,ok)=>!known?'':ok?'met':'miss';
    const items=[
      goal(st(self!=null,self>g.selfSufficiencyPct),'<span>Self-sufficient</span> &gt; '+esc(g.selfSufficiencyPct)+'%'),
      goal(st(soc!=null&&b.minSocPct!=null&&b.maxSocPct!=null,soc>=b.minSocPct&&soc<=b.maxSocPct),'<span>Battery</span> '+(b.minSocPct!=null?esc(b.minSocPct):'--')+' – '+(b.maxSocPct!=null?esc(b.maxSocPct):'--')+'%'),
      goal(st(exp!=null,exp!=null&&exp<0.05),'<span>Zero export (grid)</span>'),
      goal(st(home!=null,home!=null&&home<g.consumptionKwh),'<span>Consumption</span> &lt; '+esc(g.consumptionKwh)+' kWh'),
    ];
    $('ec-goals').innerHTML=items.join('');
  }

  // ---- battery + agent ----
  function renderBattery(data){
    const b=data.battery, i=data.instantaneous, soc=n(b.socPct.value), min=n(b.minSocPct), max=n(b.maxSocPct);
    const pct=soc==null?0:Math.max(0,Math.min(100,soc)), h=84*pct/100;
    const fill=$('ec-batt-fill'); fill.setAttribute('y',String(92-h)); fill.setAttribute('height',String(h));
    $('ec-batt-svg').classList.toggle('low',soc!=null&&min!=null&&soc<min);
    for(const [id,v] of [['ec-batt-min',min],['ec-batt-max',max]]){const l=$(id); if(v==null){l.hidden=true;continue;} const y=92-84*Math.max(0,Math.min(100,v))/100; l.hidden=false; l.setAttribute('y1',y); l.setAttribute('y2',y);}
    $('ec-batt-pct').textContent=soc==null?'--%':Math.round(soc)+'%';
    const cap=n(b.capacityKwh.value);
    $('ec-batt-cap').textContent=(cap!=null&&soc!=null)?(cap*soc/100).toFixed(1)+' / '+cap.toFixed(1)+' kWh':'-- / -- kWh';
    $('ec-batt-lim').textContent=(min!=null&&max!=null)?'min '+Math.round(min)+'% · max '+Math.round(max)+'%':'';
    $('ec-b-power').textContent=i.batteryKw.value==null?'--':fmtKw(n(i.batteryKw.value),true)+' kW';
    $('ec-b-state').textContent={charge:'Charging',discharge:'Discharging',idle:'Standby',unknown:'Unknown'}[i.batteryDirection];
    if(b.healthPct&&b.healthPct.value!=null)$('ec-b-health').textContent=Math.round(b.healthPct.value)+'%'; else $('ec-b-health').innerHTML=NA;
    if(b.temperatureC&&b.temperatureC.value!=null)$('ec-b-temp').textContent=b.temperatureC.value.toFixed(1)+' °C'; else $('ec-b-temp').innerHTML=NA;
  }
  function renderAgent(data){
    const a=data.agent, c=a.constraints||{};
    const pill=$('ec-agent-pill'); pill.className='ec-pill'+(a.enabled?'':' off'); pill.textContent=a.enabled==null?'Unknown':a.enabled?'Active':'Inactive';
    $('ec-a-mode').textContent={IDLE:'Standby',CHARGING:'Charging',DISCHARGING:'Discharging'}[a.mode]||a.mode||'Unknown';
    $('ec-a-soc').textContent=(c.socFloorPct!=null&&c.socCeilingPct!=null)?c.socFloorPct+' – '+c.socCeilingPct+'%':'--';
    $('ec-a-cd').textContent=c.cooldownSeconds!=null?c.cooldownSeconds+' s':'--';
    const reason=a.reasonText?esc(a.reasonText):'<span>No reason available.</span>';
    $('ec-a-note').innerHTML='<span>Reason:</span> '+reason+' · <span>Next action:</span> '+(a.nextActionAt?esc(hhmm(a.nextActionAt)):'<span>No planned action available.</span>');
  }

  // ---- energy today (supply mix) ----
  function renderMix(data){
    const mix=data.today.supplyMix, el=$('ec-mix');
    if(!mix){$('ec-mix-total').textContent=''; el.innerHTML='<div class="ec-empty">Not available</div>'; return;}
    $('ec-mix-total').textContent=mix.totalKwh.toFixed(1)+' kWh total';
    const rows=[['solar','Solar (used on site)','var(--ec-green)'],['grid','Grid (import)','var(--ec-red)'],['battery','Battery (discharge)','var(--ec-yellow)']];
    const bar='<div class="ec-stack" role="img" aria-label="Share of energy supplied to the home">'+rows.map(([k,,c])=>'<i style="width:'+mix.parts[k].pct+'%;background:'+c+'"></i>').join('')+'</div>';
    const list=rows.map(([k,l,c])=>'<div class="ec-mixrow" style="--c:'+c+'"><span>'+l+'</span><b>'+mix.parts[k].kwh.toFixed(1)+' kWh</b><em>'+Math.round(mix.parts[k].pct)+'%</em></div>').join('');
    el.innerHTML=bar+list+'<p class="ec-mixnote">Share of the energy supplied to the home today.</p>';
  }

  // ---- alerts ----
  const SEV={critical:'Critical',warning:'Warning',info:'Info'};
  const LINK={'battery-soc-below-floor':'/battery','battery-soc-above-ceiling':'/battery','household-meter-mismatch':'/dsmr','forecast-plan-unavailable':'/asset-steering'};
  const COPY={
    'battery-soc-below-floor':{t:'State of charge below minimum',next:'This is a controller threshold, not a hardware fault. Check that the battery charges from surplus.'},
    'battery-soc-above-ceiling':{t:'State of charge above maximum',next:'Check the configured SoC limits and the charging control.'},
    'household-meter-mismatch':{t:'Home consumption deviates',next:'Check that DSMR, solar and battery measurements are current and use the same sign convention.'},
    'forecast-plan-unavailable':{t:'No current forecast or battery plan',next:null},
  };
  const num=v=>Number.isInteger(v)?String(v):v.toFixed(1);
  function alertRow(a){
    const c=COPY[a.id]||{}, sev=SEV[a.severity]?a.severity:'info', parts=[];
    if(a.observed&&a.observed.value!=null)parts.push('<span>Observed</span> <b>'+num(a.observed.value)+esc(a.observed.unit||'')+'</b>');
    if(a.threshold&&a.threshold.value!=null)parts.push('<span>'+(a.threshold.kind==='maximum'?'maximum threshold':'minimum threshold')+'</span> <b>'+num(a.threshold.value)+esc(a.threshold.unit||'')+'</b>');
    if(a.occurred_at)parts.push('<span>since</span> <b>'+esc(hhmm(a.occurred_at))+'</b>');
    const href=LINK[a.id]||(String(a.id).startsWith('health-')?'/health':'/agent');
    return '<a class="ec-alertrow '+sev+'" href="'+href+'"><span class="sv">'+SEV[sev]+'</span><b>'+esc(c.t||a.title)+'</b><svg class="ec-i" viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>'
      +(c.t?'':'<p class="meta">'+esc(a.description)+'</p>')+(parts.length?'<p class="meta">'+parts.join(' · ')+'</p>':'')
      +(c.next?'<p class="next"><span>Next step:</span> <span>'+esc(c.next)+'</span></p>':'')+'</a>';
  }
  function renderAlerts(data){
    const el=$('ec-alerts'), alerts=data.alerts||[];
    if(!alerts.length){
      el.innerHTML=data.connection==='live'?'<div class="ec-alert-ok"><svg class="ec-i" viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg><span>All clear</span></div>':'<div class="ec-alert-ok quiet">No active alerts, but telemetry is not live.</div>';
      return;
    }
    el.innerHTML='<div class="ec-alerts">'+alerts.map(alertRow).join('')+'</div>';
  }

  // ---- overview loop ----
  async function loadOverview(){
    let data=null;
    try{const r=await fetch('/api/dashboard/energy-center'); if(r.ok)data=await r.json();}catch(e){}
    lastData=data;
    renderStatus(data);
    if(!data){
      $('ec-alerts').innerHTML='<div class="ec-alerts"><div class="ec-alertrow critical" role="alert"><span class="sv">Critical</span><b>Energy Center data unavailable</b><p class="meta">The API is unreachable. Try again later.</p></div></div>';
      return;
    }
    renderFlow(data); renderToday(data); renderGoals(data); renderBattery(data); renderAgent(data); renderMix(data); renderAlerts(data);
    drawChart();
  }

  // ---- power chart ----
  const winFor=()=>range==='7d'?'week':range==='30d'?'month':'day';
  async function loadCurves(force){
    const now=Date.now();
    if(!dayCurves||force||now-loadedAt>60000){try{const r=await fetch('/api/dashboard/curves?window=day'); if(r.ok){dayCurves=await r.json(); loadedAt=now;}}catch(e){}}
    if(winFor()!=='day'&&(longWindow!==winFor()||now-longLoadedAt>60000)){try{const r=await fetch('/api/dashboard/curves?window='+winFor()); if(r.ok){longCurves=await r.json(); longWindow=winFor(); longLoadedAt=now;}}catch(e){}}
    return currentCurves();
  }
  const currentCurves=()=>winFor()==='day'?dayCurves:longCurves;
  function domain(c){
    const end=range==='12h'?Date.now():new Date((c&&c.end)||Date.now()).getTime();
    const start=range==='12h'?end-12*3600000:new Date((c&&c.start)||new Date().setHours(0,0,0,0)).getTime();
    return [start,end];
  }
  function ticks(start,end){
    const out=[], long=range==='7d'||range==='30d';
    if(long){const days=Math.round((end-start)/86400000), step=Math.max(1,Math.round(days/7)); for(let t=start;t<=end;t+=step*86400000)out.push(t); return out;}
    const d=new Date(start); d.setMinutes(0,0,0); if(d.getTime()<start)d.setHours(d.getHours()+1); while(d.getHours()%2)d.setHours(d.getHours()+1);
    for(let t=d.getTime();t<=end;){out.push(t); const nx=new Date(t); nx.setHours(nx.getHours()+2); t=nx.getTime();} return out;
  }
  function tickLabel(ts){const d=new Date(ts); return (range==='7d'||range==='30d')?d.toLocaleDateString([], {day:'2-digit',month:'short'}):d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',hour12:false});}
  const pts=(items,key)=>(items||[]).filter(p=>p.timestamp&&Number.isFinite(new Date(p.timestamp).getTime())).map(p=>({t:new Date(p.timestamp).getTime(),w:key?(p[key]??0):(p.power_w||0)}));
  function viewWidth(svg){const h=svg.clientHeight, w=svg.clientWidth; chartW=h>0&&w>0?Math.max(640,Math.min(2400,Math.round(340*w/h))):960; svg.setAttribute('viewBox','0 0 '+chartW+' 340'); return chartW;}
  function drawChart(){
    const svg=$('ec-chart'); if(!svg)return;
    const c=currentCurves()||{}, W=viewWidth(svg), H=340, L=44, R=16, T=22, B=30, mid=(T+H-B)/2, [s0,e0]=domain(c), now=Date.now();
    const series={pv:pts(c.series&&c.series.solar),home:pts(c.series&&c.series.household),battery:pts(c.series&&c.series.battery),grid:pts(c.series&&c.series.grid,'net_w'),forecast:pts(c.forecast),load_forecast:pts(c.load_forecast)};
    const inD=a=>a.filter(p=>p.t>=s0&&p.t<=e0);
    for(const k in series)series[k]=inD(series[k]);
    let peak=5; for(const k of ['pv','home','battery','grid'])for(const p of series[k])peak=Math.max(peak,Math.abs(p.w)/1000);
    const ymax=Math.ceil(peak/2.5)*2.5, X=t=>L+(W-L-R)*(t-s0)/(e0-s0||1), Y=kw=>mid-kw/ymax*(mid-T);
    const gapMs=Math.max(20*60000,3*((c.granularity_seconds||300)*1000));
    const path=a=>{let d='',prev=null; for(const p of a){d+=((prev==null||p.t-prev>gapMs)?'M':'L')+X(p.t).toFixed(1)+' '+Y(p.w/1000).toFixed(1)+' '; prev=p.t;} return d;};
    let o='<defs><linearGradient id="ec-pvfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--ec-green)" stop-opacity=".45"/><stop offset="1" stop-color="var(--ec-green)" stop-opacity=".02"/></linearGradient></defs>';
    for(let k=-2;k<=2;k++){const kw=k*ymax/2, y=Y(kw); o+='<line class="'+(k===0?'zero':'gl')+'" x1="'+L+'" y1="'+y+'" x2="'+(W-R)+'" y2="'+y+'"/><text class="ax" x="6" y="'+(y+4)+'">'+(kw===0?'0':kw.toFixed(kw%1?1:(k<0?1:0)))+'</text>';}
    o+='<text class="ax" x="6" y="12">kW</text>';
    for(const t of ticks(s0,e0))o+='<line class="gl" x1="'+X(t)+'" y1="'+T+'" x2="'+X(t)+'" y2="'+(H-B)+'"/><text class="ax" x="'+X(t)+'" y="'+(H-8)+'" text-anchor="middle">'+tickLabel(t)+'</text>';
    if(visible.pv&&series.pv.length>1){const a=series.pv, d=path(a); if(d)o+='<path d="'+d+' L'+X(a[a.length-1].t).toFixed(1)+' '+Y(0)+' L'+X(a[0].t).toFixed(1)+' '+Y(0)+'Z" fill="url(#ec-pvfill)" stroke="none"/>';}
    for(const k of ['forecast','load_forecast']){if(visible[k]&&series[k].length)o+='<path class="fcl" stroke="'+SERIES[k]+'" d="'+path(series[k])+'"/>';}
    for(const k of ['home','battery','grid','pv']){if(visible[k]&&series[k].length)o+='<path class="ln" stroke="'+SERIES[k]+'" d="'+path(series[k])+'"/>';}
    if(now>=s0&&now<=e0){const x=X(now), lab=tr('Now')+' '+new Date(now).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',hour12:false}); o+='<line class="now" x1="'+x+'" y1="'+(T+4)+'" x2="'+x+'" y2="'+(H-B)+'"/><rect class="nowbx" x="'+(x-34)+'" y="2" width="68" height="22" rx="11"/><text class="nowtx" x="'+x+'" y="18" text-anchor="middle">'+lab+'</text>';}
    svg.innerHTML=o;
    window._ecSeries=series; window._ecDom=[s0,e0,L,R];
    $('ec-leg-fc').hidden=!series.forecast.length; $('ec-leg-lf').hidden=!series.load_forecast.length;
    const msg=$('ec-chart-msg'), ps=c.plan_status;
    if(ps&&ps!=='ok'){msg.hidden=false; msg.textContent={stale:'Planner forecast is stale',fallback:'Planner is in fallback mode, no real forecast',missing:'No planner forecast available'}[ps]||('Plan status: '+ps);} else msg.hidden=true;
    renderForecast(); renderPlan();
  }
  function nearest(a,t){let b=null,bd=Infinity; for(const p of a){const d=Math.abs(p.t-t); if(d<bd){bd=d;b=p;}} return b;}
  function hover(ev){
    const svg=$('ec-chart'), tip=$('ec-tip'), s=window._ecSeries, dom=window._ecDom; if(!s||!dom)return;
    const pt=svg.createSVGPoint(); pt.x=ev.clientX; pt.y=ev.clientY; const loc=pt.matrixTransform(svg.getScreenCTM().inverse());
    const [s0,e0,L,R]=dom, t=s0+Math.max(0,Math.min(1,(loc.x-L)/(chartW-L-R)))*(e0-s0);
    const lines=[]; for(const k in SERIES){if(!visible[k])continue; const p=nearest(s[k]||[],t); if(p&&Math.abs(p.t-t)<45*60000)lines.push('<span style="color:'+SERIES[k]+'">'+tr(SERIES_LABEL[k])+': '+(p.w/1000).toFixed(2)+' kW'+(k==='forecast'||k==='load_forecast'?' ('+tr('forecast')+')':'')+'</span>');}
    if(!lines.length){tip.hidden=true; return;}
    tip.innerHTML='<b>'+new Date(t).toLocaleString([], {hour:'2-digit',minute:'2-digit',day:'2-digit',month:'short'})+'</b>'+lines.join('');
    const wrap=svg.parentElement.getBoundingClientRect(), r=svg.getBoundingClientRect();
    tip.style.left=Math.min(wrap.width-190,Math.max(0,ev.clientX-wrap.left+14))+'px'; tip.style.top=Math.max(0,ev.clientY-wrap.top-20)+'px'; tip.hidden=false;
  }

  // ---- forecast bars + battery plan ----
  function dailyKwh(items,stepSec){
    const days={}; for(const p of pts(items)){const k=new Date(p.t).toDateString(); days[k]=(days[k]||0)+Math.max(0,p.w)*stepSec/3600/1000;} return days;
  }
  function renderForecast(){
    const el=$('ec-fc'), w=weekCache;
    if(!w.forecast||!w.forecast.length){el.innerHTML='<div class="ec-empty">Forecast not available</div>'; return;}
    const step=w.step||900, pv=dailyKwh(w.forecast,step), ld=dailyKwh(w.load_forecast||[],step);
    const keys=Object.keys(pv).slice(0,7); if(!keys.length){el.innerHTML='<div class="ec-empty">Forecast not available</div>'; return;}
    const max=Math.max(1,...keys.map(k=>Math.max(pv[k]||0,ld[k]||0))), top=Math.ceil(max/2.5)*2.5, bw=Math.min(22,170/keys.length), gw=330/keys.length;
    let o='';
    for(let i=0;i<=2;i++){const y=130-i*(100/2), v=top*i/2; o+='<line class="gl" x1="30" x2="350" y1="'+y+'" y2="'+y+'"/><text class="ax" x="2" y="'+(y+4)+'">'+(v%1?v.toFixed(1):v)+'</text>';}
    keys.forEach((k,i)=>{const x=34+i*gw, d=new Date(k), a=(pv[k]||0)/top*100, b=(ld[k]||0)/top*100;
      o+='<rect x="'+(x+gw/2-bw-1)+'" y="'+(130-a)+'" width="'+bw+'" height="'+a+'" rx="3" fill="var(--ec-green)"><title>'+d.toLocaleDateString()+': '+(pv[k]||0).toFixed(1)+' kWh</title></rect>';
      if(ld[k]!=null)o+='<rect x="'+(x+gw/2+1)+'" y="'+(130-b)+'" width="'+bw+'" height="'+b+'" rx="3" fill="var(--ec-blue)"><title>'+d.toLocaleDateString()+': '+ld[k].toFixed(1)+' kWh</title></rect>';
      o+='<text class="ax" x="'+(x+gw/2)+'" y="148" text-anchor="middle">'+d.toLocaleDateString([], {weekday:'short',day:'numeric'})+'</text>';});
    el.innerHTML='<div class="ec-fc-legend"><span style="--c:var(--ec-green)">Expected production</span>'+(Object.keys(ld).length?'<span style="--c:var(--ec-blue)">Expected consumption</span>':'')+'</div><svg viewBox="0 0 360 156" role="img" aria-label="Forecast per day in kWh">'+o+'</svg>';
  }
  const weekCache={};
  async function loadWeek(){
    try{const r=await fetch('/api/dashboard/curves?window=week'); if(r.ok){const j=await r.json(); weekCache.forecast=j.forecast; weekCache.load_forecast=j.load_forecast; weekCache.step=j.granularity_seconds; weekCache.plan=j.plan_status;}}catch(e){}
    renderForecast();
  }
  function renderPlan(){
    const el=$('ec-plan'), c=dayCurves||{}, items=pts(c.battery_forecast);
    if((c.plan_status&&c.plan_status!=='ok')||!items.length){el.innerHTML='<div class="ec-empty">No battery plan available</div>'; return;}
    const [s0,e0]=[new Date(c.start).getTime(),new Date(c.end).getTime()], X=t=>34+316*(t-s0)/(e0-s0||1), step=(c.granularity_seconds||900)*1000, bw=Math.max(2,316*step/(e0-s0||1));
    let o='<line class="gl" x1="30" x2="350" y1="70" y2="70"/>';
    for(const p of items){const kw=p.w/1000, h=Math.min(55,Math.abs(kw)/3*55); if(Math.abs(p.w)<25)continue; o+=kw<0?'<rect x="'+X(p.t)+'" y="'+(70-h)+'" width="'+bw+'" height="'+h+'" fill="var(--ec-green)"/>':'<rect x="'+X(p.t)+'" y="70" width="'+bw+'" height="'+h+'" fill="var(--ec-yellow)"/>';}
    for(let i=0;i<=4;i++)o+='<text class="ax" x="'+(34+i*79)+'" y="146" text-anchor="middle">'+['00:00','06:00','12:00','18:00','00:00'][i]+'</text>';
    el.innerHTML='<div class="ec-fc-legend"><span style="--c:var(--ec-green)">Charge</span><span style="--c:var(--ec-yellow)">Discharge</span><span style="--c:var(--ec-mut)">Standby</span></div><svg viewBox="0 0 360 156" role="img" aria-label="Planned battery charge and discharge, next 24 hours">'+o+'</svg>';
  }

  // ---- controls ----
  document.querySelectorAll('[data-s]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.s; visible[k]=!visible[k]; b.setAttribute('aria-pressed',String(visible[k])); drawChart();}));
  document.querySelectorAll('[data-r]').forEach(b=>b.addEventListener('click',async()=>{range=b.dataset.r; document.querySelectorAll('[data-r]').forEach(x=>x.classList.toggle('active',x===b)); await loadCurves(true); drawChart();}));
  $('ec-chart').addEventListener('mousemove',hover); $('ec-chart').addEventListener('mouseleave',()=>{$('ec-tip').hidden=true;});
  $('ec-theme').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light'; if(window.minyadTheme){window.minyadTheme.save(next).catch(()=>window.minyadTheme.apply(next));}});
  window.addEventListener('resize',()=>{clearTimeout(window._ecRz); window._ecRz=setTimeout(drawChart,150);});

  (async()=>{await loadCurves(true); await loadOverview(); loadWeek();})();
  setInterval(loadOverview,10000);
  setInterval(async()=>{await loadCurves(true); drawChart();},60000);
  setInterval(loadWeek,300000);
  setInterval(()=>renderStatus(lastData),30000);
})();
"""
