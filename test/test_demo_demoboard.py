'''
Desktop integration test: demo mode on a real DemoBoard and project mux
(stub pins), with the shuttle serialized to .bin the way the release
build does.

All projects use clock_hz 0: off-target there is no PWM, so
DemoBoard.clock_project_PWM can't run (the clock_hz path is covered by
test_demo_runner.py).

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_demoboard.py
'''
import json

import pytest

from ttboard import demo
from ttboard.boot.demoboard_detect import DemoboardDetect
from ttboard.demoboard import DemoBoard
from ttboard.globals import Globals
from ttboard.project_mux import DesignIndex, ProjectMux

PROJECTS = [
    {'macro': 'tt_um_factory_test', 'address': 1, 'clock_hz': 0, 'title': 'f'},
    {'macro': 'tt_um_vga_a', 'address': 2, 'clock_hz': 0, 'title': 'a'},
    {'macro': 'tt_um_vga_b', 'address': 3, 'clock_hz': 0, 'title': 'b'},
    {'macro': 'tt_um_risky', 'address': 4, 'clock_hz': 0, 'title': 'r',
     'danger_level': 'medium'},
    {'macro': 'tt_um_sub', 'address': 5, 'clock_hz': 0, 'title': 's',
     'type': 'subtile', 'subtile_addr': 2, 'subtile_addr_bits': 2},
    # renamed on the board by DesignIndex._wokwi_name_cleanup
    {'macro': 'tt_um_wokwi_123456789', 'address': 6, 'clock_hz': 0,
     'title': 'My Wokwi Thing'},
]


class Led:
    def __init__(self):
        self.writes = []

    def __call__(self, v=None):
        if v is not None:
            self.writes.append(v)


@pytest.fixture
def board(tmp_path, monkeypatch):
    shuttle_json = tmp_path / 'ttfake.json'
    shuttle_json.write_text(json.dumps({'projects': PROJECTS}))
    # as bin/serialize_shuttle.py does in the release build
    DesignIndex(None, str(shuttle_json)).to_bin_file(f'{shuttle_json}.bin')
    monkeypatch.setattr(ProjectMux, 'indexfile_for_shuttle',
                        classmethod(lambda cls, name: str(shuttle_json)))
    ini = tmp_path / 'config.ini'
    ini.write_text('[DEFAULT]\n'
                   'mode = ASIC_RP_CONTROL\n'
                   'force_shuttle = ttfake\n'
                   'project = tt_um_factory_test\n'
                   '[tt_um_vga_b]\n'
                   'ui_in = 0x21\n')
    DemoBoard._DemoBoardSingleton_Instance = None
    Globals.Pins_Singleton = None
    Globals.ProjectMux_Singleton = None
    DemoboardDetect.probe()
    tt = DemoBoard(iniFile=str(ini))
    led = Led()

    def _demo(*entries, raw=None):
        p = tmp_path / 'demo.json'
        p.write_text(raw if raw is not None else json.dumps(
            {'version': 1, 'shuttle': 'ttfake', 'projects': list(entries)}))
        display = demo.ErrorDisplay(tt, led_pin=led)
        return demo.autostart(tt, True, ini_path=str(ini), user_path=str(p),
                              shuttle_path=str(tmp_path / 'none.json'),
                              error_display=display)
    return tt, _demo, led


def E(address, subtile=0, ui_in=0, steps=()):
    return dict(address=address, subtile=subtile, duration_ms=1000, clock_hz=0,
                ui_in=ui_in, steps=list(steps))


def test_demo_cycles_real_projects(board):
    tt, start_demo, _ = board
    run = start_demo(E(2), E(3, ui_in=0x42))
    assert run.running
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'
    run._timer.callback(run._timer)
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    # the entry's ui_in lands on top of the project's config.ini section
    assert tt.ui_in.value == 0x42
    run.stop()


def test_subtile_and_wokwi_by_address(board):
    tt, start_demo, _ = board
    run = start_demo(E(5, 2), E(6))
    assert tt.shuttle.enabled.name == 'tt_um_sub'
    run.next()
    # the board's name differs from the index macro; the address finds it
    assert tt.shuttle.enabled.name.startswith('wokwi_my_wokwi_thing')
    run.stop()


def test_steps_on_real_board(board):
    tt, start_demo, _ = board
    run = start_demo(E(2, ui_in=7, steps=[{'set': 5}, {'wait_ms': 40}, {'set': 6}, {'wait_ms': 60}]),
                     E(3))
    p = run._player
    assert tt.ui_in.value == 5
    p._timer.callback(p._timer)
    assert tt.ui_in.value == 6
    p._timer.callback(p._timer)          # end of pass: reset, then step 1
    assert p.passes == 1
    assert tt.ui_in.value == 5
    assert tt.rst_n() == 1                 # project left out of reset
    run.stop()


def test_unknown_address_fails_loudly(board):
    tt, start_demo, led = board
    run = start_demo(E(2), E(99))
    assert not run.running
    assert run.errors == ['project 1: no project at address 99 on ttfake']
    # error display: factory test enabled, held in reset, E blinking
    assert tt.shuttle.enabled.name == 'tt_um_factory_test'
    assert tt.rst_n() == 0
    t = run._error_display._timer
    t.callback(t)
    assert tt.ui_in.value == 0x79
    assert led.writes[-1] == 1
    run._error_display.stop()


def test_risky_project_fails_loudly(board):
    tt, start_demo, _ = board
    run = start_demo(E(4), E(3))
    assert not run.running
    assert run.errors == ['project 0: project 4 (tt_um_risky) is not marked safe '
                          'and would not be enabled']
    run._error_display.stop()


def test_manual_enable_stops_demo_and_keeps_config(board):
    tt, start_demo, _ = board
    run = start_demo(E(2), E(2))
    assert run.running
    tt.shuttle.tt_um_vga_b.enable()
    assert not run.running
    assert tt.shuttle.design_enabled_callback == tt.apply_user_config
    assert tt.ui_in.value == 0x21
