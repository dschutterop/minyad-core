import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest


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


def test_fetch_day_ahead_requests_entsoe_xml_and_filters_to_target_day():
    collector = _load_collector()

    class Response:
        text = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Publication_MarketDocument xmlns=\"urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3\">
  <TimeSeries><Period>
    <timeInterval><start>2026-06-24T21:00Z</start></timeInterval>
    <Point><position>1</position><price.amount>20.0</price.amount></Point>
    <Point><position>2</position><price.amount>10.0</price.amount></Point>
  </Period></TimeSeries>
</Publication_MarketDocument>
"""

        def raise_for_status(self):
            pass

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, *, params, timeout):
            self.calls.append((url, params, timeout))
            return Response()

    session = Session()
    client = collector.EntsoeXmlClient(api_key="token", session=session)

    prices = collector.fetch_day_ahead(
        client,
        collector.DayAheadSettings(),
        datetime(2026, 6, 25, 12, 0, tzinfo=collector.AMSTERDAM_TZ),
    )

    assert len(prices) == 1
    assert prices[0]["date"] == "2026-06-25"
    assert prices[0]["hour"] == "00"
    assert prices[0]["price_eur_kwh"] == 0.01
    assert session.calls[0][1]["securityToken"] == "token"
    assert session.calls[0][1]["documentType"] == "A44"
    assert session.calls[0][1]["periodStart"] == "202606242200"
    assert session.calls[0][1]["periodEnd"] == "202606252200"


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
        b"https://web-api.tp.entsoe.eu/api",
    )

    assert store.get().entsoe_api_url == "https://web-api.tp.entsoe.eu/api"
    assert applied == ["https://web-api.tp.entsoe.eu/api"]


def test_trade_settings_reject_invalid_entsoe_api_url_from_mqtt():
    collector = _load_collector()
    store = collector.SettingsStore()

    store.apply_mqtt(f"{collector.MQTT_TOPICS.settings_prefix}/entsoe_api_url", b"not-a-url")

    assert store.get().entsoe_api_url == collector.DAY_AHEAD_DEFAULTS.entsoe_api_url


@pytest.mark.parametrize(
    "value",
    [
        b"http://169.254.169.254/latest/meta-data",
        b"http://minyad-db:5432/",
        b"https://web-api.tp.entsoe.eu@127.0.0.1/api",
    ],
)
def test_trade_settings_reject_non_entsoe_hosts_from_mqtt(value):
    collector = _load_collector()
    store = collector.SettingsStore()

    store.apply_mqtt(f"{collector.MQTT_TOPICS.settings_prefix}/entsoe_api_url", value)

    assert store.get().entsoe_api_url == collector.DAY_AHEAD_DEFAULTS.entsoe_api_url
