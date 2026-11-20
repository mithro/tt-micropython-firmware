'''
Tests for the demo boot trigger (project reset button held at power-up)
and the autostart decision.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_boot.py
'''
import json

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


class FakeShuttle:
    run = 'tt09'

    def __init__(self, names):
        self.names = names
        self.design_enabled_callback = None
        self.enabled = None

    def has(self, n):
        return n in self.names

    def get(self, n):
        shuttle = self

        class D:
            name = n

            def enable(self, force=False):
                # like the real muxes, record the design object itself
                shuttle.enabled = self
                return True
        return D()


class FakeTT:
    def __init__(self):
        self.shuttle = FakeShuttle(['a', 'b'])


def write(tmp_path, conf):
    p = tmp_path / 'demo.json'
    p.write_text(json.dumps(conf))
    return str(p)


PLAYLIST = {'shuttles': {'tt09': {'projects': ['a', 'b']}}}


def test_autostart_not_enabled_not_held(tmp_path):
    run = demo.autostart(FakeTT(), False, write(tmp_path, PLAYLIST))
    assert run is not None
    assert not run.running


def test_autostart_held_starts(tmp_path):
    tt = FakeTT()
    run = demo.autostart(tt, True, write(tmp_path, PLAYLIST))
    assert run.running
    assert tt.shuttle.enabled.name == 'a'
    run.stop()


def test_autostart_enabled_starts(tmp_path):
    run = demo.autostart(FakeTT(), False, write(tmp_path, dict(PLAYLIST, enabled=True)))
    assert run.running
    run.stop()


def test_autostart_enabled_and_held_skips(tmp_path):
    # holding the button on a kiosk board skips the demo for this boot
    run = demo.autostart(FakeTT(), True, write(tmp_path, dict(PLAYLIST, enabled=True)))
    assert not run.running


def test_autostart_no_config(tmp_path):
    run = demo.autostart(FakeTT(), True, str(tmp_path / 'missing.json'))
    assert run is not None
    assert not run.running
    assert run.playlist == []
