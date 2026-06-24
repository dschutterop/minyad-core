import json
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

from api.main import TRADE_PRICE_CACHE, handle_trade_price_mqtt, latest_trade_prices


def test_handle_trade_price_mqtt_normalizes_and_sorts_payload():
    TRADE_PRICE_CACHE.clear()
    handle_trade_price_mqtt(
        "minyad/trade/prices/da/2026-06-25/full",
        json.dumps([
            {"date": "2026-06-25", "hour": "02", "starts_at": "2026-06-25T02:00:00+02:00", "price_eur_kwh": "0.12"},
            {"date": "2026-06-25", "hour": "01", "starts_at": "2026-06-25T01:00:00+02:00", "price_eur_kwh": 0.08},
        ]).encode(),
    )

    prices = latest_trade_prices()

    assert [point["hour"] for point in prices] == ["01", "02"]
    assert [point["price_eur_kwh"] for point in prices] == [0.08, 0.12]
