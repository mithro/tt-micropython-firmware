'''
Created on Nov 20, 2026

Demo mode: cycle through a fixed sequence of projects -- e.g. VGA designs
on a screen at a booth -- with no computer attached, optionally playing a
fixed script of inputs to each (e.g. to make a game play itself).

Turning it on: "demo = yes" in config.ini's [DEFAULT] section.  Holding
the project reset button while the board powers up flips that setting
for one boot (see boot_button_held() and main.py).

The sequence: /demo.json if it exists, otherwise the one bundled with
the firmware for the detected chip, /shuttles/<shuttle>.demo.json.  Both
have exactly the same format, and every field is required:

    {"version": 1,
     "shuttle": "ttsky25a",            # must match the chip ROM
     "projects": [
       {"address": 260,                # the shuttle index address
        "subtile": 0,                  # the shuttle index subtile_addr
        "duration_ms": 15000,          # how long to show it
        "clock_hz": 25000000,          # project clock (0: no clock)
        "ui_in": 7,                    # input value set after enabling
        "steps": [{"set": 6}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 250}]}]}

"steps" is played in order: {"set": N} writes ui_in, {"wait_ms": N}
waits.  When the steps run out the project is reset and they start over
from the first step (ui_in is not re-applied: start with a "set" if it
matters).  An empty "steps" list plays nothing and never resets.

An invalid sequence is never shown partly: every problem is logged, and
the board shows an error pattern instead (see ErrorDisplay).

From the REPL:
    tt.demo.start() / tt.demo.stop() / tt.demo.next() / tt.demo.errors

Enabling any project by hand (REPL or the commander app) stops the demo.

This module only uses the public SDK API, so it also runs on SDK
releases that don't ship it.

@author: Tim 'mithro' Ansell
'''
import json
from ttboard.pins.upython import Timer
import ttboard.log as logging
log = logging.getLogger(__name__)

UserPath = '/demo.json'
IniPath = 'config.ini'
IniOption = 'demo'
Version = 1

_TopFields = ('version', 'shuttle', 'projects')
_EntryFields = ('address', 'subtile', 'duration_ms', 'clock_hz', 'ui_in', 'steps')


def shuttle_sequence_path(shuttle_run: str) -> str:
    '''The sequence bundled with the firmware for a chip.'''
    return f'/shuttles/{shuttle_run}.demo.json'


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _exists(path: str) -> bool:
    try:
        with open(path):
            return True
    except OSError:
        return False


def demo_setting(ini_path: str = IniPath) -> bool:
    '''
        Is "demo = yes" set in config.ini's [DEFAULT] section?
    '''
    from ttboard.config.parser import ConfigParser
    conf = ConfigParser()
    try:
        conf.read(ini_path)
    except OSError:
        return False
    return conf.get('DEFAULT', IniOption) is True


def entry_key(entry: dict):
    '''
        How the project mux looks the entry up: the plain address for a
        normal project (the only form the FPGA bitstream index accepts),
        "ADDRESS-SUBTILE" for a subtile.
    '''
    if entry['subtile']:
        return f"{entry['address']}-{entry['subtile']}"
    return entry['address']


def _check_steps(where: str, steps, errors: list):
    if not isinstance(steps, list):
        errors.append(f'{where}: "steps" must be a list')
        return
    total_wait = 0
    for i, step in enumerate(steps):
        here = f'{where} step {i}'
        if not isinstance(step, dict) or len(step) != 1:
            errors.append(f'{here}: must be an object with exactly one key: {step}')
            continue
        if 'set' in step:
            v = step['set']
            if not (_is_int(v) and 0 <= v <= 0xff):
                errors.append(f'{here}: "set" must be an integer 0..255, got {v}')
        elif 'wait_ms' in step:
            v = step['wait_ms']
            if not (_is_int(v) and v >= 0):
                errors.append(f'{here}: "wait_ms" must be an integer >= 0, got {v}')
            else:
                total_wait += v
        else:
            errors.append(f'{here}: unknown step {step}')
    if len(steps) and total_wait <= 0:
        # a loop that never waits would never give control back
        errors.append(f'{where}: "steps" must wait for some time in total')


