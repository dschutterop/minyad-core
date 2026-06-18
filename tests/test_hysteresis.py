import os
import sys

CONTROL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "control"))
if CONTROL_DIR not in sys.path:
    sys.path.insert(0, CONTROL_DIR)

from hysteresis import HysteresisController
from state import ControlState


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_controller(clock, events):
    return HysteresisController(
        start_w=500,
        stop_w=150,
        discharge_start_w=-300,
        discharge_stop_w=-100,
        start_duration=10,
        stop_duration=5,
        cooldown=20,
        on_start=lambda: events.append("charge_start"),
        on_stop=lambda: events.append("charge_stop"),
        on_discharge_start=lambda: events.append("discharge_start"),
        on_discharge_stop=lambda: events.append("discharge_stop"),
        clock=clock,
    )


def test_discharge_starts_after_sustained_grid_import_and_stops_after_recovery():
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    assert controller.tick(-300) is None
    clock.advance(9)
    assert controller.tick(-350) is None
    clock.advance(1)
    assert controller.tick(-350) is ControlState.DISCHARGING
    assert events == ["discharge_start"]

    assert controller.tick(-90) is None
    clock.advance(5)
    assert controller.tick(-90) is ControlState.COOLDOWN
    assert events == ["discharge_start", "discharge_stop"]

    clock.advance(20)
    assert controller.tick(-90) is ControlState.IDLE


def test_charge_and_discharge_paths_are_mutually_exclusive():
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    controller.tick(-400)
    clock.advance(10)
    assert controller.tick(-400) is ControlState.DISCHARGING

    clock.advance(100)
    assert controller.tick(800) is None
    assert controller.state is ControlState.DISCHARGING
    assert events == ["discharge_start"]
