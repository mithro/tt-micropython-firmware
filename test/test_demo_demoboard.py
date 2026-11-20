'''
Desktop integration test: DemoRunner driving a real DemoBoard and
project mux (stub pins), loaded from a shuttle JSON serialized to .bin
the way the release build does, and a demo.json.

All projects use clock_hz 0: off-target there is no PWM, so
DemoBoard.clock_project_PWM can't run (the clock_hz override itself is
covered by test_demo_runner.py).

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
]


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

    def _demo(conf, held=False):
        p = tmp_path / 'demo.json'
        p.write_text(json.dumps(conf))
        return demo.autostart(tt, held, str(p))
    return tt, _demo


def playlist(*projects, **kw):
    return dict({'shuttles': {'ttfake': {'projects': list(projects)}}}, **kw)


def test_demo_cycles_real_projects(board):
    tt, start_demo = board
    run = start_demo(playlist('tt_um_vga_a', 'tt_um_vga_b'), held=True)
    assert run.running
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'
    run._timer.callback(run._timer)
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    # config.ini section still applied through the wrapped callback
    assert tt.ui_in.value == 0x21
    assert run.running
    run.stop()


def test_demo_override_on_top_of_config_ini(board):
    tt, start_demo = board
    run = start_demo(playlist('tt_um_vga_a', {'macro': 'tt_um_vga_b', 'ui_in': 0x42}),
                     held=True)
    run.next()
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    assert tt.ui_in.value == 0x42
    run.stop()


def test_dangerous_project_skipped(board):
    tt, start_demo = board
    run = start_demo(playlist('tt_um_risky', 'tt_um_vga_b'), held=True)
    assert run.running
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    run.stop()


def test_address_entries(board):
    tt, start_demo = board
    run = start_demo(playlist({'address': '3'}, {'address': '5-2'}), held=True)
    assert len(run.playlist) == 2
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    run.next()
    assert tt.shuttle.enabled.name == 'tt_um_sub'
    run.stop()


def test_manual_enable_stops_demo_and_keeps_config(board):
    tt, start_demo = board
    run = start_demo(playlist('tt_um_vga_a', 'tt_um_vga_a'), held=True)
    assert run.running
    tt.shuttle.tt_um_vga_b.enable()
    assert not run.running
    # the original callback (config.ini handling) is back in place
    assert tt.shuttle.design_enabled_callback == tt.apply_user_config
    assert tt.ui_in.value == 0x21


def test_not_started_leaves_default_project(board):
    tt, start_demo = board
    run = start_demo(playlist('tt_um_vga_a', 'tt_um_vga_b'), held=False)
    assert not run.running
    assert tt.shuttle.enabled.name == 'tt_um_factory_test'