def _check_entry(where: str, e, errors: list):
    if not isinstance(e, dict):
        errors.append(f'{where}: must be an object')
        return False
    ok = True
    for f in e:
        if f not in _EntryFields:
            errors.append(f'{where}: unknown field "{f}"')
            ok = False
    for f in _EntryFields:
        if f not in e:
            errors.append(f'{where}: missing "{f}"')
            ok = False
    if not ok:
        return False
    checks = [
        ('address', _is_int(e['address']) and e['address'] >= 0, 'an integer >= 0'),
        ('subtile', _is_int(e['subtile']) and e['subtile'] >= 0, 'an integer >= 0'),
        ('duration_ms', _is_int(e['duration_ms']) and e['duration_ms'] > 0, 'an integer > 0'),
        ('clock_hz', _is_int(e['clock_hz']) and e['clock_hz'] >= 0, 'an integer >= 0'),
        ('ui_in', _is_int(e['ui_in']) and 0 <= e['ui_in'] <= 0xff, 'an integer 0..255'),
    ]
    for field, good, what in checks:
        if not good:
            errors.append(f'{where}: "{field}" must be {what}, got {e[field]}')
            ok = False
    n = len(errors)
    _check_steps(where, e['steps'], errors)
    return ok and len(errors) == n


def validate(conf, shuttle_run: str, shuttle=None):
    '''
        Check a parsed sequence against the format and, if a shuttle (the
        project mux) is given, against the projects actually on the chip.
        Returns (entries, errors): entries is only meaningful when errors
        is empty.
    '''
    errors = []
    if not isinstance(conf, dict):
        return ([], ['must be a JSON object'])
    for f in conf:
        if f not in _TopFields:
            errors.append(f'unknown field "{f}"')
    for f in _TopFields:
        if f not in conf:
            errors.append(f'missing "{f}"')
    if len(errors):
        return ([], errors)
    if conf['version'] != Version or not _is_int(conf['version']):
        errors.append(f'"version" must be {Version}, got {conf["version"]}')
    if conf['shuttle'] != shuttle_run:
        errors.append(f'"shuttle" is "{conf["shuttle"]}" but this chip is "{shuttle_run}"')
    projects = conf['projects']
    if not isinstance(projects, list) or not len(projects):
        errors.append('"projects" must be a non-empty list')
        return ([], errors)

    entries = []
    for i, e in enumerate(projects):
        where = f'project {i}'
        if not _check_entry(where, e, errors):
            continue
        entries.append(e)
        if shuttle is None:
            continue
        key = entry_key(e)
        try:
            design = shuttle.get(key)
        except Exception:
            design = None
        if design is None:
            errors.append(f'{where}: no project at address {key} on {shuttle_run}')
            continue
        if getattr(design, 'danger_level', 0):
            errors.append(f'{where}: project {key} ({design.name}) is not marked safe '
                          'and would not be enabled')
    return (entries, errors)


def load(path: str, shuttle_run: str, shuttle=None):
    '''
        Read and validate a sequence file.  Returns (entries, errors).
    '''
    try:
        with open(path) as fh:
            conf = json.load(fh)
    except OSError:
        return ([], [f'cannot read {path}'])
    except ValueError as e:
        return ([], [f'not valid JSON: {e}'])
    return validate(conf, shuttle_run, shuttle)


