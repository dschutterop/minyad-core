import asyncio
import os

os.environ.setdefault("DB_URL", "postgresql+asyncpg://user:pass@localhost/test")

import httpx

from forecast import main as forecast_main


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "hourly": {
                "time": ["2026-06-18T12:00"],
                "direct_radiation": [500],
                "diffuse_radiation": [100],
                "shortwave_radiation": [600],
            }
        }


class FlakyAsyncClient:
    attempts = 0

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        FlakyAsyncClient.attempts += 1
        if FlakyAsyncClient.attempts == 1:
            raise httpx.ConnectError("temporary DNS failure")
        return FakeResponse()


def test_fetch_solar_forecast_retries_transient_request_errors(monkeypatch):
    FlakyAsyncClient.attempts = 0
    sleeps = []
    real_sleep = forecast_main.asyncio.sleep

    async def fake_sleep(delay):
        await real_sleep(0)
        sleeps.append(delay)

    monkeypatch.setattr(forecast_main.httpx, "AsyncClient", FlakyAsyncClient)
    monkeypatch.setattr(forecast_main.asyncio, "sleep", fake_sleep)

    points = asyncio.run(forecast_main.fetch_solar_forecast())

    assert FlakyAsyncClient.attempts == 2
    assert sleeps == [forecast_main.FETCH_RETRY_BASE_DELAY_SECONDS]
    assert points[0]["estimated_w"] == 2400
