"""DSMR/P1 telegram parsing scaffold.

The full P1Reader specification was not included in the prompt. This module
keeps ingestion limited to parsing and MQTT publication; no database writes or
business decisions belong here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DsmrMeasurement:
    measurement: str
    value: float


OBIS_TOPIC_MAP = {
    "1-0:21.7.0": "phase_w_l1",
    "1-0:41.7.0": "phase_w_l2",
    "1-0:61.7.0": "phase_w_l3",
}


def parse_telegram(_telegram: str) -> list[DsmrMeasurement]:
    """Parse a DSMR/P1 telegram into Minyad measurements.

    TODO: implement against the complete P1Reader spec when supplied.
    """
    return []