def boot_button_held(reset_pin=None, led_pin=None, sleep_ms=None,
                     release_timeout_ms: int = 10000) -> bool:
    '''
        Was the project reset button held as the board powered up?

        Call this at the very start of main.py, before the demoboard is
        probed.  The reset line has an on-board pull-up, so it reads low
        only while the button is pressed.  If it is held we blink the LED
        until it is released, because the chip ROM read that follows needs
        to drive that line itself.  A line that stays low for longer than
        release_timeout_ms is treated as not pressed.

        The pins and sleep function may be passed in for testing.
    '''
    if sleep_ms is None:
        import ttboard.util.time as time
        sleep_ms = time.sleep_ms
    if reset_pin is None or led_pin is None:
        from ttboard.pins.upython import Pin
        from ttboard.pins.gpio_map_dbv3 import GPIOMapTTDBv3
        if reset_pin is None:
            reset_pin = Pin(GPIOMapTTDBv3.PROJECT_nRST, Pin.IN)
        if led_pin is None:
            led_pin = Pin(GPIOMapTTDBv3.RP_LED, Pin.OUT)

    # debounce: must read low for the whole sampling window
    for _i in range(5):
        if reset_pin():
            return False
        sleep_ms(10)

    log.info('Demo: reset button held at boot, waiting for release')
    waited = 0
    led = 1
    while not reset_pin():
        if waited >= release_timeout_ms:
            log.warn('Demo: reset line stayed low, ignoring it')
            led_pin(0)
            return False
        led_pin(led)
        led = 1 - led
        sleep_ms(100)
        waited += 100
    led_pin(0)
    # let the button settle before the ROM read drives the line
    sleep_ms(50)
    return True


def autostart(tt, button_held: bool, ini_path: str = IniPath,
              user_path: str = UserPath, shuttle_path: str = None,
              error_display=None):
    '''
        Build tt.demo and start it if config.ini's "demo" setting, flipped
        by the boot button, says so.  The sequence is user_path if it
        exists, otherwise the chip's bundled one.  If that is missing or
        invalid, every problem is logged and the error display is shown
        instead.  Always returns the DemoRunner.
    '''
    run = tt.shuttle.run
    if shuttle_path is None:
        shuttle_path = shuttle_sequence_path(run)
    path = user_path if _exists(user_path) else shuttle_path
    on = demo_setting(ini_path) != bool(button_held)

    runner = DemoRunner(tt, [], path=path, error_display=error_display)
    if not on:
        if button_held:
            log.info('Demo: reset button held, skipping the demo for this boot')
        return runner
    if not _exists(path):
        runner.fail([f'no demo sequence: neither {user_path} nor {shuttle_path} exists'])
        return runner
    entries, errors = load(path, run, tt.shuttle)
    if len(errors):
        runner.fail(errors)
        return runner
    runner.playlist = entries
    runner.start()
    return runner


class ErrorDisplay:
    '''
        Makes a demo error visible on a board nobody is watching the logs
        of: blinks "E" on the 7-segment display and the RP's LED.

        The display is driven by the chip, so we use the factory test
        design, which mirrors ui_in to uo_out while held in reset.  If that
        can't be set up, the LED still blinks.  Enabling any project by
        hand stops the display, leaving that project's inputs alone.
    '''
    Pattern = 0x79          # "E": segments a, d, e, f, g
    PeriodMs = 250

    def __init__(self, tt, timer_class=Timer, led_pin=None):
        self._tt = tt
        self._timer_class = timer_class
        self._led = led_pin
        self._timer = None
        self._segments = False
        self._on = False
        self._orig_callback = None
        self._hooked = False

    def start(self):
        tt = self._tt
        try:
            from ttboard.mode import RPMode
            tt.shuttle.tt_um_factory_test.enable()
            tt.mode = RPMode.ASIC_RP_CONTROL
            tt.clock_project_stop()
            tt.reset_project(True)
            self._segments = True
        except Exception as e:
            log.error(f'Demo: no 7-segment error display ({e}), using the LED only')
        # installed after enabling the factory test, so only later
        # (manual) enables trigger it
        self._orig_callback = tt.shuttle.design_enabled_callback
        tt.shuttle.design_enabled_callback = self._design_enabled
        self._hooked = True
        if self._led is None:
            try:
                from ttboard.pins.upython import Pin
                from ttboard.pins.gpio_map_dbv3 import GPIOMapTTDBv3
                self._led = Pin(GPIOMapTTDBv3.RP_LED, Pin.OUT)
            except Exception as e:
                log.error(f'Demo: no LED for the error display ({e})')
        self._timer = self._timer_class()
        self._timer.init(period=self.PeriodMs, mode=self._timer_class.PERIODIC,
                         callback=self._blink)

    def stop(self, release_pins: bool = True):
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None
        if self._hooked:
            if self._tt.shuttle.design_enabled_callback == self._design_enabled:
                self._tt.shuttle.design_enabled_callback = self._orig_callback
            self._hooked = False
        if self._segments and release_pins:
            self._tt.ui_in.value = 0
            self._tt.reset_project(False)
        self._segments = False
        if self._led is not None:
            self._led(0)

    def _design_enabled(self, design):
        orig = self._orig_callback
        # a project was picked by hand: get out of its way
        self.stop(release_pins=False)
        if orig is not None:
            orig(design)

    def _blink(self, _timer):
        self._on = not self._on
        try:
            if self._segments:
                self._tt.ui_in.value = self.Pattern if self._on else 0
            if self._led is not None:
                self._led(1 if self._on else 0)
        except Exception:
            pass


