"""Logging helpers shared by Minyad services."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _SuppressedLog:
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


class DuplicateInfoFilter(logging.Filter):
    """Collapse repeated INFO records so fast polling loops do not flood logs.

    The first occurrence of an INFO line is emitted immediately. Identical
    follow-up INFO messages are suppressed until either a different INFO line is
    seen or ``summary_interval_seconds`` elapses, at which point a single grouped
    line is emitted with the number of suppressed repeats.
    """

    def __init__(self, *, summary_interval_seconds: float = 60.0) -> None:
        super().__init__()
        self.summary_interval_seconds = summary_interval_seconds
        self._last_key: tuple[str, str, tuple[Any, ...]] | None = None
        self._suppressed = _SuppressedLog()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True

        key = (record.name, str(record.msg), tuple(record.args) if isinstance(record.args, tuple) else (record.args,))
        now = time.monotonic()
        if key != self._last_key:
            self._last_key = key
            self._suppressed = _SuppressedLog(first_seen=now, last_seen=now)
            return True

        self._suppressed.count += 1
        self._suppressed.last_seen = now
        if now - self._suppressed.first_seen < self.summary_interval_seconds:
            return False

        repeated = self._suppressed.count
        self._suppressed = _SuppressedLog(first_seen=now, last_seen=now)
        record.msg = f"{record.getMessage()} (repeated {repeated} times; grouped duplicate informational logs)"
        record.args = ()
        return True


def configure_container_logging(level: int | str = logging.INFO, *, format: str | None = None) -> None:
    """Configure service logging with duplicate INFO-line grouping."""

    logging.basicConfig(level=level, format=format)
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(existing, DuplicateInfoFilter) for handler in root.handlers for existing in handler.filters):
        return
    for handler in root.handlers:
        handler.addFilter(DuplicateInfoFilter())
