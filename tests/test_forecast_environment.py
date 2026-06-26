from __future__ import annotations

import importlib.util
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forecast_installation_values_come_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("FORECAST_LATITUDE", "52.123")
    monkeypatch.setenv("FORECAST_LONGITUDE", "5.456")
    monkeypatch.setenv("SOLAR_PEAK_W", "7200")

    spec = importlib.util.spec_from_file_location(
        "forecast_environment_test",
        ROOT / "forecast" / "main.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.LATITUDE == 52.123
    assert module.LONGITUDE == 5.456
    assert module.PEAK_W == 7200


def test_api_installation_values_use_environment_names() -> None:
    source = (ROOT / "api" / "main.py").read_text()

    assert 'os.getenv("FORECAST_LATITUDE"' in source
    assert 'os.getenv("FORECAST_LONGITUDE"' in source
    assert 'os.getenv("SOLAR_PEAK_W"' in source
