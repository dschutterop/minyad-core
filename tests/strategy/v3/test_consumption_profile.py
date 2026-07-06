from datetime import datetime, timedelta, timezone

from minyad.strategy.v3.consumption_profile import split_baseline_rows

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
