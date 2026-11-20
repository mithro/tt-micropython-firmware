'''
Created on Nov 20, 2026

Demo mode: cycle through a playlist of projects -- e.g. VGA designs on a
screen at a booth -- with no computer attached, optionally playing a
fixed sequence of inputs to each (e.g. to make a game play itself).

The playlist lives in /demo.json, keyed by shuttle.  There is exactly
one way to write each thing:

    {
      "version": 1,
      "enabled": false,           # true: run the demo on every boot
      "duration_ms": 15000,       # default time per project
      "shuttles": {
        "ttsky25a": {"projects": [ENTRY, ...]},
        "*":        {"projects": [ENTRY, ...]}    # any other shuttle
      }
    }

ENTRY (projects are identified by their shuttle index address only):

    {"address": 907,              # required: the index "address"
     "subtile": 0,                # required: the index "subtile_addr" (0 if none)
     "duration_ms": 15000,        # optional, overrides the default
     "clock_hz": 25175000,        # optional, overrides the index clock_hz
     "ui_in": 0,                  # optional base input value (0-255)
     "uio_oe_pico": 0,            # optional (0-255)
     "uio_in": 0,                 # optional (0-255)
     "keys": KEYS}                # optional

KEYS, played in order and looped while the project is shown:

    {"via": "ui",                 # "ui": "set" writes ui_in
                                  # "gamepad": "set" is a 12-bit Gamepad
                                  #   Pmod report, sent on ui[4..6]
     "steps": [{"set": 5}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 120}]}

Each step has exactly one key: "set" (an absolute value, applied at
once) or "wait_ms".  When the steps run out the project is reset, the
entry's ui_in is applied again and the steps start over, so every loop
plays out from the same state.  Entries without keys are never reset
while shown.  Gamepad report bits: b0 y1 select2 start3 up4 down5 left6
right7 a8 x9 l10 r11.

Each project's own config.ini section is applied when it is enabled, as
usual; the values here are applied on top of it.  Projects not on the
detected shuttle, or that refuse to enable (danger level), are skipped.
Invalid entries are skipped, invalid keys are dropped (the project is
still shown), and unknown fields are ignored -- all with a log message.

If /demo.json has no playlist for the detected shuttle (no section for
it and no "*" section), the shuttle's built-in playlist is used: see
shuttle_playlist_path().

Demo mode starts at boot if "enabled" is true, or if the project reset
button is held while the board powers up (holding it inverts "enabled",
so it can also be used to skip the demo for one boot).  See main.py.

From the REPL:
    tt.demo.start() / tt.demo.stop() / tt.demo.next()

Enabling any project by hand (REPL or the commander app) stops the demo.

This module only uses the public SDK API, so it also runs on SDK
releases that don't ship it.

@author: Tim 'mithro' Ansell
'''
import json
from ttboard.pins.upython import Timer
import ttboard.log as logging
log = logging.getLogger(__name__)

ConfigPath = '/demo.json'
DefaultDurationMs = 15000
Wildcard = '*'

_EntryByteOpts = ['ui_in', 'uio_oe_pico', 'uio_in']
_Vias = {'ui': 0xff, 'gamepad': 0xfff}   # via -> largest "set" value

# Gamepad Pmod wiring on ui_in, as on the Pmod and the VGA playground
GamepadLatchBit = 0x10   # ui[4]
GamepadClockBit = 0x20   # ui[5]
GamepadDataBit = 0x40    # ui[6]
GamepadPins = GamepadLatchBit | GamepadClockBit | GamepadDataBit


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def load_config(path: str = ConfigPath):
    '''
        Read a demo configuration, or None if it is missing or invalid.
    '''
    try:
        with open(path) as fh:
            conf = json.load(fh)
    except OSError:
        log.debug(f'No demo config at {path}')
        return None
    except ValueError as e:
        log.error(f'Demo config {path} is not valid JSON: {e}')
        return None
    if not isinstance(conf, dict):
        log.error(f'Demo config {path} must be a JSON object')
        return None
    return conf


def config_enabled(conf) -> bool:
    return isinstance(conf, dict) and conf.get('enabled') is True


