import importlib.util
import os
import sys
import asyncio
from datetime import datetime, timedelta, timezone
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


def test_battery_settings_update_accepts_goodwe_poll_interval_grace():
    update = api_main.BatterySettingsUpdate(goodwe_poll_interval_grace_s=60)

    assert update.goodwe_poll_interval_grace_s == 60
    assert api_main.BATTERY_KEYS["goodwe_poll_interval_grace_s"] == (0, 3600)


def test_bridge_stale_seconds_is_derived_from_poll_interval_and_grace():
    assert api_main.derived_bridge_stale_seconds({"inverter_poll_interval_s": 120, "goodwe_poll_interval_grace_s": 60}) == 180
    assert api_main.derived_bridge_stale_seconds({"inverter_poll_interval_s": 45, "goodwe_poll_interval_grace_s": 10}) == 55


def test_battery_override_accepts_and_normalizes_charge_aliases():
    api_main.BatteryOverrideRequest.model_rebuild(_types_namespace={"Literal": api_main.Literal})
    legacy = api_main.BatteryOverrideRequest(mode="force_on", watts=700)
    current = api_main.BatteryOverrideRequest(mode="force_charge", watts=700)
    soc_override = api_main.BatteryOverrideRequest(mode="force_discharge", watts=700, override_soc_limits=True)

    assert legacy.mode == "force_on"
    assert current.mode == "force_charge"
    assert soc_override.override_soc_limits is True
    assert api_main._normalize_battery_override_mode(legacy.mode) == "force_charge"
    assert api_main._normalize_battery_override_mode("force_off") == "force_idle"


def test_agent_hold_preserves_active_manual_battery_override():
    class Result:
        def mappings(self):
            return self

        def first(self):
            return {
                "mode": "force_discharge",
                "watts": 900,
                "duration_seconds": 900,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                "override_soc_limits": True,
            }

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement, *_args, **_kwargs):
            self.statements.append(str(statement))
            return Result()

    session = Session()
    request = api_main.AgentBatteryControlRequest(setpoint_w=0)

    response = asyncio.run(api_main.api_control_battery(request, session))

    assert response["action"] == "hold"
    assert response["override"]["mode"] == "force_discharge"
    assert response["override"]["override_soc_limits"] is True
    assert response["override"]["preserved"] is True
    assert len(session.statements) == 1


@pytest.mark.parametrize("value", [0, 201])
def test_battery_settings_update_rejects_invalid_max_charge_a(value):
    with pytest.raises(ValidationError):
        api_main.BatterySettingsUpdate(max_charge_a=value)


def test_trade_settings_update_accepts_entsoe_api_url():
    update = api_main.TradeSettingsUpdate(entsoe_api_url="https://web-api.tp.entsoe.eu/api")

    assert update.entsoe_api_url == "https://web-api.tp.entsoe.eu/api"
    assert api_main.TRADE_DEFAULTS["entsoe_api_url"] == "https://web-api.tp.entsoe.eu/api"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-url",
        "ftp://web-api.tp.entsoe.eu/api",
        "https://example.test/entsoe/api",
        "https://web-api.tp.entsoe.eu.evil.test/api",
        "https://web-api.tp.entsoe.eu@127.0.0.1/api",
        "https://web-api.tp.entsoe.eu:8443/api",
    ],
)
def test_trade_settings_update_rejects_invalid_entsoe_api_url(value):
    with pytest.raises(ValidationError):
        api_main.TradeSettingsUpdate(entsoe_api_url=value)


def test_claude_agent_settings_update_defaults_and_validation():
    update = api_main.ClaudeAgentSettingsUpdate(min_tokens_remaining=0)

    assert update.min_tokens_remaining == 0
    assert api_main.CLAUDE_AGENT_DEFAULTS == {
        "enabled": "false",
        "token_guard_enabled": "true",
        "min_tokens_remaining": "5000",
    }


def test_claude_agent_settings_update_rejects_negative_min_tokens():
    with pytest.raises(ValidationError):
        api_main.ClaudeAgentSettingsUpdate(min_tokens_remaining=-1)


def test_system_settings_update_accepts_supported_languages():
    api_main.SystemSettingsUpdate.model_rebuild(_types_namespace={"Literal": api_main.Literal})

    assert api_main.SystemSettingsUpdate(language="en").language == "en"
    assert api_main.SystemSettingsUpdate(language="nl").language == "nl"


def test_system_settings_update_rejects_unsupported_language():
    api_main.SystemSettingsUpdate.model_rebuild(_types_namespace={"Literal": api_main.Literal})

    with pytest.raises(ValidationError):
        api_main.SystemSettingsUpdate(language="de")
