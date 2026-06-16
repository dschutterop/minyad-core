import logging
from multiprocessing import Process

from minyad.common.config import get_config
from minyad.common.logging import configure_logging
from minyad.ingest import dsmr, enphase_poller, goodwe_poller

LOG = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    cfg = get_config()
    workers = []
    if cfg.dsmr_ingestion_enabled:
        workers.append(Process(target=dsmr.main, name="dsmr-consumer"))
    else:
        LOG.info("DSMR ingestion is disabled by DSMR_INGESTION_ENABLED=false")
    if cfg.enphase_ingestion_enabled:
        workers.append(Process(target=enphase_poller.main, name="enphase-poller"))
    else:
        LOG.info("Enphase ingestion is disabled by ENPHASE_INGESTION_ENABLED=false")
    if cfg.goodwe_ingestion_enabled:
        workers.append(Process(target=goodwe_poller.main, name="goodwe-poller"))
    else:
        LOG.info("GoodWe ingestion is disabled by GOODWE_INGESTION_ENABLED=false")
    if not workers:
        LOG.warning("No ingestion workers enabled; exiting")
        return
    for worker in workers:
        worker.start()
        LOG.info("Started %s pid=%s", worker.name, worker.pid)
    for worker in workers:
        worker.join()
        if worker.exitcode:
            raise SystemExit(f"{worker.name} exited with {worker.exitcode}")


if __name__ == "__main__":
    main()
