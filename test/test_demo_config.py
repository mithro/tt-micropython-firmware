'''
Tests for /demo.json parsing and playlist selection.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_config.py
'''
import json

import pytest

from ttboard import demo


def test_load_missing_file(tmp_path):
    assert demo.load_config(str(tmp_path / 'nope.json')) is None


def test_load_invalid_json(tmp_path):
    p = tmp_path / 'demo.json'
    p.write_text('{"version": 1, ')
    assert demo.load_config(str(p)) is None


def test_load_not_an_object(tmp_path):
    p = tmp_path / 'demo.json'
    p.write_text('[1, 2]')
    assert demo.load_config(str(p)) is None


def test_load_ok(tmp_path):
    p = tmp_path / 'demo.json'
    p.write_text(json.dumps({'version': 1, 'shuttles': {}}))
    assert demo.load_config(str(p)) == {'version': 1, 'shuttles': {}}


def test_entry_minimal():
    assert demo.parse_entry({'address': 907, 'subtile': 0}) == {'address': 907, 'subtile': 0}


def test_entry_all_options():
    raw = {'address': 907, 'subtile': 2, 'duration_ms': 30000, 'clock_hz': 25175000,
           'ui_in': 1, 'uio_oe_pico': 0xff, 'uio_in': 3, 'unknown_field': 'ignored'}
    assert demo.parse_entry(raw) == {
        'address': 907, 'subtile': 2, 'duration_ms': 30000, 'clock_hz': 25175000,
        'ui_in': 1, 'uio_oe_pico': 0xff, 'uio_in': 3}


@pytest.mark.parametrize('raw', [
    'tt_um_a',                          # entries are always objects
    42,
    {},
    {'address': 907},                   # subtile is required
    {'subtile': 0},
    {'address': '907', 'subtile': 0},   # integers only
    {'address': 907, 'subtile': '0'},
    {'address': -1, 'subtile': 0},
    {'address': 907, 'subtile': -1},
    {'address': True, 'subtile': 0},
    {'macro': 'tt_um_a', 'subtile': 0},  # no other way to name a project
])
def test_entry_invalid(raw):
    assert demo.parse_entry(raw) is None


@pytest.mark.parametrize('opt,value', [
    ('duration_ms', 0), ('duration_ms', 1.5), ('duration_ms', '15s'), ('duration_ms', True),
    ('clock_hz', 0), ('clock_hz', 25.175e6),
    ('ui_in', 256), ('ui_in', -1), ('uio_in', 'x'), ('uio_oe_pico', 1.0),
])
def test_bad_option_dropped_entry_kept(opt, value):
    assert demo.parse_entry({'address': 5, 'subtile': 0, opt: value}) == {'address': 5, 'subtile': 0}


def test_entry_key():
    assert demo.entry_key({'address': 907, 'subtile': 0}) == 907
    assert demo.entry_key({'address': 5, 'subtile': 2}) == '5-2'


def test_select_shuttle_specific_over_wildcard():
    conf = {'duration_ms': 10000, 'shuttles': {
        'tt09': {'projects': [{'address': 1, 'subtile': 0}]},
        '*': {'projects': [{'address': 2, 'subtile': 0}]}}}
    entries, ms = demo.select_playlist(conf, 'tt09')
    assert [e['address'] for e in entries] == [1]
    assert ms == 10000


def test_select_wildcard_fallback():
    conf = {'shuttles': {'tt09': {'projects': [{'address': 1, 'subtile': 0}]},
                         '*': {'projects': [{'address': 2, 'subtile': 0}]}}}
    entries, ms = demo.select_playlist(conf, 'ttgf0p3')
    assert [e['address'] for e in entries] == [2]
    assert ms == demo.DefaultDurationMs == 15000


def test_select_bad_default_duration():
    entries, ms = demo.select_playlist({'duration_ms': '15s', 'shuttles': {}}, 'x')
    assert ms == 15000


def test_select_nothing_for_shuttle():
    conf = {'shuttles': {'tt09': {'projects': [{'address': 1, 'subtile': 0}]}}}
    assert demo.select_playlist(conf, 'tt10') == ([], 15000)
    assert demo.select_playlist({}, 'tt10') == ([], 15000)
    assert demo.select_playlist(None, 'tt10') == ([], 15000)


def test_select_skips_invalid_entries():
    conf = {'shuttles': {'*': {'projects': [
        {'address': 1, 'subtile': 0}, 'tt_um_x', {}, {'address': 3, 'subtile': 1}]}}}
    entries, _ = demo.select_playlist(conf, 'x')
    assert entries == [{'address': 1, 'subtile': 0}, {'address': 3, 'subtile': 1}]


def test_enabled_flag():
    assert demo.config_enabled({'enabled': True}) is True
    assert demo.config_enabled({'enabled': False}) is False
    assert demo.config_enabled({}) is False
    assert demo.config_enabled(None) is False
    assert demo.config_enabled({'enabled': 'yes'}) is False


# --- keys ---------------------------------------------------------------

CONNECT4 = {'via': 'ui', 'steps': [
    {'set': 5}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 120},
    {'set': 6}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 250}]}


def test_keys_valid():
    assert demo.parse_keys(CONNECT4) == {'via': 'ui', 'steps': [
        ('set', 5), ('wait_ms', 40), ('set', 7), ('wait_ms', 120),
        ('set', 6), ('wait_ms', 40), ('set', 7), ('wait_ms', 250)]}


def test_keys_gamepad_range():
    assert demo.parse_keys({'via': 'gamepad', 'steps': [{'set': 0xfff}, {'wait_ms': 1}]}) is not None
    assert demo.parse_keys({'via': 'gamepad', 'steps': [{'set': 0x1000}, {'wait_ms': 1}]}) is None
    assert demo.parse_keys({'via': 'ui', 'steps': [{'set': 0x100}, {'wait_ms': 1}]}) is None


@pytest.mark.parametrize('keys', [
    None, [], 'x',
    {'steps': [{'wait_ms': 10}]},                          # via required
    {'via': 'pins', 'steps': [{'wait_ms': 10}]},
    {'via': 'ui'},
    {'via': 'ui', 'steps': []},
    {'via': 'ui', 'steps': [{}]},                          # exactly one key per step
    {'via': 'ui', 'steps': [{'set': 1, 'wait_ms': 10}]},
    {'via': 'ui', 'steps': [{'press': 1}, {'wait_ms': 10}]},
    {'via': 'ui', 'steps': [{'set': -1}, {'wait_ms': 10}]},
    {'via': 'ui', 'steps': [{'set': 1}, {'wait_ms': -5}]},
    {'via': 'ui', 'steps': [{'set': 1}, {'wait_ms': 1.5}]},
    {'via': 'ui', 'steps': [{'set': 1}]},                  # never waits: would spin
    {'via': 'ui', 'steps': [{'set': 1}, {'wait_ms': 0}]},
])
def test_keys_invalid(keys):
    assert demo.parse_keys(keys) is None


def test_bad_keys_dropped_entry_kept():
    e = demo.parse_entry({'address': 260, 'subtile': 0, 'ui_in': 7,
                          'keys': {'via': 'ui', 'steps': [{'set': 1}]}})
    assert e == {'address': 260, 'subtile': 0, 'ui_in': 7}


def test_entry_with_keys():
    e = demo.parse_entry({'address': 260, 'subtile': 0, 'ui_in': 7, 'keys': CONNECT4})
    assert e['keys'] == demo.parse_keys(CONNECT4)
