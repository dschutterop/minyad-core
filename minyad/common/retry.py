import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
LOG = logging.getLogger(__name__)


def with_backoff(
    operation: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
    label: str = "operation",
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - retry boundary intentionally catches all client errors
            last_error = exc
            if attempt == attempts:
                break
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            delay *= 0.75 + random.random() * 0.5
            LOG.warning("%s failed on attempt %s/%s: %s; retrying in %.2fs", label, attempt, attempts, exc, delay)
            time.sleep(delay)
    assert last_error is not None
    raise last_error
