'''
On stock firmware ttboard is frozen, so the demo configurator installs
this module as a top-level /demo.py ("import demo").  Check the file works
under that name: no package-relative imports, nothing that needs it to
be ttboard.demo.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_toplevel.py
'''
import importlib.util
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src' / 'ttboard' / 'demo.py'


def load_as_toplevel():
    spec = importlib.util.spec_from_file_location('demo', SRC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_relative_imports():
    text = SRC.read_text()
    assert not re.search(r'^\s*from\s+\.', text, re.M)
    assert 'ttboard.demo' not in text


def test_works_as_toplevel_module(tmp_path):
    demo = load_as_toplevel()
    assert demo.__name__ == 'demo'
    seq = {'version': 1, 'shuttle': 'tt09', 'projects': [
        {'address': 1, 'subtile': 0, 'duration_ms': 1000, 'clock_hz': 0, 'ui_in': 0, 'steps': []}]}
    assert demo.validate(seq, 'tt09') == (seq['projects'], [])

    class Shuttle:
        run = 'tt09'
        design_enabled_callback = None
        enabled = None

        def get(self, key):
            shuttle = self

            class D:
                name = 'p1'
                danger_level = 0

                def enable(self, force=False):
                    shuttle.enabled = self
                    return True
            return D()

    class Port:
        value = 0

    class TT:
        shuttle = Shuttle()
        ui_in = Port()

        def clock_project_stop(self):
            pass

    p = tmp_path / 'demo.json'
    p.write_text(json.dumps(seq))
    ini = tmp_path / 'config.ini'
    ini.write_text('[DEFAULT]\ndemo = yes\n')
    run = demo.autostart(TT(), False, ini_path=str(ini), user_path=str(p),
                         shuttle_path=str(tmp_path / 'none.json'))
    assert run.running
    run.stop()
