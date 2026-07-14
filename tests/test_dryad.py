from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.dryad import (
    build_dryad_payload,
    compute_autarky,
    compute_dispatch_hitrate,
    compute_import_price_penalty,
    compute_trajectory_deviation,
    history_rows_to_daily,
    soc_fraction,
)


def test_autarky_night_without_solar_uses_p1_import() -> None:
    rows = [
        {"ts": "2026-07-07T00:00:00+00:00", "source": "grid", "delivered_w": 500, "returned_w": 0, "net_w": 500},
        {"ts": "2026-07-07T00:00:00+00:00", "source": "solar", "power_w": 0},
        {"ts": "2026-07-07T00:00:00+00:00", "source": "battery", "power_w": 0},
    ]

    assert compute_autarky(rows) == 0.0


def test_autarky_counts_battery_discharge_as_supply() -> None:
    rows = [
        {"ts": "2026-07-07T12:00:00+00:00", "source": "grid", "delivered_w": 0, "returned_w": 0, "net_w": 0},
        {"ts": "2026-07-07T12:00:00+00:00", "source": "solar", "power_w": 1000},
        {"ts": "2026-07-07T12:00:00+00:00", "source": "battery", "power_w": 500},
    ]

    assert compute_autarky(rows) == 1.0


def test_autarky_prefers_existing_household_curve_when_available() -> None:
    rows = [
        {"ts": "2026-07-07T12:00:00+00:00", "source": "grid", "delivered_w": 100, "returned_w": 0, "net_w": 100},
        {"ts": "2026-07-07T12:00:00+00:00", "source": "solar", "power_w": 10_000},
        {"ts": "2026-07-07T12:00:00+00:00", "source": "household", "power_w": 1000},
    ]

    assert compute_autarky(rows) == 0.9


def test_trajectory_deviation_interpolates_plan_and_clamps() -> None:
    now = datetime(2026, 7, 7, 12, 30, tzinfo=UTC)
    plan = {
        "valid_from": "2026-07-07T12:00:00+00:00",
        "slot_seconds": 3600,
        "soc_start_pct": 50,
        "slots": [{"start": "2026-07-07T12:00:00+00:00", "soc_target_pct": 70}],
    }

    assert compute_trajectory_deviation(0.70, plan, 8.0, now) == 1.0


def test_dispatch_hitrate_empty_queue_is_perfect() -> None:
    assert compute_dispatch_hitrate([]) == 1.0


def test_dispatch_hitrate_counts_acknowledged_dispatches() -> None:
    rows = [{"ack_received": True}, {"ack_received": False}, {"ack_received": True}]

    assert compute_dispatch_hitrate(rows) == 2 / 3


def test_import_price_penalty_missing_price_data_returns_null() -> None:
    rows = [{"ts": "2026-07-07T12:00:00+00:00", "delivered_w": 1000}]

    assert compute_import_price_penalty(rows, []) is None


def test_import_price_penalty_weights_expensive_import_kwh() -> None:
    rows = [
        {"ts": "2026-07-07T12:00:00+00:00", "delivered_w": 1000},
        {"ts": "2026-07-07T13:00:00+00:00", "delivered_w": 3000},
    ]
    prices = [
        {"starts_at": "2026-07-07T12:00:00+00:00", "price_eur_kwh": 0.40},
        {"starts_at": "2026-07-07T13:00:00+00:00", "price_eur_kwh": 0.10},
        {"starts_at": "2026-07-07T14:00:00+00:00", "price_eur_kwh": 0.10},
    ]

    assert compute_import_price_penalty(rows, prices, threshold_pct=30) == 0.16875


def test_soc_fraction_clamps_full_battery() -> None:
    assert soc_fraction({"soc": 105}) == 1.0


def test_build_dryad_payload_marks_stale_soc_as_null() -> None:
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    payload = build_dryad_payload(
        now=now,
        mqtt_status={"soc": 80, "bridge_last_seen": (now - timedelta(minutes=10)).isoformat()},
        inputs={"settings": {"battery.inverter_poll_interval_s": "120", "battery.goodwe_poll_interval_grace_s": "60"}},
        prices=[],
    )

    assert payload["soc"] is None
    assert payload["sources"]["soc"]["stale"] is True


def test_build_dryad_payload_keeps_empty_dispatch_queue_perfect() -> None:
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    payload = build_dryad_payload(
        now=now,
        mqtt_status={},
        inputs={"setpoint_rows": [], "latest_setpoint_ts": None, "settings": {}},
        prices=[],
    )

    assert payload["dispatch_hitrate"] == 1.0
    assert payload["sources"]["dispatch_hitrate"]["stale"] is False


def test_build_dryad_payload_marks_missing_soc_value_stale() -> None:
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    payload = build_dryad_payload(
        now=now,
        mqtt_status={"bridge_last_seen": now.isoformat()},
        inputs={"settings": {}},
        prices=[],
    )

    assert payload["soc"] is None
    assert payload["sources"]["soc"]["stale"] is True


def test_history_rows_to_daily_returns_kwh() -> None:
    rows = [{"day": datetime(2026, 7, 7, tzinfo=UTC).date(), "generated_wh": 12_345}]

    assert history_rows_to_daily(rows) == [{"date": "2026-07-07", "solar_kwh": 12.345}]
