import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from minyad.strategy.v2.consumption_profile import ConsumptionProfile
from minyad.strategy.v3 import consumption_profile
from minyad.strategy.v3.consumption_profile import (
    HouseholdLoadProfile,
    fetch_flex_load_wh,
    fit_temperature_betas,
    split_baseline_rows,
    split_rows_by_daytype,
)

UTC = timezone.utc


def test_split_baseline_rows_subtracts_flex_load():
    slot = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    rows = [(slot, 800.0)]
    # 200 Wh dispatched by Vesper in a 15-min (0.25h) slot = 800 W average flex draw
    flex = {slot: 200.0}
    baseline = split_baseline_rows(rows, flex)
    assert baseline == [(slot, 0.0)]


def test_split_baseline_rows_partial_subtraction():
    slot = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    rows = [(slot, 800.0)]
    flex = {slot: 100.0}  # 100 Wh / 0.25h = 400 W
    baseline = split_baseline_rows(rows, flex)
    assert baseline == [(slot, 400.0)]


def test_split_baseline_rows_no_flex_data_for_slot_is_unchanged():
    slot = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    rows = [(slot, 800.0)]
    baseline = split_baseline_rows(rows, {})
    assert baseline == [(slot, 800.0)]


def test_split_baseline_rows_clips_negative_to_zero():
    slot = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    rows = [(slot, 300.0)]
    flex = {slot: 200.0}  # 200 Wh / 0.25h = 800 W > 300 W measured -> would go negative
    baseline = split_baseline_rows(rows, flex)
    assert baseline == [(slot, 0.0)]


def test_split_baseline_rows_matches_slots_across_timezone_offsets():
    # measured row in UTC, flex-load key given with a different (but equal-instant) offset
    slot_utc = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    rows = [(slot_utc, 800.0)]
    slot_plus2 = slot_utc.astimezone(timezone(timedelta(hours=2)))
    flex = {slot_plus2: 200.0}
    baseline = split_baseline_rows(rows, flex)
    assert baseline == [(slot_utc, 0.0)]


def test_split_baseline_rows_preserves_order_and_length():
    rows = [
        (datetime(2026, 7, 1, 12, 0, tzinfo=UTC), 800.0),
        (datetime(2026, 7, 1, 12, 15, tzinfo=UTC), 500.0),
    ]
    baseline = split_baseline_rows(rows, {})
    assert len(baseline) == 2
    assert [ts for ts, _ in baseline] == [row[0] for row in rows]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    calls = []
    payload = {}
    fail = False

    def __init__(self, *, verify):
        self.verify = verify

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, *, params, headers):
        FakeAsyncClient.calls.append({"url": url, "params": params, "headers": headers, "verify": self.verify})
        if FakeAsyncClient.fail:
            raise RuntimeError("boom")
        return FakeResponse(FakeAsyncClient.payload)


def test_fetch_flex_load_wh_parses_slots_and_skips_bad_entries(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.fail = False
    FakeAsyncClient.payload = {
        "slots": [
            {"start": "2026-07-01T10:00:00+02:00", "flex_load_wh": "125.5"},
            {"start": "bad", "flex_load_wh": 999},
            {"flex_load_wh": 999},
        ]
    }
    monkeypatch.setattr(consumption_profile.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(consumption_profile.Path, "is_file", lambda self: False)

    result = asyncio.run(
        fetch_flex_load_wh(
            "https://vesper.local",
            "secret",
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 2, tzinfo=UTC),
        )
    )

    assert result == {datetime(2026, 7, 1, 8, 0, tzinfo=UTC): 125.5}
    assert FakeAsyncClient.calls[0]["url"] == "https://vesper.local/api/minyad/dispatch-ledger"
    assert FakeAsyncClient.calls[0]["headers"] == {"X-API-Key": "secret"}
    assert FakeAsyncClient.calls[0]["verify"] is True


def test_fetch_flex_load_wh_returns_empty_on_failure(monkeypatch):
    FakeAsyncClient.fail = True
    monkeypatch.setattr(consumption_profile.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        fetch_flex_load_wh(
            "https://vesper.local",
            None,
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 2, tzinfo=UTC),
        )
    )

    assert result == {}
    FakeAsyncClient.fail = False


