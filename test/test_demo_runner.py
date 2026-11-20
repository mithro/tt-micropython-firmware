'''
Tests for DemoRunner and KeyPlayer using a fake demoboard, shuttle and
timer.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_runner.py
'''
from ttboard.demo import DemoRunner, KeyPlayer, parse_keys


class FakePort:
    def __init__(self):
        self.value = 0


class WatchedPort:
    '''Records every byte written.'''
    def __init__(self, value=0):
        self._value = value
        self.writes = []

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
        self.writes.append(v)


class FakeDesign:
    def __init__(self, shuttle, name, enables=True):
        self.shuttle = shuttle
        self.name = name
        self.enables = enables

    def enable(self, force=False):
        self.shuttle.enable_calls.append(self.name)
        if not self.enables:
            return False
        self.shuttle.enabled = self
        if self.shuttle.design_enabled_callback is not None:
            self.shuttle.design_enabled_callback(self)
        return True


class FakeShuttle:
    '''Designs looked up the way the project mux does: by int address or "A-S".'''
    def __init__(self, keys, failing=()):
        self.designs = {k: FakeDesign(self, f'p{k}', k not in failing) for k in keys}
        self.enabled = None
        self.enable_calls = []
        self.callback_calls = []
        self.design_enabled_callback = self.callback_calls.append

    def get(self, key):
        if key in self.designs:
            return self.designs[key]
        raise AttributeError(f'Unknown project ({key})')


class FakeTT:
    def __init__(self, shuttle):
        self.shuttle = shuttle
        self.ui_in = FakePort()
        self.uio_in = FakePort()
        self.uio_oe_pico = FakePort()
        self.clock_calls = []
        self.resets = []

    def clock_project_PWM(self, hz):
        self.clock_calls.append(hz)

    def reset_project(self, in_reset):
        self.resets.append(in_reset)


class FakeTimer:
    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self):
        self.period = None
        self.mode = None
        self.callback = None
        self.active = False

    def init(self, period, mode, callback):
        self.period = period
        self.mode = mode
        self.callback = callback
        self.active = True

    def deinit(self):
        self.active = False

    def fire(self):
        assert self.active
        self.active = False  # one-shot
        self.callback(self)


def E(address, subtile=0, **kw):
    return dict(address=address, subtile=subtile, **kw)


def make(entries, keys=None, failing=(), ms=15000):
    if keys is None:
        keys = [e['address'] if not e['subtile'] else f"{e['address']}-{e['subtile']}"
                for e in entries]
    shuttle = FakeShuttle(keys, failing)
    tt = FakeTT(shuttle)
    return tt, shuttle, DemoRunner(tt, entries, ms, timer_class=FakeTimer,
                                   sleep_ms=lambda ms: None)


def test_filters_unavailable_projects():
    tt, shuttle, run = make([E(1), E(2), E(3)], keys=[1, 3])
    assert [e['address'] for e in run.playlist] == [1, 3]


def test_subtile_looked_up_as_string():
    tt, shuttle, run = make([E(5, 2), E(5)], keys=['5-2', 5])
    assert len(run.playlist) == 2
    run.start()
    assert shuttle.enabled.name == 'p5-2'
    run.stop()


def test_start_enables_first_and_arms_timer():
    tt, shuttle, run = make([E(1), E(2, duration_ms=2500)])
    assert run.start()
    assert run.running
    assert shuttle.enabled.name == 'p1'
    assert run._timer.mode == FakeTimer.ONE_SHOT
    assert run._timer.period == 15000


def test_per_entry_duration_and_wrap():
    tt, shuttle, run = make([E(1), E(2, duration_ms=2500)])
    run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'p2'
    assert run._timer.period == 2500
    run._timer.fire()
    assert shuttle.enabled.name == 'p1'
    assert run._timer.period == 15000


def test_single_entry_shown_without_switching():
    tt, shuttle, run = make([E(1)])
    assert run.start()
    assert shuttle.enabled.name == 'p1'
    assert not run._timer.active


def test_start_with_empty_playlist():
    tt, shuttle, run = make([], keys=[1])
    assert not run.start()
    assert not run.running


