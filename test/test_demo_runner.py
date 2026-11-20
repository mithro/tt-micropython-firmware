'''
Tests for DemoRunner, StepPlayer and ErrorDisplay using a fake demoboard,
shuttle and timer.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_runner.py
'''
from ttboard.demo import DemoRunner, ErrorDisplay, StepPlayer


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
    run = 'ttfake'

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
        self.ui_in = WatchedPort()
        self.clock_calls = []
        self.resets = []

    def clock_project_PWM(self, hz):
        self.clock_calls.append(hz)

    def clock_project_stop(self):
        self.clock_calls.append(0)

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
        if self.mode == self.ONE_SHOT:
            self.active = False
        self.callback(self)


class FakeErrorDisplay:
    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1


def E(address, subtile=0, duration_ms=15000, clock_hz=0, ui_in=0, steps=()):
    return dict(address=address, subtile=subtile, duration_ms=duration_ms,
                clock_hz=clock_hz, ui_in=ui_in, steps=list(steps))


def make(entries, keys=None, failing=()):
    if keys is None:
        keys = [e['address'] if not e['subtile'] else f"{e['address']}-{e['subtile']}"
                for e in entries]
    shuttle = FakeShuttle(keys, failing)
    tt = FakeTT(shuttle)
    display = FakeErrorDisplay()
    run = DemoRunner(tt, entries, path='/demo.json', timer_class=FakeTimer,
                     sleep_ms=lambda ms: None, error_display=display)
    return tt, shuttle, run, display


def test_start_enables_first_and_arms_timer():
    tt, shuttle, run, _ = make([E(1), E(2, duration_ms=2500)])
    assert run.start()
    assert run.running
    assert shuttle.enabled.name == 'p1'
    assert run._timer.mode == FakeTimer.ONE_SHOT
    assert run._timer.period == 15000


def test_per_entry_duration_and_wrap():
    tt, shuttle, run, _ = make([E(1), E(2, duration_ms=2500)])
    run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'p2'
    assert run._timer.period == 2500
    run._timer.fire()
    assert shuttle.enabled.name == 'p1'
    assert run._timer.period == 15000


def test_subtile_looked_up_as_string():
    tt, shuttle, run, _ = make([E(5, 2), E(5)], keys=['5-2', 5])
    run.start()
    assert shuttle.enabled.name == 'p5-2'


def test_single_entry_shown_without_switching():
    tt, shuttle, run, _ = make([E(1)])
    assert run.start()
    assert shuttle.enabled.name == 'p1'
    assert not run._timer.active


def test_clock_and_ui_in_applied():
    tt, shuttle, run, _ = make([E(1, clock_hz=25000000, ui_in=0x12), E(2, clock_hz=0, ui_in=3)])
    run.start()
    assert tt.clock_calls == [25000000]
    assert tt.ui_in.value == 0x12
    run._timer.fire()
    assert tt.clock_calls == [25000000, 0]   # clock_hz 0 stops the clock
    assert tt.ui_in.value == 3


def test_original_callback_still_called():
    tt, shuttle, run, _ = make([E(1), E(2)])
    run.start()
    assert [d.name for d in shuttle.callback_calls] == ['p1']


def test_manual_enable_stops_demo():
    tt, shuttle, run, display = make([E(1), E(2)], keys=[1, 2, 3])
    run.start()
    shuttle.get(3).enable()
    assert not run.running
    assert not run._timer.active
    assert shuttle.design_enabled_callback == shuttle.callback_calls.append
    assert [d.name for d in shuttle.callback_calls] == ['p1', 'p3']
    assert display.started == 0       # stopping by hand is not an error


def test_stop_restores_callback():
    tt, shuttle, run, _ = make([E(1), E(2)])
    orig = shuttle.design_enabled_callback
    run.start()
    run.stop()
    assert shuttle.design_enabled_callback == orig


def test_start_twice_is_noop():
    tt, shuttle, run, _ = make([E(1), E(2)])
    run.start()
    run.start()
    assert shuttle.enable_calls == ['p1']


def test_next():
    tt, shuttle, run, _ = make([E(1), E(2, duration_ms=3000)])
    run.start()
    run.next()
    assert shuttle.enabled.name == 'p2'
    assert run._timer.period == 3000


def test_refused_enable_fails_loudly():
    tt, shuttle, run, display = make([E(1), E(2)], failing=[2])
    run.start()
    run._timer.fire()
    assert not run.running
    assert display.started == 1
    assert run.errors == ['project 2 could not be enabled']


def test_exception_fails_loudly_without_escaping_timer():
    tt, shuttle, run, display = make([E(1), E(2)])

    def boom(force=False):
        raise RuntimeError('mux problem')
    shuttle.get(2).enable = boom
    run.start()
    run._timer.fire()
    assert not run.running
    assert display.started == 1
    assert run.errors == ['project 2: mux problem']


def test_first_project_failing_fails_start():
    tt, shuttle, run, display = make([E(1), E(2)], failing=[1])
    assert not run.start()
    assert display.started == 1


def test_enable_returning_none_but_enabled_counts_as_success():
    # FPGA BitStream.enable() returns None even when the bitstream loaded
    tt, shuttle, run, display = make([E(1), E(2)])
    for d in shuttle.designs.values():
        orig = d.enable
        d.enable = (lambda o: (lambda force=False: (o(force), None)[1]))(orig)
    assert run.start()
    run._timer.fire()
    assert shuttle.enabled.name == 'p2'
    assert display.started == 0