def test_split_rows_by_daytype_reports_history_sufficiency():
    monday = datetime(2026, 7, 6, 10, 0, tzinfo=UTC)
    saturday = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)
    rows = [(monday + timedelta(days=i), 100.0) for i in range(5)] + [(saturday, 200.0)]

    weekday_rows, weekend_rows, weekday_ok, weekend_ok = split_rows_by_daytype(rows, UTC, min_days=1)

    assert len(weekday_rows) == 5
    assert len(weekend_rows) == 1
    assert weekday_ok is True
    assert weekend_ok is True


def test_fit_temperature_betas_by_daypart():
    row_time = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
    rows = [(row_time, 500.0), (datetime(2026, 7, 1, 2, 0, tzinfo=UTC), 100.0)]
    temps = [(row_time, 27.0), (row_time + timedelta(hours=1), 27.0)]

    betas = fit_temperature_betas(rows, temps, lambda _ts: 300.0, UTC, t_ref_c=22.0)

    assert betas["afternoon"] == 40.0
    assert betas["night"] == -40.0
    assert betas["morning"] == 0.0
    assert betas["evening"] == 0.0


def test_household_load_profile_selects_daytype_and_temperature_correction():
    weekday = ConsumptionProfile({slot: 100.0 for slot in range(96)}, tz=UTC)
    weekend = ConsumptionProfile({slot: 200.0 for slot in range(96)}, tz=UTC)
    profile = HouseholdLoadProfile(weekday, weekend, {"afternoon": 10.0}, t_ref_c=22.0, tz=UTC)

    assert profile.expected_w(datetime(2026, 7, 1, 14, 0, tzinfo=UTC), temperature_c=25.0) == 130.0
    assert profile.expected_w(datetime(2026, 7, 4, 14, 0, tzinfo=UTC), temperature_c=25.0) == 230.0
    assert profile.expected_w(datetime(2026, 7, 4, 14, 0, tzinfo=UTC), temperature_c=None) == 200.0
    assert profile.has_history is True


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement, _params):
        return FakeResult(self.rows)


class FakeSessionFactory:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self):
        return FakeSession(self.rows)


def test_load_baseline_consumption_profile_falls_back_and_fits_temperature(monkeypatch):
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    rows = [
        type("Row", (), {"bucket_start": now - timedelta(days=day), "power_w": 500.0})()
        for day in range(1, 8)
    ]
    rows.append(type("Row", (), {"bucket_start": now - timedelta(days=8), "power_w": None})())

    async def fake_temperature_fetcher(**_kwargs):
        await asyncio.sleep(0)
        return [(now - timedelta(days=1), 27.0), (now, 27.0)]

    profile = asyncio.run(
        consumption_profile.load_baseline_consumption_profile(
            FakeSessionFactory(rows),
            vesper_api_url=None,
            tz=UTC,
            lookback_days=7,
            fallback_w=300.0,
            now=now,
            temperature_fetcher=fake_temperature_fetcher,
        )
    )

    assert isinstance(profile, HouseholdLoadProfile)
    assert profile.has_history
    assert set(profile.temp_betas) == {"night", "morning", "afternoon", "evening"}


def test_load_baseline_consumption_profile_applies_flex_split_and_temperature_failure(monkeypatch):
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    rows = [type("Row", (), {"bucket_start": now - timedelta(days=1), "power_w": 800.0})()]

    async def fake_fetch_flex(*_args, **_kwargs):
        await asyncio.sleep(0)
        return {rows[0].bucket_start: 100.0}

    async def failing_temperature_fetcher(**_kwargs):
        await asyncio.sleep(0)
        raise RuntimeError("no weather")

    monkeypatch.setattr(consumption_profile, "fetch_flex_load_wh", fake_fetch_flex)

    profile = asyncio.run(
        consumption_profile.load_baseline_consumption_profile(
            FakeSessionFactory(rows),
            vesper_api_url="https://vesper.local",
            vesper_api_key="secret",
            tz=UTC,
            lookback_days=7,
            fallback_w=300.0,
            now=now,
            temperature_fetcher=failing_temperature_fetcher,
        )
    )

    assert profile.temp_betas == {}
    assert profile.expected_w(rows[0].bucket_start) == pytest.approx(400.0)
