'''
Tests for ProjectRotation, using a fake shuttle and timer.

Run with:
    PYTHONPATH=src pytest test/test_project_rotation.py
'''
from ttboard.project_rotation import ProjectRotation


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
        return True


class FakeShuttle:
    def __init__(self, names, failing=()):
        self.designs = {n: FakeDesign(self, n, n not in failing) for n in names}
        self.enabled = None
        self.enable_calls = []

    def has(self, name):
        return name in self.designs

    def get(self, name):
        return self.designs[name]


class FakeTimer:
    PERIODIC = 1
    instances = []

    def __init__(self):
        self.period = None
        self.callback = None
        self.active = False
        FakeTimer.instances.append(self)

    def init(self, period, mode, callback):
        self.period = period
        self.callback = callback
        self.active = True

    def deinit(self):
        self.active = False

    def fire(self):
        assert self.active
        self.callback(self)


def make(names, interval=15, failing=()):
    shuttle = FakeShuttle(names, failing)
    rot = ProjectRotation(shuttle, names, interval, timer_class=FakeTimer)
    return shuttle, rot


def test_cycles_in_order_and_wraps():
    shuttle, rot = make(['a', 'b', 'c'])
    shuttle.get('a').enable()  # boot loads the first one
    rot.start()
    assert rot.running
    assert rot._timer.period == 15000
    for expected in ['b', 'c', 'a', 'b']:
        rot._timer.fire()
        assert shuttle.enabled.name == expected


def test_fractional_interval_period_ms():
    _shuttle, rot = make(['a', 'b'], interval=2.5)
    rot.start()
    assert rot._timer.period == 2500


def test_stop_deinits_timer():
    _shuttle, rot = make(['a', 'b'])
    rot.start()
    timer = rot._timer
    rot.stop()
    assert not rot.running
    assert not timer.active


def test_start_twice_uses_one_timer():
    _shuttle, rot = make(['a', 'b'])
    rot.start()
    first = rot._timer
    rot.start()
    assert rot._timer is first


def test_does_not_start_with_single_project():
    _shuttle, rot = make(['a'])
    rot.start()
    assert not rot.running


def test_does_not_start_with_zero_interval():
    _shuttle, rot = make(['a', 'b'], interval=0)
    rot.start()
    assert not rot.running


def test_skips_project_that_fails_to_enable():
    shuttle, rot = make(['a', 'b', 'c'], failing=['b'])
    shuttle.get('a').enable()
    rot.start()
    rot._timer.fire()
    assert shuttle.enabled.name == 'c'
    assert shuttle.enable_calls == ['a', 'b', 'c']


def test_all_failing_does_not_loop_forever():
    shuttle, rot = make(['a', 'b'], failing=['a', 'b'])
    rot.start()
    rot._timer.fire()
    assert shuttle.enable_calls == ['b', 'a']


def test_exception_in_enable_keeps_timer_running():
    shuttle, rot = make(['a', 'b'])

    def boom(force=False):
        raise RuntimeError('mux problem')
    shuttle.get('b').enable = boom
    rot.start()
    rot._timer.fire()  # must not raise out of the timer callback
    assert rot.running


def test_switching_flag_set_only_during_enable():
    shuttle, rot = make(['a', 'b'])
    seen = []
    orig = shuttle.get('b').enable

    def spy(force=False):
        seen.append(rot.switching)
        return orig(force)
    shuttle.get('b').enable = spy
    assert not rot.switching
    rot.next()
    assert seen == [True]
    assert not rot.switching
