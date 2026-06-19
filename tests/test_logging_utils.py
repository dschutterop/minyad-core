import logging

from shared.logging_utils import DuplicateInfoFilter


def _record(message: str, *args: object, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("service", level, __file__, 1, message, args, None)


def test_duplicate_info_filter_suppresses_immediate_repeated_info_lines(monkeypatch):
    clock = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr("shared.logging_utils.time.monotonic", lambda: next(clock))
    duplicate_filter = DuplicateInfoFilter(summary_interval_seconds=60)

    assert duplicate_filter.filter(_record("poll value=%s", 10)) is True
    assert duplicate_filter.filter(_record("poll value=%s", 10)) is False
    assert duplicate_filter.filter(_record("poll value=%s", 10)) is False


def test_duplicate_info_filter_groups_repeats_after_interval(monkeypatch):
    clock = iter([0.0, 1.0, 61.0])
    monkeypatch.setattr("shared.logging_utils.time.monotonic", lambda: next(clock))
    duplicate_filter = DuplicateInfoFilter(summary_interval_seconds=60)

    assert duplicate_filter.filter(_record("poll value=%s", 10)) is True
    assert duplicate_filter.filter(_record("poll value=%s", 10)) is False
    grouped = _record("poll value=%s", 10)

    assert duplicate_filter.filter(grouped) is True
    assert grouped.getMessage() == "poll value=10 (repeated 2 times; grouped duplicate informational logs)"


def test_duplicate_info_filter_does_not_suppress_warnings():
    duplicate_filter = DuplicateInfoFilter(summary_interval_seconds=60)

    assert duplicate_filter.filter(_record("same", level=logging.WARNING)) is True
    assert duplicate_filter.filter(_record("same", level=logging.WARNING)) is True
