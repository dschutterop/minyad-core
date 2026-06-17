"""Traditional Minyad web UI scaffold."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Minyad Frontend")

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
        </style>
      </head>
      <body><nav><h1>Minyad</h1>{links}</nav><main>{body}</main></body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return render_page("Dashboard", "<div class='card'><h2>Energy Flow</h2><p>Solar → Home → Battery → Grid, health, and forecast placeholders.</p></div>")


@app.get("/{section}", response_class=HTMLResponse)
async def section(section: str) -> str:
    title = "DSMR" if section.lower() == "dsmr" else section.capitalize()
    if title not in MENU:
        title = "Dashboard"
    content = "Runtime settings are loaded from PostgreSQL and secrets are stored encrypted." if title == "Settings" else f"{title} module scaffold."
    return render_page(title, f"<div class='card'><h2>{title}</h2><p>{content}</p></div>")
