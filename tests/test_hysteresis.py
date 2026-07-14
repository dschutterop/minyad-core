import os
import sys

CONTROL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "control"))
if CONTROL_DIR not in sys.path:
    sys.path.insert(0, CONTROL_DIR)

from hysteresis import HysteresisController  # noqa: E402,I001 - must follow sys.path setup above
from state import ControlState  # noqa: E402 - must follow sys.path setup above


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


def test_charge_timer_does_not_bleed_into_discharge_trigger():
    """Charge timer built up in IDLE must not contribute to discharge start_duration."""
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    # Accumulate nearly-full charge timer (9 of 10 s)
    controller.tick(600)
    clock.advance(9)
    assert controller.tick(600) is None   # not yet charged

    # Surplus swings hard negative — discharge condition now active
    # With shared timer this would fire immediately; with split timers it must not
    assert controller.tick(-400) is None  # discharge timer starts fresh from here
    clock.advance(1)
    assert controller.tick(-400) is None  # only 1s into discharge timer
    clock.advance(9)
    assert controller.tick(-400) is ControlState.DISCHARGING  # full 10s now elapsed
    assert events == ["discharge_start"]


def test_discharge_timer_does_not_bleed_into_charge_trigger():
    """Discharge timer built up in IDLE must not contribute to charge start_duration."""
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    controller.tick(-400)
    clock.advance(9)
    assert controller.tick(-400) is None

    assert controller.tick(600) is None   # charge timer starts fresh
    clock.advance(1)
    assert controller.tick(600) is None
    clock.advance(9)
    assert controller.tick(600) is ControlState.CHARGING
    assert events == ["charge_start"]


def test_opposite_direction_bypasses_cooldown_after_sustained_trigger():
    """Strong solar surplus during discharge cooldown should skip to CHARGING without waiting."""
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    # Enter DISCHARGING
    controller.tick(-400)
    clock.advance(10)
    assert controller.tick(-400) is ControlState.DISCHARGING

    # Stop discharging (surplus recovered), enter COOLDOWN
    controller.tick(-90)
    clock.advance(5)
    assert controller.tick(-90) is ControlState.COOLDOWN

    # Solar kicks in hard — sustain charge trigger for start_duration (10s) during cooldown
    # Cooldown is 20s; without bypass we'd be stuck here
    controller.tick(600)
    clock.advance(10)
    result = controller.tick(600)
    assert result is ControlState.CHARGING, f"expected CHARGING during cooldown bypass, got {result}"
    assert events[-1] == "charge_start"


def test_cooldown_still_applies_when_same_direction_trigger_persists():
    """No bypass when the same-direction condition reappears during cooldown."""
    clock = FakeClock()
    events = []
    controller = make_controller(clock, events)

    controller.tick(-400)
    clock.advance(10)
    assert controller.tick(-400) is ControlState.DISCHARGING

    controller.tick(-90)
    clock.advance(5)
    assert controller.tick(-90) is ControlState.COOLDOWN

    # Import reappears (same direction as the just-finished discharge)
    clock.advance(10)
    assert controller.tick(-400) is None  # still in cooldown, no bypass
    assert controller.state is ControlState.COOLDOWN


def test_cooldown_expiry_immediately_reevaluates_without_idle_dwell(caplog):
    """Persistent export after charge cooldown should trim up immediately."""
    clock = FakeClock()
    events = []
    controller = HysteresisController(
        start_w=500,
        stop_w=150,
        discharge_start_w=-300,
        discharge_stop_w=-100,
        start_duration=120,
        stop_duration=5,
        cooldown=180,
        on_start=lambda: events.append("trim_up"),
        on_stop=lambda: events.append("charge_stop"),
        on_discharge_start=lambda: events.append("trim_down"),
        on_discharge_stop=lambda: events.append("discharge_stop"),
        clock=clock,
    )

    # Initial state: charging at roughly 10A.  A drop below the stop threshold
    # sends the controller into its stabilization cooldown.
    controller.tick(1800)
    clock.advance(120)
    assert controller.tick(1800) is ControlState.CHARGING
    assert events == ["trim_up"]

    controller.tick(100)
    clock.advance(5)
    assert controller.tick(100) is ControlState.COOLDOWN
    assert events == ["trim_up", "charge_stop"]

    # Once cooldown expires, the latest export sample is evaluated immediately;
    # the 120s IDLE start-duration dwell must not run a second time.
    caplog.set_level("INFO")
    clock.advance(180)
    result = controller.tick(1800, grid_power_w=-1800, charge_current_target=10)

    assert result is ControlState.CHARGING
    assert controller.state is ControlState.CHARGING
    assert events == ["trim_up", "charge_stop", "trim_up"]
    assert "Cooldown expired, performing immediate control evaluation" in caplog.text
    assert "current_fsm_state=COOLDOWN" in caplog.text
    assert "grid_power=-1800W" in caplog.text
    assert "calculated_surplus=1800W" in caplog.text
    assert "current_charge_current_target=10" in caplog.text


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
