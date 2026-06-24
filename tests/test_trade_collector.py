import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def _load_collector():
    module_dir = Path(__file__).resolve().parents[1] / "minyad-trade"
    module_path = module_dir / "epex_collector.py"
    sys.path.insert(0, str(module_dir))
    spec = importlib.util.spec_from_file_location("epex_collector", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_startup_target_day_is_tomorrow_in_amsterdam_timezone():
    collector = _load_collector()

    target = collector._target_day(datetime(2026, 6, 24, 12, 0, tzinfo=collector.AMSTERDAM_TZ))

    assert target.date().isoformat() == "2026-06-25"


def test_next_poll_time_rolls_to_tomorrow_after_poll_time():
    collector = _load_collector()

    now = datetime(2026, 6, 24, 14, 0, tzinfo=collector.AMSTERDAM_TZ)
    poll_at = collector.next_poll_time(now, "13:30")

    assert poll_at.isoformat() == "2026-06-25T13:30:00+02:00"


def test_fetch_day_ahead_filters_entsoe_expanded_window_to_target_day():
    collector = _load_collector()

    class Client:
        def query_day_ahead_prices(self, _zone, *, start, end):
            return collector.pd.Series(
                [20.0, 10.0],
                index=collector.pd.DatetimeIndex([
                    "2026-06-24T23:00:00+02:00",
                    "2026-06-25T00:00:00+02:00",
                ]),
            )

    prices = collector.fetch_day_ahead(
        Client(),
        collector.DayAheadSettings(),
        datetime(2026, 6, 25, 12, 0, tzinfo=collector.AMSTERDAM_TZ),
    )

    assert len(prices) == 1
    assert prices[0]["date"] == "2026-06-25"
    assert prices[0]["hour"] == "00"


def test_startup_falls_back_to_current_day_when_tomorrow_unavailable(monkeypatch):
    collector = _load_collector()
    calls = []

    retried = []

    def fake_collect(_client, _mqtt, _settings, target_day):
        calls.append(target_day.date().isoformat())
        if len(calls) == 1:
            raise RuntimeError("not published yet")

    def fake_retry(_client, _mqtt, _settings, target_day):
        retried.append(target_day.date().isoformat())
        return True

    monkeypatch.setattr(collector, "collect_once", fake_collect)
    monkeypatch.setattr(collector, "collect_with_retries", fake_retry)

    collector.collect_startup_prices(
        object(),
        object(),
        collector.DayAheadSettings(),
        datetime(2026, 6, 24, 12, 0, tzinfo=collector.AMSTERDAM_TZ),
    )

    assert calls == ["2026-06-25", "2026-06-24"]
    assert retried == ["2026-06-25"]


def test_trade_settings_apply_entsoe_api_url_from_mqtt(monkeypatch):
    collector = _load_collector()
    applied = []
    store = collector.SettingsStore()

    monkeypatch.setattr(collector, "apply_entsoe_api_url", applied.append)

    store.apply_mqtt(
        f"{collector.MQTT_TOPICS.settings_prefix}/entsoe_api_url",
        b"https://example.test/entsoe/api",
    )

    assert store.get().entsoe_api_url == "https://example.test/entsoe/api"
    assert applied == ["https://example.test/entsoe/api"]


def test_trade_settings_reject_invalid_entsoe_api_url_from_mqtt():
    collector = _load_collector()
    store = collector.SettingsStore()

    store.apply_mqtt(f"{collector.MQTT_TOPICS.settings_prefix}/entsoe_api_url", b"not-a-url")

    assert store.get().entsoe_api_url == collector.DAY_AHEAD_DEFAULTS.entsoe_api_url
