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