def test_overrides_applied_after_enable():
    tt, shuttle, run = make([E(1, clock_hz=25175000, ui_in=0x12, uio_oe_pico=0x0f, uio_in=0x05), E(2)])
    run.start()
    assert tt.clock_calls == [25175000]
    assert tt.ui_in.value == 0x12
    assert tt.uio_oe_pico.value == 0x0f
    assert tt.uio_in.value == 0x05


def test_no_overrides_leaves_ports_alone():
    tt, shuttle, run = make([E(1), E(2)])
    tt.ui_in.value = 7
    run.start()
    assert tt.clock_calls == []
    assert tt.ui_in.value == 7


def test_original_callback_still_called():
    tt, shuttle, run = make([E(1), E(2)])
    run.start()
    assert [d.name for d in shuttle.callback_calls] == ['p1']


def test_manual_enable_stops_demo():
    tt, shuttle, run = make([E(1), E(2)], keys=[1, 2, 3])
    run.start()
    shuttle.get(3).enable()
    assert not run.running
    assert not run._timer.active
    assert shuttle.design_enabled_callback == shuttle.callback_calls.append
    assert [d.name for d in shuttle.callback_calls] == ['p1', 'p3']


def test_stop_restores_callback():
    tt, shuttle, run = make([E(1), E(2)])
    orig = shuttle.design_enabled_callback
    run.start()
    assert shuttle.design_enabled_callback != orig
    run.stop()
    assert shuttle.design_enabled_callback == orig
    assert not run.running


def test_start_twice_is_noop():
    tt, shuttle, run = make([E(1), E(2)])
    run.start()
    run.start()
    assert shuttle.enable_calls == ['p1']


def test_restart_after_stop():
    tt, shuttle, run = make([E(1), E(2)])
    run.start()
    run.stop()
    assert run.start()
    assert run.running


def test_skips_failing_projects():
    tt, shuttle, run = make([E(1), E(2), E(3)], failing=[2])
    run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'p3'


def test_enable_returning_none_but_enabled_counts_as_success():
    # FPGA BitStream.enable() returns None even when the bitstream loaded
    tt, shuttle, run = make([E(1), E(2)])
    for d in shuttle.designs.values():
        orig = d.enable
        d.enable = (lambda o: (lambda force=False: (o(force), None)[1]))(orig)
    assert run.start()
    assert shuttle.enabled.name == 'p1'
    run._timer.fire()
    assert shuttle.enabled.name == 'p2'


def test_enable_returning_none_and_nothing_enabled_is_failure():
    # e.g. ProjectMux.enable() on a GROUP: disables, returns None
    tt, shuttle, run = make([E(1), E(2)])

    def group_enable(force=False):
        shuttle.enabled = None
        return None
    shuttle.get(1).enable = group_enable
    assert run.start()
    assert shuttle.enabled.name == 'p2'


def test_all_failing_stops_without_looping():
    tt, shuttle, run = make([E(1), E(2)], failing=[1, 2])
    assert not run.start()
    assert shuttle.enable_calls == ['p1', 'p2']
    assert not run.running


def test_exception_in_tick_rearms():
    tt, shuttle, run = make([E(1), E(2), E(3)])

    def boom(force=False):
        raise RuntimeError('mux problem')
    shuttle.get(2).enable = boom
    run.start()
    run._timer.fire()   # must not raise out of the timer callback
    assert run.running
    assert shuttle.enabled.name == 'p3'
    assert run._timer.active


def test_next_while_stopped_just_switches():
    tt, shuttle, run = make([E(1), E(2)])
    run.next()
    assert shuttle.enabled.name == 'p1'
    run.next()
    assert shuttle.enabled.name == 'p2'
    assert not run.running


def test_next_while_running_resets_timer():
    tt, shuttle, run = make([E(1), E(2, duration_ms=3000)])
    run.start()
    run.next()
    assert shuttle.enabled.name == 'p2'
    assert run._timer.period == 3000
    assert run.running


# --- keys -----------------------------------------------------------------

def player(steps, via='ui', base=7, port=None):
    tt = FakeTT(FakeShuttle([]))
    tt.ui_in = port if port is not None else WatchedPort(base)
    keys = parse_keys({'via': via, 'steps': steps})
    assert keys is not None
    p = KeyPlayer(tt, base, keys, timer_class=FakeTimer, sleep_ms=lambda ms: None)
    return tt, p


