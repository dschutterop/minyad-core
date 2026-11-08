import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import asyncio
from unittest.mock import AsyncMock

import pytest

import api.main as api_main


class _FakeSession:
    async def __aenter__(self) -> object:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def _run_recorder_for_ticks(monkeypatch: pytest.MonkeyPatch, ticks: int) -> None:
    done = asyncio.Event()
    count = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal count
        count += 1
        if count >= ticks:
            done.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(api_main, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(api_main.asyncio, "sleep", fake_sleep)
    task = asyncio.create_task(api_main._record_power_curves())
    await done.wait()
    task.cancel()


def test_recorder_samples_all_curve_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    for name, target in (("grid", "grid_status"), ("battery", "battery_status"), ("household", "household_status_payload")):
        monkeypatch.setattr(api_main, target, AsyncMock(side_effect=lambda _s, name=name: calls.append(name)))

    asyncio.run(_run_recorder_for_ticks(monkeypatch, 2))

    assert calls == ["grid", "battery", "household"] * 2


def test_recorder_survives_a_failing_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = AsyncMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(api_main, "grid_status", grid)

    asyncio.run(_run_recorder_for_ticks(monkeypatch, 3))

    assert grid.await_count == 3
