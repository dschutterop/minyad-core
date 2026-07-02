from datetime import datetime
from zoneinfo import ZoneInfo

from minyad.strategy.v3.price_client import PriceStore

TZ = ZoneInfo("Europe/Amsterdam")


def test_price_vectors_use_live_entsoe_points_when_available():
    store = PriceStore()
    day = "2026-07-03"
    points = [{"date": day, "hour": f"{h:02d}", "starts_at": f"{day}T{h:02d}:00:00+02:00", "price_eur_kwh": 0.10 + h * 0.01} for h in range(24)]
    store.set_from_entsoe(day, points)
    horizon_start = datetime(2026, 7, 3, 10, 0, tzinfo=TZ)
    import_vec, export_vec = store.price_vectors_for(horizon_start, 8, 900, fixed_import=0.25, fixed_export=0.0)
    assert import_vec[0] == 0.10 + 10 * 0.01
    assert all(price == 0.0 for price in export_vec)


def test_price_vectors_fall_back_to_fixed_when_day_missing():
    store = PriceStore()
    horizon_start = datetime(2026, 7, 3, 10, 0, tzinfo=TZ)
    import_vec, export_vec = store.price_vectors_for(horizon_start, 4, 900, fixed_import=0.25, fixed_export=0.0)
    assert import_vec == [0.25, 0.25, 0.25, 0.25]
    assert export_vec == [0.0, 0.0, 0.0, 0.0]


def test_price_store_evicts_oldest_day_beyond_cache_limit():
    store = PriceStore()
    for i in range(6):
        store.set_from_entsoe(f"2026-07-{i + 1:02d}", [{"date": f"2026-07-{i+1:02d}", "hour": "00", "starts_at": "x", "price_eur_kwh": 0.1}])
    assert len(store._points_by_day) <= 4
    assert "2026-07-01" not in store._points_by_day


def _price_vector_signal(signal_id="signal-1", source="minyad-trade", day="2026-07-03", expired=False, export_price=0.0):
    valid_until = "2026-07-03T10:00:00+02:00" if expired else "2026-07-03T12:00:00+02:00"
    return {
        "id": signal_id,
        "source": source,
        "type": "price_vector",
        "created_at": f"{day}T09:45:00+02:00",
        "valid_from": f"{day}T10:00:00+02:00",
        "valid_until": valid_until,
        "priority": 50,
        "hard": False,
        "payload": {
            "slot_seconds": 900,
            "slots": [
                {
                    "start": f"{day}T10:{minute:02d}:00+02:00",
                    "price_import_eur_kwh": 0.31,
                    "price_export_eur_kwh": export_price,
                }
                for minute in (0, 15, 30, 45)
            ],
        },
    }


def test_invariant_16_no_market_signals_use_fixed_vectors():
    store = PriceStore()
    inputs = store.planner_inputs_for(datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 4, 900, fixed_import=0.25, fixed_export=0.01)
    assert inputs.price_import == [0.25] * 4
    assert inputs.price_export == [0.01] * 4
    assert inputs.market_signal_ids == []


def test_invariant_17_price_vector_matches_equivalent_legacy_payload():
    horizon_start = datetime(2026, 7, 3, 10, 0, tzinfo=TZ)
    legacy = PriceStore()
    legacy.set_from_entsoe(
        "2026-07-03",
        [{"date": "2026-07-03", "hour": "10", "starts_at": "2026-07-03T10:00:00+02:00", "price_eur_kwh": 0.31}],
    )
    normalized = PriceStore()
    normalized.set_market_signal(_price_vector_signal())

    legacy_inputs = legacy.planner_inputs_for(horizon_start, 4, 900, fixed_import=0.25, fixed_export=0.0)
    normalized_inputs = normalized.planner_inputs_for(horizon_start, 4, 900, fixed_import=0.25, fixed_export=0.0)

    assert normalized_inputs.price_import == legacy_inputs.price_import
    assert normalized_inputs.price_export == legacy_inputs.price_export


def test_invariant_18_expired_signals_are_ignored():
    store = PriceStore()
    store.set_market_signal(_price_vector_signal(expired=True), now=datetime(2026, 7, 3, 10, 1, tzinfo=TZ))
    inputs = store.planner_inputs_for(datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 4, 900, fixed_import=0.25, fixed_export=0.0)
    assert inputs.price_import == [0.25] * 4
    assert inputs.market_signal_ids == []


def test_invariant_19_reserved_and_unknown_signal_types_are_ignored(caplog):
    store = PriceStore()
    store.set_market_signal({"id": "grid-1", "type": "grid_constraint", "source": "test", "payload": {}})
    store.set_market_signal({"id": "weird-1", "type": "surprise", "source": "test", "payload": {}})
    inputs = store.planner_inputs_for(datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 4, 900, fixed_import=0.25, fixed_export=0.0)
    assert inputs.price_import == [0.25] * 4
    assert "grid_constraint" in store._ignored_signal_types
    assert "surprise" in store._ignored_signal_types


def test_market_signal_metadata_is_exposed_when_used():
    store = PriceStore()
    store.set_market_signal(_price_vector_signal(signal_id="sig-abc", source="minyad-trade"))
    inputs = store.planner_inputs_for(datetime(2026, 7, 3, 10, 0, tzinfo=TZ), 4, 900, fixed_import=0.25, fixed_export=0.0)
    assert inputs.market_signal_ids == ["sig-abc"]
    assert inputs.constraint_reasons == ["price_vector:minyad-trade"]
