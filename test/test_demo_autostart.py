'''
Tests for demo.autostart(): the config.ini "demo" setting, the boot
button flipping it, which sequence file is used, and failing loudly.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_autostart.py
'''
import json

import pytest

from ttboard import demo


class FakeShuttle:
    run = 'tt09'

    def __init__(self, keys):
        self.keys = keys
        self.design_enabled_callback = None
        self.enabled = None

    def get(self, n):
        if n not in self.keys:
            raise AttributeError(n)
        shuttle = self

        class D:
            name = f'p{n}'
            danger_level = 0

            def enable(self, force=False):
                shuttle.enabled = self
                return True
        return D()


class Port:
    value = 0


class FakeTT:
    def __init__(self):
        self.shuttle = FakeShuttle([1, 2, 3])
        self.ui_in = Port()

    def clock_project_PWM(self, hz):
        pass

    def clock_project_stop(self):
        pass


class FakeErrorDisplay:
    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1


def seq(*addresses, shuttle='tt09'):
    return {'version': 1, 'shuttle': shuttle, 'projects': [
        {'address': a, 'subtile': 0, 'duration_ms': 1000, 'clock_hz': 0, 'ui_in': 0, 'steps': []}
        for a in addresses]}


@pytest.fixture
def files(tmp_path):
    class Files:
        ini = tmp_path / 'config.ini'
        user = tmp_path / 'demo.json'
        builtin = tmp_path / 'tt09.demo.json'

        def start(self, held, demo_setting=None):
            if demo_setting is not None:
                self.ini.write_text(f'[DEFAULT]\ndemo = {demo_setting}\n')
            display = FakeErrorDisplay()
            run = demo.autostart(FakeTT(), held, ini_path=str(self.ini),
                                 user_path=str(self.user), shuttle_path=str(self.builtin),
                                 error_display=display)
            return run, display
    return Files()


def test_off_by_default(files):
    files.user.write_text(json.dumps(seq(1, 2)))
    run, display = files.start(False)
    assert not run.running and display.started == 0


def test_setting_turns_it_on(files):
    files.user.write_text(json.dumps(seq(1, 2)))
    run, display = files.start(False, 'yes')
    assert run.running
    assert [e['address'] for e in run.playlist] == [1, 2]


def test_button_turns_it_on(files):
    files.user.write_text(json.dumps(seq(1, 2)))
    run, _ = files.start(True)
    assert run.running


def test_button_skips_it_when_on(files):
    files.user.write_text(json.dumps(seq(1, 2)))
    run, display = files.start(True, 'yes')
    assert not run.running and display.started == 0


def test_user_file_wins_over_builtin(files):
    files.user.write_text(json.dumps(seq(1)))
    files.builtin.write_text(json.dumps(seq(2, 3)))
    run, _ = files.start(True)
    assert run.path == str(files.user)
    assert [e['address'] for e in run.playlist] == [1]


def test_builtin_used_without_user_file(files):
    files.builtin.write_text(json.dumps(seq(2, 3)))
    run, _ = files.start(True)
    assert run.running
    assert run.path == str(files.builtin)
    assert [e['address'] for e in run.playlist] == [2, 3]


def test_no_file_at_all_fails_loudly(files):
    run, display = files.start(True)
    assert not run.running
    assert display.started == 1
    assert run.errors[0].startswith('no demo sequence')


def test_invalid_user_file_fails_loudly_no_fallback(files):
    # an invalid /demo.json is an error, not a reason to use the built-in one
    files.user.write_text(json.dumps(seq(1, 99)))
    files.builtin.write_text(json.dumps(seq(2, 3)))
    run, display = files.start(True)
    assert not run.running
    assert display.started == 1
    assert run.errors == ['project 1: no project at address 99 on tt09']


def test_wrong_shuttle_fails_loudly(files):
    files.user.write_text(json.dumps(seq(1, shuttle='ttsky25a')))
    run, display = files.start(True)
    assert display.started == 1
    assert run.errors == ['"shuttle" is "ttsky25a" but this chip is "tt09"']


def test_bad_json_fails_loudly(files):
    files.user.write_text('{"version": 1,')
    run, display = files.start(True)
    assert display.started == 1
    assert run.errors[0].startswith('not valid JSON')


def test_invalid_file_ignored_when_demo_off(files):
    files.user.write_text('nonsense')
    run, display = files.start(False)
    assert display.started == 0 and run.errors == []