class StepPlayer:
    '''
        Plays an entry's "steps", looping: "set" is applied at once,
        "wait_ms" arms a one-shot timer.  When the steps run out the
        project is reset and they start over.
    '''

    def __init__(self, tt, steps: list, timer_class=Timer, sleep_ms=None):
        self._tt = tt
        self.steps = steps
        self._timer_class = timer_class
        if sleep_ms is None:
            import ttboard.util.time as time
            sleep_ms = time.sleep_ms
        self._sleep_ms = sleep_ms
        self._timer = None
        self._active = False
        self._step = 0
        self._waiting = False
        self.passes = 0

    @property
    def running(self) -> bool:
        return self._active

    def start(self):
        if not len(self.steps):
            return
        self._active = True
        self._step = 0
        self._waiting = False
        self.passes = 0
        if self._timer is None:
            self._timer = self._timer_class()
        self._run()

    def stop(self):
        if self._timer is not None:
            self._timer.deinit()
        self._active = False

    def _run(self):
        # run steps until one waits; the steps always wait for some time
        # in total (validate() checks), so this terminates.  A wait is only
        # passed once its timer has fired, so a pass ends at the end of the
        # last wait, not its start.
        while self._active:
            step = self.steps[self._step]
            if 'set' in step:
                self._tt.ui_in.value = step['set']
            elif step['wait_ms'] > 0 and not self._waiting:
                self._waiting = True
                self._timer.init(period=step['wait_ms'], mode=self._timer_class.ONE_SHOT,
                                 callback=self._on_timer)
                return
            self._waiting = False
            self._step += 1
            if self._step == len(self.steps):
                # out of steps: reset the project and start over
                self._step = 0
                self.passes += 1
                self._tt.reset_project(True)
                self._sleep_ms(2)
                self._tt.reset_project(False)

    def _on_timer(self, _timer):
        try:
            self._run()
        except Exception as e:
            log.error(f'Demo: steps error: {e}')


