'''
Tests for the demo boot trigger (project reset button held at power-up).
The autostart decision is in test_demo_autostart.py.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_boot.py
'''
from ttboard import demo


class ScriptedPin:
    '''Returns successive values from a script (last value repeats).'''
    def __init__(self, values):
        self.values = list(values)
        self.reads = 0

    def __call__(self, v=None):
        if v is not None:
            raise AssertionError('reset pin must only be read')
        i = min(self.reads, len(self.values) - 1)
        self.reads += 1
        return self.values[i]


class LedPin:
    def __init__(self):
        self.writes = []

    def __call__(self, v=None):
        if v is not None:
            self.writes.append(v)
        return self.writes[-1] if self.writes else 0


class Clock:
    def __init__(self):
        self.ms = 0

    def sleep_ms(self, ms):
        self.ms += ms


def held(values, timeout_ms=10000):
    led = LedPin()
    clock = Clock()
    result = demo.boot_button_held(reset_pin=ScriptedPin(values), led_pin=led,
                                   sleep_ms=clock.sleep_ms,
                                   release_timeout_ms=timeout_ms)
    return result, led, clock


def test_not_pressed():
    result, led, clock = held([1])
    assert result is False
    assert led.writes == []
    assert clock.ms < 100


def test_glitch_is_not_a_press():
    # a single low sample that doesn't persist through the debounce
    result, _led, _clock = held([0, 1])
    assert result is False


def test_held_then_released():
    result, led, clock = held([0] * 30 + [1])
    assert result is True
    # LED blinked while waiting, and is left off
    assert len(led.writes) > 2
    assert led.writes[-1] == 0


def test_stuck_low_times_out():
    result, led, clock = held([0], timeout_ms=2000)
    assert result is False
    assert clock.ms >= 2000
    assert led.writes[-1] == 0

