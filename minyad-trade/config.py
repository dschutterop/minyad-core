"""Configuration constants for Minyad energy-market data collectors."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")


@dataclass(frozen=True)
class MqttTopics:
    settings_prefix: str = "minyad/settings/trade"
    day_ahead_price_prefix: str = "minyad/trade/prices/da"

    @property
    def day_ahead_full_suffix(self) -> str:
        return "full"


@dataclass(frozen=True)
class DayAheadDefaults:
    bidding_zone: str = "10YNL----------L"
    poll_time_local: str = "13:30"
    retry_attempts: int = 3
    retry_interval_minutes: int = 15


@dataclass(frozen=True)
class EntsoeConfig:
    price_unit_divisor: float = 1000.0  # ENTSO-E returns EUR/MWh; Minyad publishes EUR/kWh.
    timezone_name: str = "Europe/Amsterdam"


MQTT_TOPICS = MqttTopics()
DAY_AHEAD_DEFAULTS = DayAheadDefaults()
ENTSOE = EntsoeConfig()