def parse_keys(raw):
    '''
        Validate a "keys" object; returns it, or None (with a warning)
        if it can't be played.
    '''
    if not isinstance(raw, dict):
        log.warn(f'Demo: keys must be an object: {raw}')
        return None
    via = raw.get('via')
    if via not in _Vias:
        log.warn(f'Demo: keys "via" must be "ui" or "gamepad", got {via}')
        return None
    steps = raw.get('steps')
    if not isinstance(steps, list) or not len(steps):
        log.warn('Demo: keys need a non-empty "steps" list')
        return None
    max_set = _Vias[via]
    total_ms = 0
    parsed = []
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            log.warn(f'Demo: keys step must be an object with exactly one key: {step}')
            return None
        if 'set' in step:
            v = step['set']
            if not (_is_int(v) and 0 <= v <= max_set):
                log.warn(f'Demo: keys "set" must be an integer 0..{max_set}: {step}')
                return None
            parsed.append(('set', v))
        elif 'wait_ms' in step:
            v = step['wait_ms']
            if not (_is_int(v) and v >= 0):
                log.warn(f'Demo: keys "wait_ms" must be an integer >= 0: {step}')
                return None
            parsed.append(('wait_ms', v))
            total_ms += v
        else:
            log.warn(f'Demo: unknown keys step {step}')
            return None
    if total_ms <= 0:
        # a loop that never waits would never give control back
        log.warn('Demo: keys steps must wait for some time')
        return None
    return {'via': via, 'steps': parsed}


def parse_entry(raw):
    '''
        Validate one playlist entry.  Returns a dict with 'address',
        'subtile' and any valid options, or None if it can't be used.
    '''
    if not isinstance(raw, dict):
        log.warn(f'Demo: ignoring playlist entry {raw}: must be an object')
        return None
    address = raw.get('address')
    subtile = raw.get('subtile')
    if not (_is_int(address) and address >= 0 and _is_int(subtile) and subtile >= 0):
        log.warn(f'Demo: playlist entry needs integer "address" and "subtile": {raw}')
        return None
    entry = {'address': address, 'subtile': subtile}

    for opt in ['duration_ms', 'clock_hz']:
        v = raw.get(opt)
        if v is None:
            continue
        if _is_int(v) and v > 0:
            entry[opt] = v
        else:
            log.warn(f'Demo: ignoring bad {opt} {v} in {raw}')

    for opt in _EntryByteOpts:
        v = raw.get(opt)
        if v is None:
            continue
        if _is_int(v) and 0 <= v <= 0xff:
            entry[opt] = v
        else:
            log.warn(f'Demo: ignoring bad {opt} {v} in {raw}')

    if raw.get('keys') is not None:
        keys = parse_keys(raw['keys'])
        if keys is not None:
            entry['keys'] = keys
        else:
            log.warn(f'Demo: dropping keys of {entry_key(entry)}, still showing it')
    return entry


def select_playlist(conf, shuttle_run: str):
    '''
        Pick the playlist for this shuttle (falling back to the "*"
        section) and the default time per project.
        Returns (entries, duration_ms).
    '''
    duration_ms = DefaultDurationMs
    if not isinstance(conf, dict):
        return ([], duration_ms)
    d = conf.get('duration_ms')
    if d is not None:
        if _is_int(d) and d > 0:
            duration_ms = d
        else:
            log.warn(f'Demo: ignoring bad duration_ms {d}')

    shuttles = conf.get('shuttles')
    if not isinstance(shuttles, dict):
        return ([], duration_ms)
    section = shuttles.get(shuttle_run)
    if section is None:
        section = shuttles.get(Wildcard)
    if not isinstance(section, dict):
        return ([], duration_ms)
    raw_list = section.get('projects')
    if not isinstance(raw_list, list):
        return ([], duration_ms)

    entries = []
    for raw in raw_list:
        e = parse_entry(raw)
        if e is not None:
            entries.append(e)
    return (entries, duration_ms)


