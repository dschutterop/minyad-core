import logging
import time
from dataclasses import dataclass
from typing import Any

from minyad.common.config import get_config
from minyad.common.db import (
    connect,
    get_settings,
    insert_reading,
    latest,
    latest_forecast,
    setting_float,
    setting_int,
)
from minyad.common.status import update_status
from minyad.common.time import utc_now
from minyad.integrations.goodwe import GoodWeClient, build_goodwe_client

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    trigger: str
    action: str
    target_w: int
    details: dict[str, Any]


def battery_net_w(battery: dict[str, Any] | None) -> int:
    if not battery:
        return 0
    return int(battery.get("discharge_w") or 0) - int(battery.get("charge_w") or 0)


def tomorrow_forecast_kwh(forecast: list[dict[str, Any]]) -> float:
    return sum(int(row.get("predicted_w") or 0) for row in forecast[:24]) / 1000.0


def decide(
    grid: dict[str, Any] | None,
    solar: dict[str, Any] | None,
    battery: dict[str, Any] | None,
    settings: dict[str, str],
    forecast: list[dict[str, Any]],
) -> Decision:
    if not grid or not solar or not battery:
        return Decision("missing_data", "idle", 0, {"grid": bool(grid), "solar": bool(solar), "battery": bool(battery)})

    import_w = int(grid.get("import_w") or 0)
    export_w = int(grid.get("export_w") or 0)
    production_w = int(solar.get("production_w") or 0)
    batt_net = battery_net_w(battery)
    soc = float(battery.get("soc_pct") or 0)
    net_power = import_w - export_w
    house_load = max(0, net_power + production_w - batt_net)
    solar_surplus_w = max(0, production_w - house_load)

    tolerance = setting_int(settings, "export_tolerance_w", 50)
    min_soc = setting_float(settings, "min_soc_pct", 15)
    max_soc = setting_float(settings, "max_soc_pct", 95)
    threshold = setting_int(settings, "charge_threshold_w", 200)
    max_charge = setting_int(settings, "battery_max_charge_w", 4600)
    max_discharge = setting_int(settings, "battery_max_discharge_w", 4600)
    low_solar_kwh = setting_float(settings, "low_solar_forecast_kwh", 8.0)
    forecast_floor = setting_float(settings, "min_forecast_soc_pct", 35)
    effective_min_soc = max(min_soc, forecast_floor) if tomorrow_forecast_kwh(forecast) < low_solar_kwh else min_soc

    details = {
        "grid_import_w": import_w,
        "grid_export_w": export_w,
        "net_power_w": net_power,
        "production_w": production_w,
        "battery_net_w": batt_net,
        "house_load_w": house_load,
        "solar_surplus_w": solar_surplus_w,
        "soc_pct": soc,
        "effective_min_soc_pct": effective_min_soc,
    }

    if export_w > tolerance and soc < max_soc:
        target = min(max_charge, export_w - tolerance + int(battery.get("charge_w") or 0))
        return Decision("zero_export", "charge", target, details)

    if export_w > tolerance and soc >= max_soc:
        return Decision("zero_export", "curtail_solar", export_w - tolerance, details)

    if solar_surplus_w > threshold and soc < max_soc:
        target = min(max_charge, solar_surplus_w)
        return Decision("self_consumption", "charge", target, details)

    if import_w > threshold and production_w < house_load and soc > effective_min_soc:
        target = min(max_discharge, import_w)
        return Decision("self_consumption", "discharge", target, details)

    return Decision("balanced", "idle", 0, details)


def apply_decision(client: GoodWeClient, decision: Decision) -> int | None:
    if decision.action == "charge":
        client.set_charge_power(decision.target_w)
        return decision.target_w
    if decision.action == "discharge":
        client.set_discharge_power(decision.target_w)
        return decision.target_w
    if decision.action in {"idle", "curtail_solar"}:
        client.set_idle()
        return 0
    return None


def run_once(client: GoodWeClient) -> Decision:
    with connect() as conn:
        settings = get_settings(conn)
        grid = latest(conn, "grid_readings")
        solar = latest(conn, "solar_readings")
        battery = latest(conn, "battery_readings")
        forecast = latest_forecast(conn, hours=24)
        decision = decide(grid, solar, battery, settings, forecast)
    actual = apply_decision(client, decision)
    with connect() as conn:
        insert_reading(
            conn,
            "control_log",
            {
                "timestamp": utc_now(),
                "trigger": decision.trigger,
                "action": decision.action,
                "target_w": decision.target_w,
                "actual_w": actual,
                "details": decision.details,
            },
        )
        update_status(conn, "control", "ok", {"action": decision.action, "target_w": decision.target_w})
    return decision


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    client = build_goodwe_client(get_config())
    while True:
        interval = 10
        try:
            decision = run_once(client)
            LOG.info("Control decision: %s", decision)
            with connect() as conn:
                interval = setting_int(get_settings(conn), "control_loop_interval_s", 10)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Control loop failed: %s", exc)
            with connect() as conn:
                update_status(conn, "control", "error", {"error": str(exc)})
                interval = setting_int(get_settings(conn), "control_loop_interval_s", 10)
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
