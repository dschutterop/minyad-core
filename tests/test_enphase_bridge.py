import importlib.util
import sys
import types
from pathlib import Path


def install_import_stubs() -> None:
    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.Session = object
        requests.Timeout = TimeoutError
        requests.ConnectionError = ConnectionError
        requests.HTTPError = RuntimeError
        sys.modules["requests"] = requests
    if "urllib3" not in sys.modules:
        urllib3 = types.ModuleType("urllib3")
        exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
        urllib3.exceptions = exceptions
        urllib3.disable_warnings = lambda *_args, **_kwargs: None
        sys.modules["urllib3"] = urllib3


install_import_stubs()

MODULE_PATH = Path(__file__).resolve().parents[1] / "host-services" / "enphase_bridge.py"
spec = importlib.util.spec_from_file_location("enphase_bridge", MODULE_PATH)
enphase_bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["enphase_bridge"] = enphase_bridge
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


def test_production_w_from_payload_uses_fallback_only_for_missing_values():
    assert enphase_bridge.production_w_from_payload({}, fallback=400) == 400
    assert enphase_bridge.production_w_from_payload({"productionW": None}, fallback=400) == 400
    assert enphase_bridge.production_w_from_payload({"productionW": ""}, fallback=400) == 400
    assert enphase_bridge.production_w_from_payload({"productionW": 0}, fallback=400) == 0
    assert enphase_bridge.production_w_from_payload({"productionW": "0"}, fallback=400) == 0
    assert enphase_bridge.production_w_from_payload({"productionW": 275}, fallback=400) == 275
