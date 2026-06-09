import logging
from multiprocessing import Process

from minyad.ingest import dsmr, enphase_poller, goodwe_poller

LOG = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    workers = [
        Process(target=dsmr.main, name="dsmr-consumer"),
        Process(target=enphase_poller.main, name="enphase-poller"),
        Process(target=goodwe_poller.main, name="goodwe-poller"),
    ]
    for worker in workers:
        worker.start()
        LOG.info("Started %s pid=%s", worker.name, worker.pid)
    for worker in workers:
        worker.join()
        if worker.exitcode:
            raise SystemExit(f"{worker.name} exited with {worker.exitcode}")


if __name__ == "__main__":
    main()