class DemoRunner:
    '''
        Shows each project of a validated sequence in turn, on a one-shot
        machine.Timer re-armed after every switch.  Available as tt.demo.
    '''

    def __init__(self, tt, entries: list, path: str = None, timer_class=Timer,
                 sleep_ms=None, error_display=None):
        self._tt = tt
        self._shuttle = tt.shuttle
        self.playlist = list(entries)
        self.path = path
        self.errors = []
        self._timer_class = timer_class
        self._sleep_ms = sleep_ms
        self._timer = None
        self._index = -1
        self._active = False
        self._orig_callback = None
        self._player = None
        self._error_display = error_display
        # True while we enable a project, so our design-enabled hook
        # can tell our switches apart from manual ones
        self.switching = False

    @property
    def running(self) -> bool:
        return self._active

    @property
    def current(self):
        if self._index < 0 or not len(self.playlist):
            return None
        return self.playlist[self._index]

    def fail(self, errors: list):
        '''
            Stop, log every error and show the error display.
        '''
        self.stop()
        self.errors = list(errors)
        where = f' in {self.path}' if self.path else ''
        log.error(f'Demo: {len(self.errors)} problem(s){where}, not running the demo:')
        for err in self.errors:
            log.error(f'Demo:   {err}')
        if self._error_display is None:
            self._error_display = ErrorDisplay(self._tt, self._timer_class)
        self._error_display.start()

    def start(self) -> bool:
        '''
            Start the demo with the first project.  Returns True if it is
            running.
        '''
        if self._active:
            return True
        if not len(self.playlist):
            log.warn('Demo: nothing to show')
            return False
        if self._timer is None:
            self._timer = self._timer_class()
        self._install_hook()
        self._active = True
        self._index = -1
        if not self._advance():
            return False
        log.info(f'Demo: started, {len(self.playlist)} project(s) from {self.path}')
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.deinit()
        self._stop_player()
        if self._active:
            log.info('Demo: stopped')
        self._active = False
        self._remove_hook()

    def next(self):
        '''Switch to the next project now.'''
        if self._active:
            self._advance()

    def _advance(self) -> bool:
        self._index = (self._index + 1) % len(self.playlist)
        entry = self.playlist[self._index]
        try:
            ok = self._show(entry)
        except Exception as e:
            self.fail([f'project {entry_key(entry)}: {e}'])
            return False
        if not ok:
            self.fail([f'project {entry_key(entry)} could not be enabled'])
            return False
        if len(self.playlist) > 1:
            self._timer.init(period=entry['duration_ms'], mode=self._timer_class.ONE_SHOT,
                             callback=self._on_timer)
        return True

    def _show(self, entry: dict) -> bool:
        self._stop_player()
        self.switching = True
        try:
            design = self._shuttle.get(entry_key(entry))
            result = design.enable()
        finally:
            self.switching = False
        # enable()'s return value isn't reliable on its own: FPGA
        # bitstreams return None even when loaded, and ProjectMux returns
        # None for a group it refused.  False is always a refusal (e.g.
        # danger level); otherwise trust what the mux says is enabled.
        enabled = self._shuttle.enabled
        if result is False or enabled is None or enabled.name != design.name:
            return False

        tt = self._tt
        if entry['clock_hz']:
            tt.clock_project_PWM(entry['clock_hz'])
        else:
            tt.clock_project_stop()
        tt.ui_in.value = entry['ui_in']
        if len(entry['steps']):
            self._player = StepPlayer(tt, entry['steps'], self._timer_class, self._sleep_ms)
            self._player.start()
        return True

    def _stop_player(self):
        if self._player is not None:
            self._player.stop()
            self._player = None

    def _on_timer(self, _timer):
        # never let an exception escape a timer callback
        try:
            if self._active:
                self._advance()
        except Exception as e:
            log.error(f'Demo: timer error: {e}')

    def _install_hook(self):
        self._orig_callback = self._shuttle.design_enabled_callback
        self._shuttle.design_enabled_callback = self._design_enabled

    def _remove_hook(self):
        if self._shuttle.design_enabled_callback == self._design_enabled:
            self._shuttle.design_enabled_callback = self._orig_callback
        self._orig_callback = None

    def _design_enabled(self, design):
        orig = self._orig_callback
        if orig is not None:
            orig(design)
        if self._active and not self.switching:
            log.info(f'Demo: "{design.name}" enabled by hand, stopping demo')
            self.stop()

    def __repr__(self):
        if self.errors:
            return f'<DemoRunner FAILED, {len(self.errors)} error(s) in {self.path}: see .errors>'
        state = 'running' if self._active else 'stopped'
        keys = ', '.join(str(entry_key(e)) for e in self.playlist)
        return f'<DemoRunner {state}, {len(self.playlist)} projects: {keys}>'
