import logging
import time

from minyad.common.config import get_config
from minyad.common.db import connect, get_settings, insert_reading, setting_int
from minyad.common.logging import configure_logging
from minyad.common.status import update_status
from minyad.common.time import utc_now
from minyad.integrations.goodwe import build_goodwe_client

LOG = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    cfg = get_config()
    if not cfg.goodwe_ingestion_enabled:
        LOG.info("GoodWe ingestion is disabled; exiting")
        return
    client = build_goodwe_client(cfg)
    while True:
        interval = 5
        try:
            state = client.read_state()
            with connect() as conn:
                insert_reading(
                    conn,
                    "battery_readings",
                    {
                        "timestamp": utc_now(),
                        "soc_pct": state.soc_pct,
                        "charge_w": state.charge_w,
                        "discharge_w": state.discharge_w,
                        "mode": state.mode,
                        "grid_feed_w": state.grid_feed_w,
                        "raw": state.raw or {},
                    },
                )
                update_status(conn, "goodwe", "ok", {"mode": state.mode, "soc_pct": state.soc_pct})
                interval = setting_int(get_settings(conn), "goodwe_poll_interval_s", 5)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("GoodWe poll failed: %s", exc)
            with connect() as conn:
                update_status(conn, "goodwe", "error", {"error": str(exc)})
                interval = setting_int(get_settings(conn), "goodwe_poll_interval_s", 5)
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
