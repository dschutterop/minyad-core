import asyncio
from datetime import date, datetime, timedelta, timezone

from minyad.strategy.v3 import forecast_accuracy
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


def test_normalize_iso_utc_handles_naive_and_offset_timestamps():
    assert forecast_accuracy._normalize_iso_utc("2026-07-01T10:00:00") == "2026-07-01T10:00:00+00:00"
    assert forecast_accuracy._normalize_iso_utc("2026-07-01T12:00:00+02:00") == "2026-07-01T10:00:00+00:00"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self.committed = False

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        result = self.results.pop(0) if self.results else []
        return FakeResult(result)

    async def commit(self):
        self.committed = True


def test_load_measured_slots_skips_nulls_and_normalizes_naive_times():
    solar_ts = datetime(2026, 7, 1, 10, 0)
    battery_ts = datetime(2026, 7, 1, 10, 0)
    session = FakeSession(
        [
            [
                (solar_ts, "solar", 500),
                (solar_ts, "household", None),
                (solar_ts.replace(tzinfo=UTC), "household", 300),
            ],
            [(battery_ts, 61.5), (battery_ts.replace(tzinfo=UTC), None)],
        ]
    )

    measured = asyncio.run(
        forecast_accuracy._load_measured_slots(
            session,
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 2, tzinfo=UTC),
        )
    )

    assert measured[solar_ts.replace(tzinfo=UTC).isoformat()] == {"pv": 500.0, "load": 300.0, "battery_soc": 61.5}
    assert len(session.executed) == 2


def test_load_vintages_normalizes_slot_keys_to_utc():
    generated_at = datetime(2026, 7, 1, 9, 0)
    session = FakeSession(
        [
            [
                (
                    generated_at,
                    {
                        "slots": [
                            {"start": "2026-07-01T12:00:00+02:00", "pv_forecast_w": 450},
                            {"start": "2026-07-01T10:15:00", "load_forecast_w": 300},
                        ]
                    },
                )
            ]
        ]
    )

    vintages = asyncio.run(
        forecast_accuracy._load_vintages(
            session,
            datetime(2026, 7, 1, tzinfo=UTC),
            datetime(2026, 7, 2, tzinfo=UTC),
        )
    )

    assert vintages[0]["generated_at"] == generated_at.replace(tzinfo=UTC)
    assert "2026-07-01T10:00:00+00:00" in vintages[0]["slots_by_start"]
    assert "2026-07-01T10:15:00+00:00" in vintages[0]["slots_by_start"]


class FakeSessionFactory:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def __call__(self):
        return self.sessions.pop(0)


class FakeContextSession(FakeSession):
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_run_daily_accuracy_job_persists_stats_and_prunes_old_rows():
    slot_start = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    read_session = FakeContextSession(
        [
            [(slot_start, "solar", 500.0), (slot_start, "household", 300.0)],
            [(slot_start, 60.0)],
            [
                (
                    slot_start - timedelta(hours=2),
                    {
                        "slots": [
                            {
                                "start": slot_start.isoformat(),
                                "pv_forecast_w": 450.0,
                                "load_forecast_w": 330.0,
                                "soc_target_pct": 58.0,
                            }
                        ]
                    },
                )
            ],
        ]
    )
    write_session = FakeContextSession([])
    factory = FakeSessionFactory([read_session, write_session])

    asyncio.run(forecast_accuracy.run_daily_accuracy_job(factory, date(2026, 7, 1), tz=timezone.utc))

    writes = [params for sql, params in write_session.executed if "insert into forecast_accuracy_daily" in sql]
    assert {params["curve"] for params in writes} == {"pv", "load", "battery_soc"}
    assert {params["horizon"] for params in writes} == {"1h"}
    assert any(params["mae"] == 50.0 and params["bias"] == -50.0 for params in writes if params["curve"] == "pv")
    assert write_session.executed[-1][1] == {"cutoff": date(2026, 1, 2)}
    assert write_session.committed


def test_run_daily_accuracy_job_returns_without_writes_when_no_measurements():
    read_session = FakeContextSession([[], []])
    write_session = FakeContextSession([])
    factory = FakeSessionFactory([read_session, write_session])

    asyncio.run(forecast_accuracy.run_daily_accuracy_job(factory, date(2026, 7, 1), tz=timezone.utc))

    assert write_session.executed == []
