'''
Created on Nov 20, 2026

Demo mode: cycle through a playlist of projects -- e.g. VGA designs on a
screen at a booth -- with no computer attached.

The playlist lives in /demo.json, keyed by shuttle so one file can
serve several chips:

    {
      "version": 1,
      "enabled": false,          # true: run the demo on every boot
      "seconds": 15,             # default time per project
      "shuttles": {
        "tt09": {
          "seconds": 20,         # default for this shuttle
          "projects": [
            "tt_um_vga_example",                 # just a macro name
            {"macro": "tt_um_rebeccargb_colorbars", "clock_hz": 25175000},
            {"address": "123-2", "seconds": 30, "ui_in": 0,
             "uio_oe_pico": 0, "uio_in": 0}
          ]
        },
        "*": {"projects": ["tt_um_vga_example"]}   # any other shuttle
      }
    }

Each project's own config.ini section is applied when it is enabled, as
usual; the clock_hz/ui_in/uio_oe_pico/uio_in values here are applied on
top of that.  Projects not present on the detected shuttle are skipped,
as are projects that refuse to enable (danger level).  Unknown keys are
ignored, so the file can carry extra data for other tools.

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
DefaultSeconds = 15
Wildcard = '*'

_EntryIntOpts = ['ui_in', 'uio_oe_pico', 'uio_in']


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_config(path: str = ConfigPath):
    '''
        Read the demo configuration, or None if it is missing or invalid.
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


def parse_entry(raw):
    '''
        Normalise one playlist entry to a dict with either 'macro' or
        'address' ('ADDR-SUBTILE'), plus any valid options.
        Returns None if the entry can't be used.
    '''
    if isinstance(raw, str):
        raw = {'macro': raw}
    if not isinstance(raw, dict):
        log.warn(f'Demo: ignoring playlist entry {raw}')
        return None

    entry = {}
    macro = raw.get('macro')
    address = raw.get('address')
    if isinstance(macro, str) and len(macro.strip()):
        entry['macro'] = macro.strip()
    elif address is not None and not isinstance(address, bool):
        parts = str(address).strip().split('-')
        try:
            addr = int(parts[0])
            sub = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            log.warn(f'Demo: bad address "{address}", use "ADDR" or "ADDR-SUBTILE"')
            return None
        entry['address'] = f'{addr}-{sub}'
    else:
        log.warn(f'Demo: playlist entry needs a "macro" or "address": {raw}')
        return None

    secs = raw.get('seconds')
    if secs is not None:
        if _is_number(secs) and secs > 0:
            entry['seconds'] = secs
        else:
            log.warn(f'Demo: ignoring bad seconds {secs} in {raw}')

    hz = raw.get('clock_hz')
    if hz is not None:
        if _is_number(hz) and hz > 0:
            entry['clock_hz'] = hz
        else:
            log.warn(f'Demo: ignoring bad clock_hz {hz} in {raw}')

    for opt in _EntryIntOpts:
        v = raw.get(opt)
        if v is None:
            continue
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 0xff:
            entry[opt] = v
        else:
            log.warn(f'Demo: ignoring bad {opt} {v} in {raw}')

    return entry


def select_playlist(conf, shuttle_run: str):
    '''
        Pick the playlist for this shuttle (falling back to the "*"
        section) and its default seconds per project.
        Returns (entries, seconds).
    '''
    seconds = DefaultSeconds
    if not isinstance(conf, dict):
        return ([], seconds)
    if _is_number(conf.get('seconds')) and conf['seconds'] > 0:
        seconds = conf['seconds']

    shuttles = conf.get('shuttles')
    if not isinstance(shuttles, dict):
        return ([], seconds)
    section = shuttles.get(shuttle_run)
    if section is None:
        section = shuttles.get(Wildcard)
    if not isinstance(section, dict):
        return ([], seconds)

    if _is_number(section.get('seconds')) and section['seconds'] > 0:
        seconds = section['seconds']
    raw_list = section.get('projects')
    if not isinstance(raw_list, list):
        return ([], seconds)

    entries = []
    for raw in raw_list:
        e = parse_entry(raw)
        if e is not None:
            entries.append(e)
    return (entries, seconds)


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
    entries, seconds = select_playlist(conf, run)
    source = path
    if not len(entries):
        if fallback_path is None:
            fallback_path = shuttle_playlist_path(run)
        entries, fb_seconds = select_playlist(load_config(fallback_path), run)
        if len(entries):
            source = fallback_path
            # the board's own default time per project still applies
            if not (isinstance(conf, dict) and _is_number(conf.get('seconds')) and conf['seconds'] > 0):
                seconds = fb_seconds
            log.info(f'Demo: using the shuttle playlist {fallback_path}')
    runner = DemoRunner(tt, entries, seconds)
    if config_enabled(conf) != bool(button_held):
        if not len(runner.playlist):
            log.warn(f'Demo: requested but there is no playlist for "{run}" ({source})')
        else:
            runner.start()
    elif button_held:
        log.info('Demo: reset button held, skipping the demo for this boot')
    return runner


def _entry_key(entry: dict):
    return entry['macro'] if 'macro' in entry else entry['address']


class DemoRunner:
    '''
        Cycles through a playlist on a one-shot machine.Timer that is
        re-armed after every switch, so each entry can have its own
        duration.  Available as tt.demo.
    '''

    def __init__(self, tt, entries: list, default_seconds=DefaultSeconds,
                 timer_class=Timer):
        self._tt = tt
        self._shuttle = tt.shuttle
        self.default_seconds = default_seconds
        self._timer_class = timer_class
        self._timer = None
        self._index = -1
        self._active = False
        self._orig_callback = None
        # True while we enable a project, so our design-enabled hook
        # can tell our switches apart from manual ones
        self.switching = False
        self.playlist = []
        for e in entries:
            if self._available(e):
                self.playlist.append(e)
            else:
                log.warn(f'Demo: "{_entry_key(e)}" is not on this shuttle, skipping')

    def _available(self, entry: dict) -> bool:
        if 'macro' in entry:
            return bool(self._shuttle.has(entry['macro']))
        try:
            return self._shuttle.get(entry['address']) is not None
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
                log.warn(f'Demo: could not enable "{_entry_key(entry)}", skipping')
            except Exception as e:
                log.error(f'Demo: error showing "{_entry_key(entry)}": {e}')
        return None

    def _show(self, entry: dict) -> bool:
        self.switching = True
        try:
            design = self._shuttle.get(_entry_key(entry))
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
        return True

    def _arm(self):
        if len(self.playlist) < 2:
            return
        secs = self.current.get('seconds', self.default_seconds)
        self._timer.init(period=int(secs * 1000),
                         mode=self._timer_class.ONE_SHOT,
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
        names = ', '.join(_entry_key(e) for e in self.playlist)
        return f'<DemoRunner {state}, {len(self.playlist)} projects: {names}>'