CONNECT4 = [{'set': 5}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 120},
            {'set': 6}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 250}]


def test_keys_play_in_order_with_waits():
    tt, p = player(CONNECT4)
    p.start()
    assert tt.ui_in.writes == [5]
    assert p._timer.period == 40
    p._timer.fire()
    assert tt.ui_in.writes == [5, 7]
    assert p._timer.period == 120
    p._timer.fire()
    assert tt.ui_in.writes == [5, 7, 6]
    assert p._timer.period == 40
    p._timer.fire()
    assert tt.ui_in.writes == [5, 7, 6, 7]
    assert p._timer.period == 250
    assert tt.resets == []


def test_keys_reset_and_restart_after_last_wait():
    tt, p = player(CONNECT4)
    p.start()
    for _ in range(4):
        p._timer.fire()
    # end of the last 250 ms wait: reset, base ui_in again, then step 1
    assert tt.resets == [True, False]
    assert tt.ui_in.writes[-2:] == [7, 5]
    assert p.passes == 1
    assert p._timer.period == 40


def test_keys_identical_every_loop():
    tt, p = player(CONNECT4)
    p.start()
    for _ in range(8):
        p._timer.fire()
    first, second = tt.ui_in.writes[:5], tt.ui_in.writes[5:10]
    assert first == [5, 7, 6, 7, 7] and second == first
    assert tt.resets == [True, False, True, False]


def test_keys_zero_wait_steps_run_through():
    tt, p = player([{'set': 1}, {'wait_ms': 0}, {'set': 2}, {'wait_ms': 10}])
    p.start()
    assert tt.ui_in.writes == [1, 2]
    assert p._timer.period == 10


def test_keys_stop_restores_base():
    tt, p = player(CONNECT4)
    p.start()
    p.stop()
    assert tt.ui_in.value == 7
    assert not p._timer.active
    assert not p.running


def test_gamepad_frame_waveform():
    base = 0b10000011        # other ui pins keep their base value
    tt, p = player([{'set': 0b000010001000}, {'wait_ms': 100}], via='gamepad', base=base)
    p.start()
    w = tt.ui_in.writes
    assert len(w) == 24 * 2 + 3
    idle = base & ~0x70
    report = 0b000010001000 << 12
    for i in range(24):
        bit = (report >> i) & 1
        assert w[2 * i] == idle | (bit << 6)               # data, clock low
        assert w[2 * i + 1] == idle | (bit << 6) | 0x20    # clock high
    assert w[48:] == [idle, idle | 0x10, idle]           # latch pulse
    # all writes leave the non-gamepad pins alone
    assert all(v & ~0x70 == idle for v in w)


def test_gamepad_stop_sends_empty_report():
    tt, p = player([{'set': 0xfff}, {'wait_ms': 100}], via='gamepad', base=0)
    p.start()
    tt.ui_in.writes.clear()
    p.stop()
    data_bits = [(v >> 6) & 1 for v in tt.ui_in.writes[:48:2]]
    assert data_bits == [0] * 24


def test_runner_starts_and_stops_player():
    keys = parse_keys({'via': 'ui', 'steps': CONNECT4})
    tt, shuttle, run = make([E(260, ui_in=7, keys=keys), E(2)])
    run.start()
    assert run._player is not None and run._player.running
    assert tt.ui_in.value == 5          # first step applied after ui_in
    run._timer.fire()                    # switch to the next project
    assert run._player is None
    assert shuttle.enabled.name == 'p2'


def test_manual_enable_stops_player():
    keys = parse_keys({'via': 'ui', 'steps': CONNECT4})
    tt, shuttle, run = make([E(260, ui_in=7, keys=keys), E(2)], keys=[260, 2, 3])
    run.start()
    player_ = run._player
    shuttle.get(3).enable()
    assert not player_.running
    assert not run.running


def test_entry_without_keys_never_reset():
    tt, shuttle, run = make([E(1), E(2)])
    run.start()
    run._timer.fire()
    run._timer.fire()
    assert tt.resets == []