def test_fail_logs_and_shows(capsys):
    tt, shuttle, run, display = make([E(1)])
    run.fail(['first problem', 'second problem'])
    assert display.started == 1
    assert run.errors == ['first problem', 'second problem']
    assert 'FAILED' in repr(run)


# --- steps ---------------------------------------------------------------

CONNECT4 = [{'set': 5}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 120},
            {'set': 6}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 250}]


def player(steps):
    tt = FakeTT(FakeShuttle([]))
    p = StepPlayer(tt, steps, timer_class=FakeTimer, sleep_ms=lambda ms: None)
    return tt, p


def test_steps_play_in_order_with_waits():
    tt, p = player(CONNECT4)
    p.start()
    assert tt.ui_in.writes == [5]
    assert p._timer.period == 40
    p._timer.fire()
    assert tt.ui_in.writes == [5, 7]
    assert p._timer.period == 120
    p._timer.fire()
    p._timer.fire()
    assert tt.ui_in.writes == [5, 7, 6, 7]
    assert p._timer.period == 250
    assert tt.resets == []


def test_steps_reset_and_restart_after_last_wait():
    tt, p = player(CONNECT4)
    p.start()
    for _ in range(4):
        p._timer.fire()
    # end of the last wait: reset, then step 1 again; ui_in NOT re-applied
    assert tt.resets == [True, False]
    assert tt.ui_in.writes == [5, 7, 6, 7, 5]
    assert p.passes == 1
    assert p._timer.period == 40


def test_steps_identical_every_loop():
    tt, p = player(CONNECT4)
    p.start()
    for _ in range(8):
        p._timer.fire()
    assert tt.ui_in.writes[:4] == tt.ui_in.writes[4:8] == [5, 7, 6, 7]
    assert tt.resets == [True, False, True, False]


def test_zero_wait_steps_run_through():
    tt, p = player([{'set': 1}, {'wait_ms': 0}, {'set': 2}, {'wait_ms': 10}])
    p.start()
    assert tt.ui_in.writes == [1, 2]
    assert p._timer.period == 10


def test_empty_steps_do_nothing():
    tt, p = player([])
    p.start()
    assert not p.running
    assert tt.ui_in.writes == [] and tt.resets == []


def test_runner_plays_steps_after_ui_in():
    tt, shuttle, run, _ = make([E(260, ui_in=7, steps=CONNECT4), E(2)])
    run.start()
    assert tt.ui_in.writes == [7, 5]      # entry ui_in, then step 1
    assert run._player.running
    run._timer.fire()                      # next project: player stopped
    assert run._player is None


def test_entry_without_steps_never_reset():
    tt, shuttle, run, _ = make([E(1), E(2)])
    run.start()
    run._timer.fire()
    run._timer.fire()
    assert tt.resets == []


def test_manual_enable_stops_player():
    tt, shuttle, run, _ = make([E(260, ui_in=7, steps=CONNECT4), E(2)], keys=[260, 2, 3])
    run.start()
    p = run._player
    shuttle.get(3).enable()
    assert not p.running


# --- error display -------------------------------------------------------

class DisplayTT(FakeTT):
    def __init__(self, has_factory_test=True):
        shuttle = FakeShuttle([])
        if has_factory_test:
            shuttle.tt_um_factory_test = FakeDesign(shuttle, 'tt_um_factory_test')
        super().__init__(shuttle)
        self.mode = None


class Led:
    def __init__(self):
        self.writes = []

    def __call__(self, v=None):
        if v is not None:
            self.writes.append(v)


def test_error_display_blinks_E_on_segments_and_led():
    tt = DisplayTT()
    led = Led()
    d = ErrorDisplay(tt, timer_class=FakeTimer, led_pin=led)
    d.start()
    assert tt.shuttle.enabled.name == 'tt_um_factory_test'
    assert tt.resets == [True]             # held in reset: uo_out mirrors ui_in
    assert d._timer.mode == FakeTimer.PERIODIC
    d._timer.fire()
    d._timer.fire()
    assert tt.ui_in.writes[-2:] == [0x79, 0]
    assert led.writes[-2:] == [1, 0]
    d.stop()
    assert tt.resets == [True, False]


def test_error_display_stops_when_project_enabled_by_hand():
    tt = DisplayTT()
    tt.shuttle.other = FakeDesign(tt.shuttle, 'other')
    led = Led()
    d = ErrorDisplay(tt, timer_class=FakeTimer, led_pin=led)
    d.start()
    timer = d._timer
    tt.ui_in.writes.clear()
    tt.shuttle.other.enable()
    assert not timer.active
    assert led.writes[-1] == 0
    # the hand-picked project's inputs are left alone, and the hook is gone
    assert tt.ui_in.writes == []
    assert tt.shuttle.design_enabled_callback == tt.shuttle.callback_calls.append
    assert [x.name for x in tt.shuttle.callback_calls][-1] == 'other'


def test_error_display_led_only_without_factory_test():
    tt = DisplayTT(has_factory_test=False)
    led = Led()
    d = ErrorDisplay(tt, timer_class=FakeTimer, led_pin=led)
    d.start()
    d._timer.fire()
    assert led.writes == [1]
    assert tt.ui_in.writes == []
