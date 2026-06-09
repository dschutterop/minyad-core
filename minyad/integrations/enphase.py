import logging
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPDigestAuth

from minyad.common.config import AppConfig
from minyad.common.retry import with_backoff

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnphaseProduction:
    production_w: int
    lifetime_wh: int | None
    raw: dict[str, Any]


class EnphaseClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = f"http://{config.envoy_host}"
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(config.envoy_username, config.envoy_password)

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
