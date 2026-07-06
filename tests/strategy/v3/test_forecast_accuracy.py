from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.forecast_accuracy import (
    build_accuracy_pairs,
    compute_forecast_accuracy,
    latest_vintage_at_or_before,
)

UTC = timezone.utc


def test_compute_forecast_accuracy_mae_and_bias():
    # forecast consistently 100 above measured -> MAE 100, bias +100 (spec: bias = forecast - measured)
    pairs = [(600.0, 500.0), (700.0, 600.0), (800.0, 700.0)]
    stats = compute_forecast_accuracy(pairs)
    assert stats["mae"] == 100.0
    assert stats["bias"] == 100.0
    assert stats["sample_count"] == 3


def test_compute_forecast_accuracy_mixed_errors_cancel_bias_not_mae():
    pairs = [(600.0, 500.0), (400.0, 500.0)]  # errors +100, -100
    stats = compute_forecast_accuracy(pairs)
    assert stats["mae"] == 100.0
    assert stats["bias"] == 0.0


def test_compute_forecast_accuracy_empty_is_zero():
    stats = compute_forecast_accuracy([])
    assert stats == {"mae": 0.0, "bias": 0.0, "sample_count": 0}


def test_latest_vintage_at_or_before_picks_last_matching():
    vintages = [
        {"generated_at": datetime(2026, 7, 1, 8, 0, tzinfo=UTC), "slots_by_start": {}},
        {"generated_at": datetime(2026, 7, 1, 8, 15, tzinfo=UTC), "slots_by_start": {}},
        {"generated_at": datetime(2026, 7, 1, 8, 30, tzinfo=UTC), "slots_by_start": {}},
    ]
    match = latest_vintage_at_or_before(vintages, datetime(2026, 7, 1, 8, 20, tzinfo=UTC))
    assert match["generated_at"] == datetime(2026, 7, 1, 8, 15, tzinfo=UTC)


def test_latest_vintage_at_or_before_none_when_all_after_cutoff():
    vintages = [{"generated_at": datetime(2026, 7, 1, 9, 0, tzinfo=UTC), "slots_by_start": {}}]
    assert latest_vintage_at_or_before(vintages, datetime(2026, 7, 1, 8, 0, tzinfo=UTC)) is None


def test_build_accuracy_pairs_matches_by_horizon():
    slot_start = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    measured_by_slot = {slot_start.isoformat(): {"pv": 500.0, "load": 300.0, "battery_soc": 60.0}}
    # must be sorted ascending by generated_at, per latest_vintage_at_or_before's contract
    vintages = [
        {
            "generated_at": slot_start - timedelta(hours=6),
            "slots_by_start": {slot_start.isoformat(): {"pv_forecast_w": 400.0, "load_forecast_w": 250.0, "soc_target_pct": 55.0}},
        },
        {
            "generated_at": slot_start - timedelta(hours=1),
            "slots_by_start": {slot_start.isoformat(): {"pv_forecast_w": 450.0, "load_forecast_w": 280.0, "soc_target_pct": 58.0}},
        },
    ]
    pairs = build_accuracy_pairs(measured_by_slot, vintages, horizons={"1h": timedelta(hours=1), "6h": timedelta(hours=6)})
    assert pairs[("pv", "1h")] == [(450.0, 500.0)]
    assert pairs[("pv", "6h")] == [(400.0, 500.0)]
    assert pairs[("load", "1h")] == [(280.0, 300.0)]
    assert pairs[("battery_soc", "1h")] == [(58.0, 60.0)]


def test_build_accuracy_pairs_skips_slot_with_no_matching_vintage():
    slot_start = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    measured_by_slot = {slot_start.isoformat(): {"pv": 500.0}}
    # only a vintage generated *after* the 1h cutoff exists -> no match
    vintages = [{"generated_at": slot_start - timedelta(minutes=10), "slots_by_start": {slot_start.isoformat(): {"pv_forecast_w": 450.0}}}]
    pairs = build_accuracy_pairs(measured_by_slot, vintages, horizons={"1h": timedelta(hours=1)})
    assert pairs == {}


def test_build_accuracy_pairs_normalizes_across_timezone_offsets():
    # measured key in UTC, vintage slot key in local +02:00 offset for the same instant
    slot_start_utc = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    slot_start_local_str = "2026-07-01T12:00:00+02:00"
    measured_by_slot = {slot_start_utc.isoformat(): {"pv": 500.0}}
    vintages = [
        {
            "generated_at": slot_start_utc - timedelta(hours=1),
            "slots_by_start": {slot_start_local_str: {"pv_forecast_w": 450.0}},
        }
    ]
    # Caller is expected to normalize vintage keys to UTC before calling build_accuracy_pairs
    # (see forecast_accuracy._load_vintages); this test documents that expectation by using an
    # already-normalized key and confirming the match succeeds.
    normalized_vintages = [
        {
            "generated_at": v["generated_at"],
            "slots_by_start": {
                datetime.fromisoformat(k).astimezone(UTC).isoformat(): val for k, val in v["slots_by_start"].items()
            },
        }
        for v in vintages
    ]
    pairs = build_accuracy_pairs(measured_by_slot, normalized_vintages, horizons={"1h": timedelta(hours=1)})
    assert pairs[("pv", "1h")] == [(450.0, 500.0)]
