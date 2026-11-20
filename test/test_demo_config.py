'''
Tests for demo.json parsing and playlist selection.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_config.py
'''
import json

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


def test_entry_string_shorthand():
    assert demo.parse_entry('tt_um_a') == {'macro': 'tt_um_a'}


def test_entry_macro_with_options():
    raw = {'macro': 'tt_um_a', 'seconds': 30, 'clock_hz': 25175000,
           'ui_in': 1, 'uio_oe_pico': 0xff, 'uio_in': 3, 'unknown_key': 'kept'}
    e = demo.parse_entry(raw)
    assert e['macro'] == 'tt_um_a'
    assert e['seconds'] == 30
    assert e['clock_hz'] == 25175000
    assert e['ui_in'] == 1
    assert e['uio_oe_pico'] == 0xff
    assert e['uio_in'] == 3


def test_entry_address_forms():
    assert demo.parse_entry({'address': '123-2'})['address'] == '123-2'
    # plain addresses become ADDRESS-0, the form the project mux looks up
    assert demo.parse_entry({'address': '123'})['address'] == '123-0'
    assert demo.parse_entry({'address': 123})['address'] == '123-0'


def test_entry_invalid():
    assert demo.parse_entry({}) is None
    assert demo.parse_entry({'seconds': 3}) is None
    assert demo.parse_entry({'address': 'abc'}) is None
    assert demo.parse_entry(42) is None
    assert demo.parse_entry('') is None
    # bad option types drop the option, not the entry
    e = demo.parse_entry({'macro': 'tt_um_a', 'seconds': 'long', 'ui_in': 'x'})
    assert e == {'macro': 'tt_um_a'}


def test_select_shuttle_specific_over_wildcard():
    conf = {'seconds': 10, 'shuttles': {
        'tt09': {'projects': ['a', 'b']},
        '*': {'projects': ['c']}}}
    entries, seconds = demo.select_playlist(conf, 'tt09')
    assert [e['macro'] for e in entries] == ['a', 'b']
    assert seconds == 10


def test_select_wildcard_fallback_and_section_seconds():
    conf = {'shuttles': {'tt09': {'projects': ['a']},
                         '*': {'seconds': 7, 'projects': ['c', 'd']}}}
    entries, seconds = demo.select_playlist(conf, 'ttgf0p3')
    assert [e['macro'] for e in entries] == ['c', 'd']
    assert seconds == 7


def test_select_default_seconds():
    entries, seconds = demo.select_playlist({'shuttles': {'*': {'projects': ['a']}}}, 'x')
    assert seconds == demo.DefaultSeconds == 15


def test_select_nothing_for_shuttle():
    assert demo.select_playlist({'shuttles': {'tt09': {'projects': ['a']}}}, 'tt10') == ([], 15)
    assert demo.select_playlist({}, 'tt10') == ([], 15)
    assert demo.select_playlist(None, 'tt10') == ([], 15)


def test_select_skips_invalid_entries():
    conf = {'shuttles': {'*': {'projects': ['a', {}, 7, {'address': '5'}]}}}
    entries, _ = demo.select_playlist(conf, 'x')
    assert entries == [{'macro': 'a'}, {'address': '5-0'}]


def test_enabled_flag():
    assert demo.config_enabled({'enabled': True}) is True
    assert demo.config_enabled({'enabled': False}) is False
    assert demo.config_enabled({}) is False
    assert demo.config_enabled(None) is False
    assert demo.config_enabled({'enabled': 'yes'}) is False
