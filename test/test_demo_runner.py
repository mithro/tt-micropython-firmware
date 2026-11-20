'''
Tests for DemoRunner using a fake demoboard, shuttle and timer.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_runner.py
'''
from ttboard.demo import DemoRunner


class FakePort:
    def __init__(self):
        self.value = 0


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
    def __init__(self, names, failing=(), addresses=None):
        self.designs = {n: FakeDesign(self, n, n not in failing) for n in names}
        self.addresses = addresses or {}
        self.enabled = None
        self.enable_calls = []
        self.callback_calls = []
        self.design_enabled_callback = self.callback_calls.append

    def has(self, name):
        return name in self.designs

    def get(self, name):
        if name in self.addresses:
            return self.designs[self.addresses[name]]
        if name in self.designs:
            return self.designs[name]
        raise AttributeError(f'Unknown project ({name})')


class FakeTT:
    def __init__(self, shuttle):
        self.shuttle = shuttle
        self.ui_in = FakePort()
        self.uio_in = FakePort()
        self.uio_oe_pico = FakePort()
        self.clock_calls = []

    def clock_project_PWM(self, hz):
        self.clock_calls.append(hz)


class FakeTimer:
    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self):
        self.period = None
        self.mode = None
        self.callback = None
        self.active = False
        self.inits = 0

    def init(self, period, mode, callback):
        self.period = period
        self.mode = mode
        self.callback = callback
        self.active = True
        self.inits += 1

    def deinit(self):
        self.active = False

    def fire(self):
        assert self.active
        self.active = False  # one-shot
        self.callback(self)


def make(entries, names=None, seconds=15, **kw):
    if names is None:
        names = [e['macro'] for e in entries if 'macro' in e]
    shuttle = FakeShuttle(names, **kw)
    tt = FakeTT(shuttle)
    return tt, shuttle, DemoRunner(tt, entries, seconds, timer_class=FakeTimer)


def test_filters_unavailable_projects():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'gone'}, {'macro': 'b'}], names=['a', 'b'])
    assert [e['macro'] for e in run.playlist] == ['a', 'b']


def test_address_entries_checked_via_get():
    entries = [{'address': '5-0'}, {'address': '9-0'}]
    tt, shuttle, run = make(entries, names=['five'], addresses={'5-0': 'five'})
    assert run.playlist == [{'address': '5-0'}]


def test_start_enables_first_and_arms_timer():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b', 'seconds': 2.5}])
    assert run.start()
    assert run.running
    assert shuttle.enabled.name == 'a'
    assert run._timer.mode == FakeTimer.ONE_SHOT
    assert run._timer.period == 15000


def test_per_entry_seconds_and_wrap():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b', 'seconds': 2.5}])
    run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'b'
    assert run._timer.period == 2500
    run._timer.fire()
    assert shuttle.enabled.name == 'a'
    assert run._timer.period == 15000


def test_single_entry_shown_without_switching():
    tt, shuttle, run = make([{'macro': 'a'}])
    assert run.start()
    assert shuttle.enabled.name == 'a'
    assert not run._timer.active


def test_start_with_empty_playlist():
    tt, shuttle, run = make([], names=['a'])
    assert not run.start()
    assert not run.running


def test_overrides_applied_after_enable():
    entry = {'macro': 'a', 'clock_hz': 25175000, 'ui_in': 0x12,
             'uio_oe_pico': 0x0f, 'uio_in': 0x05}
    tt, shuttle, run = make([entry, {'macro': 'b'}])
    run.start()
    assert tt.clock_calls == [25175000]
    assert tt.ui_in.value == 0x12
    assert tt.uio_oe_pico.value == 0x0f
    assert tt.uio_in.value == 0x05


def test_no_overrides_leaves_ports_alone():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    tt.ui_in.value = 7
    run.start()
    assert tt.clock_calls == []
    assert tt.ui_in.value == 7


def test_original_callback_still_called():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    run.start()
    assert [d.name for d in shuttle.callback_calls] == ['a']


def test_manual_enable_stops_demo():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}], names=['a', 'b', 'c'])
    run.start()
    shuttle.get('c').enable()
    assert not run.running
    assert not run._timer.active
    # callback restored, and the original still saw the manual enable
    assert shuttle.design_enabled_callback == shuttle.callback_calls.append
    assert [d.name for d in shuttle.callback_calls] == ['a', 'c']


def test_stop_restores_callback():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    orig = shuttle.design_enabled_callback
    run.start()
    assert shuttle.design_enabled_callback != orig
    run.stop()
    assert shuttle.design_enabled_callback == orig
    assert not run.running


def test_start_twice_is_noop():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    run.start()
    run.start()
    assert shuttle.enable_calls == ['a']


def test_restart_after_stop():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    run.start()
    run.stop()
    assert run.start()
    assert run.running


def test_skips_failing_projects():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}, {'macro': 'c'}], failing=['b'])
    run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'c'


def test_enable_returning_none_but_enabled_counts_as_success():
    # FPGA BitStream.enable() returns None even when the bitstream loaded
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    for d in shuttle.designs.values():
        orig = d.enable
        d.enable = (lambda o: (lambda force=False: (o(force), None)[1]))(orig)
    assert run.start()
    assert shuttle.enabled.name == 'a'
    run._timer.fire()
    assert shuttle.enabled.name == 'b'
    assert run.running


def test_enable_returning_none_and_nothing_enabled_is_failure():
    # e.g. ProjectMux.enable() on a GROUP: disables, returns None
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])

    def group_enable(force=False):
        shuttle.enable_calls.append('a')
        shuttle.enabled = None
        return None
    shuttle.get('a').enable = group_enable
    assert run.start()
    assert shuttle.enabled.name == 'b'


def test_all_failing_stops_without_looping():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}], failing=['a', 'b'])
    assert not run.start()
    assert shuttle.enable_calls == ['a', 'b']
    assert not run.running


def test_exception_in_tick_rearms():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}, {'macro': 'c'}])

    def boom(force=False):
        raise RuntimeError('mux problem')
    shuttle.get('b').enable = boom
    run.start()
    run._timer.fire()   # must not raise out of the timer callback
    assert run.running
    assert shuttle.enabled.name == 'c'
    assert run._timer.active


def test_next_while_stopped_just_switches():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b'}])
    run.next()
    assert shuttle.enabled.name == 'a'
    run.next()
    assert shuttle.enabled.name == 'b'
    assert not run.running


def test_next_while_running_resets_timer():
    tt, shuttle, run = make([{'macro': 'a'}, {'macro': 'b', 'seconds': 3}])
    run.start()
    run.next()
    assert shuttle.enabled.name == 'b'
    assert run._timer.period == 3000
    assert run.running
