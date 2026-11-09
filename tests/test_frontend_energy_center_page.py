"""Route-level tests for the /energy-center page (frontend/main.py, frontend/views.py,
frontend/energy_center.py). No httpx mocking needed: _brand_name() falls back to
"Minyad Core" when the (unreachable in tests) API service can't be reached.
"""

import os

os.environ.setdefault("API_BASE_URL", "https://minyad-api:8000")

from fastapi.testclient import TestClient

import frontend.main as frontend_main

app = frontend_main.app


def _page() -> str:
    with TestClient(app) as client:
        response = client.get("/energy-center")
    assert response.status_code == 200
    return response.text


def test_energy_center_route_renders_new_page():
    html = _page()

    assert 'class="ec-page"' in html
    assert 'id="ec-conn"' in html
    assert "fetch('/api/dashboard/energy-center')" in html


def test_energy_center_is_in_primary_navigation_and_dashboard_nav():
    assert 'href="/energy-center"' in _page()
    with TestClient(app) as client:
        dashboard = client.get("/")
    assert "href='/energy-center'" in dashboard.text


def test_dashboard_route_unchanged_by_energy_center():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="ec-conn"' not in response.text
    assert 'class="ec-page"' not in response.text


def test_energy_center_catch_all_section_route_is_shadowed_by_dedicated_route():
    assert "Energy Center module scaffold" not in _page()


def test_energy_center_source_strings_are_english_and_have_dutch_translations():
    html = _page()

    for text in ("Live energy flow", "Daily goals", "Alerts &amp; actions", "Battery plan", "Forecast not available"):
        assert text in html
    # Dutch interface: the shared dictionary translates the English source strings.
    for english, dutch in (("Daily goals", "Dagdoelen"), ("All clear", "Alles in orde"), ("Not available", "Niet beschikbaar")):
        assert f"'{english}': '{dutch}'" in html


def test_energy_center_has_flow_diagram_with_text_alternative():
    html = _page()

    assert 'id="ec-flow-svg"' in html and 'role="img"' in html
    assert 'id="ec-flow-d"' in html  # description updated with the live values
    for icon_id in ("ec-fl-pv", "ec-fl-bat", "ec-fl-grid", "ec-fl-home"):
        assert f'id="{icon_id}"' in html


def test_energy_center_matches_mockup_layout_sections():
    html = _page()

    for section in ("Live energy flow", "Today", "Self-sufficient", "Daily goals", "Battery", "VPP / Agent",
                    "Energy today", "Forecast \u2013 Production", "Battery plan", "Alerts"):
        assert f'aria-label="{section}' in html or f"<h2>{section}" in html


def test_energy_center_script_never_renders_negative_zero_or_missing_as_zero():
    html = _page()

    assert "if(r===0)return '0.00'" in html
    assert "Not available" in html  # missing totals say so instead of showing 0 kWh
    assert "data.connection==='live'" in html  # "All clear" only when telemetry is live


def test_energy_center_severity_is_a_word_not_only_a_colour():
    html = _page()

    assert "Critical" in html and "Warning" in html
    assert "ec-alertrow" in html
