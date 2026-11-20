'''
Tests for the shuttle's curated demo playlist: built from the shuttle
index's "demo" field by bin/extract_demo_playlist.py, used on the board
when /demo.json has nothing for the detected shuttle.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_index_playlist.py
'''
import importlib.util
import json
from pathlib import Path

from ttboard import demo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'extract_demo_playlist', ROOT / 'bin' / 'extract_demo_playlist.py')
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

KEYS = {'via': 'ui', 'steps': [{'set': 1}, {'wait_ms': 100}]}

INDEX = {
    'id': 'tt09',
    'projects': [
        {'macro': 'tt_um_plain', 'address': 10},
        {'macro': 'tt_um_vga_a', 'address': 20, 'demo': {}},
        {'macro': 'tt_um_wokwi_123', 'address': 30,
         'demo': {'duration_ms': 30000, 'clock_hz': 25175000}},
        {'macro': 'tt_um_sub', 'address': 40, 'type': 'subtile',
         'subtile_addr': 2, 'subtile_addr_bits': 2, 'demo': {'ui_in': 1, 'keys': KEYS}},
    ],
}

EXPECTED_PROJECTS = [
    {'address': 20, 'subtile': 0},
    {'address': 30, 'subtile': 0, 'duration_ms': 30000, 'clock_hz': 25175000},
    {'address': 40, 'subtile': 2, 'ui_in': 1, 'keys': KEYS},
]


def test_playlist_from_index():
    assert extract.playlist_from_index(INDEX) == {
        'version': 1, 'shuttles': {'tt09': {'projects': EXPECTED_PROJECTS}}}


def test_no_demo_projects():
    assert extract.playlist_from_index({'id': 'x', 'projects': [{'macro': 'a', 'address': 1}]}) is None


def test_main_writes_file_next_to_index(tmp_path):
    src = tmp_path / 'tt09.json'
    src.write_text(json.dumps(INDEX))
    assert extract.main([str(src)]) == 0
    out = json.loads((tmp_path / 'tt09.demo.json').read_text())
    assert out == extract.playlist_from_index(INDEX)


def test_main_no_demo_writes_nothing(tmp_path):
    src = tmp_path / 'tt10.json'
    src.write_text(json.dumps({'id': 'tt10', 'projects': []}))
    assert extract.main([str(src)]) == 0
    assert not (tmp_path / 'tt10.demo.json').exists()


def test_generated_file_parses_on_board_side(tmp_path):
    p = tmp_path / 'tt09.demo.json'
    p.write_text(json.dumps(extract.playlist_from_index(INDEX)))
    entries, ms = demo.select_playlist(demo.load_config(str(p)), 'tt09')
    assert [(e['address'], e['subtile']) for e in entries] == [(20, 0), (30, 0), (40, 2)]
    assert entries[1]['duration_ms'] == 30000
    assert entries[2]['keys'] == demo.parse_keys(KEYS)
    assert ms == 15000


# --- board side: fallback to /shuttles/<run>.demo.json ---------------------

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
            name = n

            def enable(self, force=False):
                shuttle.enabled = self
                return True
        return D()


class FakeTT:
    def __init__(self):
        self.shuttle = FakeShuttle([1, 20, 30])


def write(path, conf):
    path.write_text(json.dumps(conf))
    return str(path)


def curated(tmp_path):
    return write(tmp_path / 'tt09.demo.json', {'shuttles': {'tt09': {'projects': [
        {'address': 20, 'subtile': 0}, {'address': 30, 'subtile': 0, 'duration_ms': 30000}]}}})


USER_ENTRY = {'address': 1, 'subtile': 0}


def test_fallback_used_without_user_config(tmp_path):
    run = demo.autostart(FakeTT(), True, str(tmp_path / 'missing.json'),
                         fallback_path=curated(tmp_path))
    assert run.running
    assert [e['address'] for e in run.playlist] == [20, 30]
    run.stop()


def test_user_shuttle_section_wins(tmp_path):
    user = write(tmp_path / 'demo.json', {'shuttles': {'tt09': {'projects': [USER_ENTRY]}}})
    run = demo.autostart(FakeTT(), True, user, fallback_path=curated(tmp_path))
    assert [e['address'] for e in run.playlist] == [1]
    run.stop()


def test_user_wildcard_wins(tmp_path):
    user = write(tmp_path / 'demo.json', {'shuttles': {'*': {'projects': [USER_ENTRY]}}})
    run = demo.autostart(FakeTT(), True, user, fallback_path=curated(tmp_path))
    assert [e['address'] for e in run.playlist] == [1]
    run.stop()


def test_fallback_uses_user_duration_and_enabled(tmp_path):
    user = write(tmp_path / 'demo.json', {'enabled': True, 'duration_ms': 7000,
                                          'shuttles': {'tt10': {'projects': [USER_ENTRY]}}})
    run = demo.autostart(FakeTT(), False, user, fallback_path=curated(tmp_path))
    assert run.running                    # "enabled" still comes from /demo.json
    assert run.default_duration_ms == 7000  # and so does the default time
    run.stop()


def test_no_fallback_file(tmp_path):
    run = demo.autostart(FakeTT(), True, str(tmp_path / 'missing.json'),
                         fallback_path=str(tmp_path / 'also-missing.json'))
    assert not run.running
    assert run.playlist == []
