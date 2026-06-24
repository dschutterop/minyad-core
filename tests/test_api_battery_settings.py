import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")
if "shared.db" in sys.modules and not hasattr(sys.modules["shared.db"], "get_session"):
    async def _get_session():
        yield None
    sys.modules["shared.db"].get_session = _get_session

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("api_main", ROOT / "api" / "main.py")
api_main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(api_main)


def test_battery_settings_update_accepts_max_charge_a():
    update = api_main.BatterySettingsUpdate(max_charge_a=60)

    assert update.max_charge_a == 60
    assert api_main.BATTERY_KEYS["max_charge_a"] == (1, 200)


def test_battery_settings_update_accepts_nominal_v():
    update = api_main.BatterySettingsUpdate(nominal_v=48)

    assert update.nominal_v == 48


@pytest.mark.parametrize("value", [0, 201])
def test_battery_settings_update_rejects_invalid_max_charge_a(value):
    with pytest.raises(ValidationError):
        api_main.BatterySettingsUpdate(max_charge_a=value)
