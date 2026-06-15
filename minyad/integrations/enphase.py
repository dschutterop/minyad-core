import logging
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPDigestAuth

from minyad.common.config import AppConfig
from minyad.common.retry import with_backoff

LOG = logging.getLogger(__name__)

POWER_STATUS_MODULE_ID = "603980032"
POWER_STATUS_PATH = f"/ivp/mod/{POWER_STATUS_MODULE_ID}/mode/power_status"
PHASE_A = "ph-a"


@dataclass(frozen=True)
class EnphaseProduction:
    production_w: int
    lifetime_wh: int | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class EnphasePowerStatus:
    power_forced_off: bool
    raw: dict[str, Any]


class EnphaseClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = f"http://{config.envoy_host}"
        self.control_base_url = f"https://{config.enphase_gateway_ip}"
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(config.envoy_username, config.envoy_password)
        self.control_session = requests.Session()
        self.control_session.verify = config.enphase_verify_tls
        self._last_power_switch_monotonic: float | None = None

    def get_production(self) -> EnphaseProduction:
        def call() -> EnphaseProduction:
            response = self.session.get(
                f"{self.base_url}/api/v1/production", timeout=self.config.http_timeout_s
            )
            response.raise_for_status()
            payload = response.json()
            watts_now = int(payload.get("wattsNow") or payload.get("wNow") or 0)
            lifetime_wh = payload.get("wattHoursLifetime") or payload.get("whLifetime")
            LOG.debug("Envoy production=%sW lifetime=%sWh", watts_now, lifetime_wh)
            return EnphaseProduction(
                production_w=watts_now,
                lifetime_wh=int(lifetime_wh) if lifetime_wh is not None else None,
                raw=payload,
            )

        return with_backoff(call, label="enphase production")

    def get_power_status(self) -> EnphasePowerStatus:
        def call() -> EnphasePowerStatus:
            payload = self._control_request("GET", POWER_STATUS_PATH)
            return EnphasePowerStatus(
                power_forced_off=bool(payload.get("powerForcedOff")),
                raw=payload,
            )

        return with_backoff(call, label="enphase power status")

    def set_production_enabled(self, enabled: bool) -> bool:
        """Enable or hard-disable production, respecting the configured switch hysteresis.

        Returns True when a command was sent and False when no command was necessary or the
        minimum switch interval has not elapsed yet.
        """
        status = self.get_power_status()
        if status.power_forced_off != enabled:
            return False
        now = time.monotonic()
        if (
            self._last_power_switch_monotonic is not None
            and now - self._last_power_switch_monotonic < self.config.enphase_switch_hysteresis_s
        ):
            LOG.info(
                "Skipping Enphase power switch; hysteresis %.0fs has not elapsed",
                self.config.enphase_switch_hysteresis_s,
            )
            return False
        flag = 1 if enabled else 0
        payload = {"length": 1, "arr": [{"phase": PHASE_A, "expectedEnergyFlag": flag}]}
        self._control_request("PUT", POWER_STATUS_PATH, json=payload)
        self._last_power_switch_monotonic = now
        LOG.info("Set Enphase production enabled=%s", enabled)
        return True

    def set_production_limit(self, percent: int) -> bool:
        """Set the production limit via the active curtailment strategy.

        The public interface is intentionally percentage-based so the future granular DRM
        route can be enabled with CURTAILMENT_GRANULAR_ENABLED without changing callers.
        """
        bounded_percent = max(0, min(100, int(percent)))
        if self.config.curtailment_granular_enabled:
            return self._set_granular_production_limit(bounded_percent)
        return self.set_production_enabled(bounded_percent > 0)

    def _set_granular_production_limit(self, percent: int) -> bool:
        LOG.warning(
            "Granular Enphase curtailment requested at %s%%, but the DRM route is not implemented yet",
            percent,
        )
        return False

    def _control_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = self._bearer_token()
        headers = {"Authorization": f"Bearer {token}"}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
        response = self.control_session.request(
            method,
            f"{self.control_base_url}{path}",
            headers=headers,
            timeout=self.config.http_timeout_s,
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _bearer_token(self) -> str:
        token = self.config.enphase_token.strip()
        if not token:
            raise ValueError("ENPHASE_TOKEN must be set in the environment for Enphase control")
        return token
