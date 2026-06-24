import importlib.util
import sys
from datetime import datetime
from pathlib import Path


def _load_collector():
    module_dir = Path(__file__).resolve().parents[1] / "minyad-trade"
    module_path = module_dir / "epex_collector.py"
    sys.path.insert(0, str(module_dir))
    spec = importlib.util.spec_from_file_location("epex_collector", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_startup_target_day_is_tomorrow_in_amsterdam_timezone():
    collector = _load_collector()

    target = collector._target_day(datetime(2026, 6, 24, 12, 0, tzinfo=collector.AMSTERDAM_TZ))

    assert target.date().isoformat() == "2026-06-25"


def test_next_poll_time_rolls_to_tomorrow_after_poll_time():
    collector = _load_collector()

    now = datetime(2026, 6, 24, 14, 0, tzinfo=collector.AMSTERDAM_TZ)
    poll_at = collector.next_poll_time(now, "13:30")

    assert poll_at.isoformat() == "2026-06-25T13:30:00+02:00"
