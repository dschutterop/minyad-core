import os

from minyad.ingest import all, dsmr, enphase_poller, goodwe_poller

SERVICES = {
    "all": all.main,
    "dsmr": dsmr.main,
    "enphase": enphase_poller.main,
    "goodwe": goodwe_poller.main,
}

if __name__ == "__main__":
    service = os.getenv("INGEST_SERVICE", "all")
    SERVICES[service]()
