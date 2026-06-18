import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("requests")

MODULE_PATH = Path(__file__).resolve().parents[1] / "host-services" / "enphase_bridge.py"
spec = importlib.util.spec_from_file_location("enphase_bridge", MODULE_PATH)
enphase_bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(enphase_bridge)


def test_summarize_inverter_production_uses_array_total_as_production_w():
    inverters = [
        {"serialNumber": "a", "lastReportWatts": 125, "lastReportDate": 100, "array": ""},
        {"serialNumber": "b", "lastReportWatts": 275, "lastReportDate": 105},
        {"serialNumber": "", "lastReportWatts": 999, "lastReportDate": 110},
    ]

    array_totals, total_production_w, latest_report_at = (
        enphase_bridge.summarize_inverter_production(inverters)
    )

    assert array_totals == {"unknown": 400}
    assert total_production_w == 400
    assert latest_report_at == 105