def entry_key(entry: dict):
    '''
        How the project mux looks the entry up: the plain address for a
        normal project (the only form the FPGA bitstream index accepts),
        "ADDRESS-SUBTILE" for a subtile.
    '''
    if entry['subtile']:
        return f"{entry['address']}-{entry['subtile']}"
    return entry['address']


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


def shuttle_playlist_path(shuttle_run: str) -> str:
    '''
        The shuttle's curated playlist, built into the firmware from the
        shuttle index's "demo" field (see bin/extract_demo_playlist.py).
    '''
    return f'/shuttles/{shuttle_run}.demo.json'


def autostart(tt, button_held: bool, path: str = ConfigPath, fallback_path: str = None):
    '''
        Build the DemoRunner for this board (always returned, so it is
        available as tt.demo) and start it if the config's "enabled"
        flag and the boot button say so: the button inverts "enabled".

        The playlist comes from /demo.json; if that has nothing for this
        shuttle (no section for it and no "*" section), the shuttle's
        curated playlist is used instead.
    '''
    run = tt.shuttle.run
    conf = load_config(path)
    # the default time per project always comes from /demo.json (or the
    # built-in default): the shuttle playlist only lists projects
    entries, duration_ms = select_playlist(conf, run)
    source = path
    if not len(entries):
        if fallback_path is None:
            fallback_path = shuttle_playlist_path(run)
        entries, _ = select_playlist(load_config(fallback_path), run)
        if len(entries):
            source = fallback_path
            log.info(f'Demo: using the shuttle playlist {fallback_path}')
    runner = DemoRunner(tt, entries, duration_ms)
    if config_enabled(conf) != bool(button_held):
        if not len(runner.playlist):
            log.warn(f'Demo: requested but there is no playlist for "{run}" ({source})')
        else:
            runner.start()
    elif button_held:
        log.info('Demo: reset button held, skipping the demo for this boot')
    return runner


class KeyPlayer:
    '''
        Plays an entry's "keys" steps, looping: "set" steps are applied
        at once, "wait_ms" steps arm a one-shot timer.
    '''

    def __init__(self, tt, base: int, keys: dict, timer_class=Timer, sleep_ms=None):
        self._tt = tt
        # the ui_in value the entry set up; for "gamepad" its pins other
        # than ui[4..6] are kept, and it is restored when we stop
        self.base = base
        self.via = keys['via']
        self.steps = keys['steps']
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
        self.value = None    # last value set

    @property
    def running(self) -> bool:
        return self._active

    def start(self):
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
        if self._active:
            self._active = False
            if self.via == 'ui':
                self._tt.ui_in.value = self.base
            else:
                self._send_gamepad(0)

    def _set(self, v: int):
        self.value = v
        if self.via == 'ui':
            self._tt.ui_in.value = v
        else:
            self._send_gamepad(v)

    def _send_gamepad(self, report: int):
        # same waveform as the VGA playground's Gamepad Pmod emulation:
        # 24 bits, LSB first (the lower 12 are a second, absent controller),
        # data changed while the clock is low, then one latch pulse
        port = self._tt.ui_in
        idle = self.base & ~GamepadPins
        data_reg = report << 12
        for i in range(24):
            v = idle | (GamepadDataBit if (data_reg >> i) & 1 else 0)
            port.value = v
            port.value = v | GamepadClockBit
        port.value = idle
        port.value = idle | GamepadLatchBit
        port.value = idle

    def _run(self):
        # run steps until one waits; the steps always wait for some time
        # in total (parse_keys checks), so this terminates.  A wait step is
        # only passed once its timer has fired, so a pass (and reset_every)
        # completes at the end of the last wait, not its start.
        while self._active:
            kind, v = self.steps[self._step]
            if kind == 'set':
                self._set(v)
            elif v > 0 and not self._waiting:
                self._waiting = True
                self._timer.init(period=v, mode=self._timer_class.ONE_SHOT,
                                 callback=self._on_timer)
                return
            self._waiting = False
            self._advance()

    def _advance(self):
        self._step += 1
        if self._step < len(self.steps):
            return
        # out of steps: start over from the same reset state
        self._step = 0
        self.passes += 1
        self._tt.reset_project(True)
        self._sleep_ms(2)
        self._tt.reset_project(False)
        self._tt.ui_in.value = self.base

    def _on_timer(self, _timer):
        try:
            self._run()
        except Exception as e:
            log.error(f'Demo: keys error: {e}')


