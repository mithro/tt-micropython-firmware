'''
Desktop integration test: DemoBoard boot with several default projects
in config.ini.

Run with:
    PYTHONPATH=src pytest test/test_demoboard_rotation.py
'''
import json

import pytest

from ttboard.boot.demoboard_detect import DemoboardDetect
from ttboard.demoboard import DemoBoard
from ttboard.globals import Globals
from ttboard.project_mux import ProjectMux

PROJECTS = ['tt_um_factory_test', 'tt_um_vga_a', 'tt_um_vga_b', 'tt_um_vga_c']


@pytest.fixture
def boot(tmp_path, monkeypatch):
    shuttle_json = tmp_path / 'ttfake.json'
    shuttle_json.write_text(json.dumps({'projects': [
        {'macro': name, 'address': i + 1, 'clock_hz': 0, 'title': name}
        for i, name in enumerate(PROJECTS)]}))
    monkeypatch.setattr(ProjectMux, 'indexfile_for_shuttle',
                        classmethod(lambda cls, name: str(shuttle_json)))

    def _boot(default_section: str) -> DemoBoard:
        ini = tmp_path / 'config.ini'
        ini.write_text('[DEFAULT]\n'
                       'mode = ASIC_RP_CONTROL\n'
                       'force_shuttle = ttfake\n'
                       + default_section)
        # fresh singletons for every boot
        DemoBoard._DemoBoardSingleton_Instance = None
        Globals.Pins_Singleton = None
        Globals.ProjectMux_Singleton = None
        DemoboardDetect.probe()
        return DemoBoard(iniFile=str(ini))
    return _boot


def test_single_project_no_rotation(boot):
    tt = boot('project = tt_um_vga_a\n')
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'
    assert tt.project_rotation is None


def test_list_enables_first_and_rotates(boot):
    tt = boot('project = tt_um_vga_a, tt_um_vga_b, tt_um_vga_c\n'
              'switch_interval = 5\n')
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'
    rot = tt.project_rotation
    assert rot.running
    assert rot.interval_s == 5
    assert rot._timer._period == 5000
    rot._timer.callback(rot._timer)
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    # a rotation switch must not stop the rotation
    assert rot.running
    rot._timer.callback(rot._timer)
    rot._timer.callback(rot._timer)
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'


def test_default_interval(boot):
    tt = boot('project = tt_um_vga_a, tt_um_vga_b\n')
    assert tt.project_rotation.interval_s == 15


def test_unknown_names_skipped(boot):
    tt = boot('project = tt_um_nope, tt_um_vga_b, tt_um_also_nope, tt_um_vga_c\n')
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    assert tt.project_rotation.projects == ['tt_um_vga_b', 'tt_um_vga_c']


def test_only_one_known_no_rotation(boot):
    tt = boot('project = tt_um_nope, tt_um_vga_b\n')
    assert tt.shuttle.enabled.name == 'tt_um_vga_b'
    assert tt.project_rotation is None


def test_manual_enable_stops_rotation(boot):
    tt = boot('project = tt_um_vga_a, tt_um_vga_b\n')
    assert tt.project_rotation.running
    tt.shuttle.tt_um_factory_test.enable()
    assert not tt.project_rotation.running
    assert tt.shuttle.enabled.name == 'tt_um_factory_test'


def test_zero_interval_loads_first_only(boot):
    tt = boot('project = tt_um_vga_a, tt_um_vga_b\nswitch_interval = 0\n')
    assert tt.shuttle.enabled.name == 'tt_um_vga_a'
    assert not tt.project_rotation.running
