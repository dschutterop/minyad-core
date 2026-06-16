import logging

import uvicorn

from minyad.common.config import get_config
from minyad.common.logging import configure_logging

if __name__ == "__main__":
    config = get_config()
    configure_logging(config)
    uvicorn.run(
        "minyad.api.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=logging.getLevelName(logging.DEBUG if config.debug_messages else logging.INFO).lower(),
    )
