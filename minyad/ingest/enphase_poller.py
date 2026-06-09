import logging
import time

from minyad.common.config import get_config
from minyad.common.db import connect, get_settings, insert_reading, setting_int
from minyad.common.status import update_status
from minyad.common.time import utc_now
from minyad.integrations.enphase import EnphaseClient

LOG = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = get_config()
    client = EnphaseClient(cfg)
    while True:
        interval = 10
        try:
            production = client.get_production()
            with connect() as conn:
                insert_reading(
                    conn,
                    "solar_readings",
                    {
                        "timestamp": utc_now(),
                        "production_w": production.production_w,
                        "lifetime_wh": production.lifetime_wh,
                        "raw": production.raw,
                    },
                )
                update_status(conn, "enphase", "ok", {"production_w": production.production_w})
                interval = setting_int(get_settings(conn), "enphase_poll_interval_s", 10)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Enphase poll failed: %s", exc)
            with connect() as conn:
                update_status(conn, "enphase", "error", {"error": str(exc)})
                interval = setting_int(get_settings(conn), "enphase_poll_interval_s", 10)
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