class DemoRunner:
    '''
        Cycles through a playlist on a one-shot machine.Timer that is
        re-armed after every switch, so each entry can have its own
        duration.  Available as tt.demo.
    '''

    def __init__(self, tt, entries: list, default_duration_ms=DefaultDurationMs,
                 timer_class=Timer, sleep_ms=None):
        self._tt = tt
        self._shuttle = tt.shuttle
        self.default_duration_ms = default_duration_ms
        self._timer_class = timer_class
        self._sleep_ms = sleep_ms
        self._timer = None
        self._index = -1
        self._active = False
        self._orig_callback = None
        self._player = None
        # True while we enable a project, so our design-enabled hook
        # can tell our switches apart from manual ones
        self.switching = False
        self.playlist = []
        for e in entries:
            if self._available(e):
                self.playlist.append(e)
            else:
                log.warn(f'Demo: project {entry_key(e)} is not on this shuttle, skipping')

    def _available(self, entry: dict) -> bool:
        try:
            return self._shuttle.get(entry_key(entry)) is not None
        except Exception:
            return False

    @property
    def running(self) -> bool:
        return self._active

    @property
    def current(self):
        if self._index < 0 or not len(self.playlist):
            return None
        return self.playlist[self._index]

    def start(self) -> bool:
        '''
            Start the demo with the first project.  Returns True if it is
            running.
        '''
        if self._active:
            return True
        if not len(self.playlist):
            log.warn('Demo: nothing to show for this shuttle')
            return False
        if self._timer is None:
            self._timer = self._timer_class()
        self._install_hook()
        self._active = True
        self._index = -1
        if self._advance() is None:
            log.error('Demo: no project in the playlist could be enabled')
            self.stop()
            return False
        log.info(f'Demo: started, {len(self.playlist)} project(s)')
        self._arm()
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
        '''
            Switch to the next project now (restarting its timer if the
            demo is running).
        '''
        if self._advance() is not None and self._active:
            self._arm()

    def _advance(self):
        n = len(self.playlist)
        for _attempt in range(n):
            self._index = (self._index + 1) % n
            entry = self.playlist[self._index]
            try:
                if self._show(entry):
                    return entry
                log.warn(f'Demo: could not enable project {entry_key(entry)}, skipping')
            except Exception as e:
                log.error(f'Demo: error showing project {entry_key(entry)}: {e}')
        return None

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
        if 'clock_hz' in entry:
            tt.clock_project_PWM(entry['clock_hz'])
        if 'uio_oe_pico' in entry:
            tt.uio_oe_pico.value = entry['uio_oe_pico']
        if 'uio_in' in entry:
            tt.uio_in.value = entry['uio_in']
        if 'ui_in' in entry:
            tt.ui_in.value = entry['ui_in']
        if 'keys' in entry:
            base = entry['ui_in'] if 'ui_in' in entry else tt.ui_in.value
            self._player = KeyPlayer(tt, base, entry['keys'], self._timer_class,
                                     self._sleep_ms)
            self._player.start()
        return True

    def _stop_player(self):
        if self._player is not None:
            self._player.stop()
            self._player = None

    def _arm(self):
        if len(self.playlist) < 2:
            return
        ms = self.current.get('duration_ms', self.default_duration_ms)
        self._timer.init(period=ms, mode=self._timer_class.ONE_SHOT,
                         callback=self._on_timer)

    def _on_timer(self, _timer):
        # never let an exception escape a timer callback
        try:
            if not self._active:
                return
            if self._advance() is None:
                log.error('Demo: no project could be enabled, stopping')
                self.stop()
                return
            self._arm()
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
        state = 'running' if self._active else 'stopped'
        keys = ', '.join(str(entry_key(e)) for e in self.playlist)
        return f'<DemoRunner {state}, {len(self.playlist)} projects: {keys}>'
