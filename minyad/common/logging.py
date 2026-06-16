import logging

from minyad.common.config import AppConfig, get_config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(config: AppConfig | None = None) -> None:
    cfg = config or get_config()
    logging.basicConfig(
        level=logging.DEBUG if cfg.debug_messages else logging.INFO, format=LOG_FORMAT
    )
