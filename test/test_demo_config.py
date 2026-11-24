'''
Tests for demo sequence validation and the config.ini "demo" setting.

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_config.py
'''
import copy
import json

import pytest

from ttboard import demo

ENTRY = {'address': 260, 'subtile': 0, 'duration_ms': 15000, 'clock_hz': 25000000,
         'ui_in': 7, 'steps': [{'set': 6}, {'wait_ms': 40}, {'set': 7}, {'wait_ms': 250}]}
SEQ = {'version': 1, 'shuttle': 'ttsky25a', 'projects': [ENTRY]}


def with_entry(**changes):
    seq = copy.deepcopy(SEQ)
    for k, v in changes.items():
        if v is DELETE:
            del seq['projects'][0][k]
        else:
            seq['projects'][0][k] = v
    return seq


DELETE = object()


def test_valid():
    entries, errors = demo.validate(SEQ, 'ttsky25a')
    assert errors == []
    assert entries == [ENTRY]


def test_empty_steps_valid():
    assert demo.validate(with_entry(steps=[]), 'ttsky25a')[1] == []


def test_clock_zero_valid():
    assert demo.validate(with_entry(clock_hz=0), 'ttsky25a')[1] == []


def test_shuttle_must_match_rom():
    _, errors = demo.validate(SEQ, 'tt09')
    assert errors == ['"shuttle" is "ttsky25a" but this chip is "tt09"']


@pytest.mark.parametrize('conf,expected', [
    ([], 'must be a JSON object'),
    ({'version': 1, 'shuttle': 'ttsky25a'}, 'missing "projects"'),
    (dict(SEQ, enabled=True), 'unknown field "enabled"'),
    (dict(SEQ, version=2), '"version" must be 1'),
    (dict(SEQ, version=True), '"version" must be 1'),
    (dict(SEQ, projects=[]), '"projects" must be a non-empty list'),
    (dict(SEQ, projects={}), '"projects" must be a non-empty list'),
])
def test_top_level_errors(conf, expected):
    _, errors = demo.validate(conf, 'ttsky25a')
    assert any(e.startswith(expected) for e in errors), errors


@pytest.mark.parametrize('field', ['address', 'subtile', 'duration_ms', 'clock_hz', 'ui_in', 'steps'])
def test_every_entry_field_required(field):
    _, errors = demo.validate(with_entry(**{field: DELETE}), 'ttsky25a')
    assert errors == [f'project 0: missing "{field}"']


@pytest.mark.parametrize('field,value', [
    ('address', -1), ('address', '260'), ('address', True), ('address', 2.0),
    ('subtile', -1), ('subtile', None),
    ('duration_ms', 0), ('duration_ms', 1.5), ('duration_ms', '15s'),
    ('clock_hz', -1), ('clock_hz', 25.175e6),
    ('ui_in', 256), ('ui_in', -1),
    ('steps', {}), ('steps', None),
])
def test_bad_entry_values(field, value):
    _, errors = demo.validate(with_entry(**{field: value}), 'ttsky25a')
    assert len(errors) == 1 and errors[0].startswith(f'project 0: "{field}"'), errors


def test_unknown_entry_field():
    _, errors = demo.validate(with_entry(keys={}), 'ttsky25a')
    assert errors == ['project 0: unknown field "keys"']


@pytest.mark.parametrize('steps,expected', [
    ([{}], 'must be an object with exactly one key'),
    ([{'set': 1, 'wait_ms': 2}], 'must be an object with exactly one key'),
    ([{'press': 1}, {'wait_ms': 1}], 'unknown step'),
    ([{'set': 256}, {'wait_ms': 1}], '"set" must be an integer 0..255'),
    ([{'set': 1}, {'wait_ms': -1}], '"wait_ms" must be an integer >= 0'),
    ([{'set': 1}, {'wait_ms': 1.5}], '"wait_ms" must be an integer >= 0'),
    ([{'set': 1}], '"steps" must wait for some time in total'),
    ([{'set': 1}, {'wait_ms': 0}], '"steps" must wait for some time in total'),
])
def test_bad_steps(steps, expected):
    _, errors = demo.validate(with_entry(steps=steps), 'ttsky25a')
    assert any(expected in e for e in errors), errors


def test_unknown_top_level_field_does_not_hide_other_errors():
    seq = copy.deepcopy(SEQ)
    seq['enabled'] = True
    seq['shuttle'] = 'tt09'
    seq['projects'].append(dict(ENTRY, ui_in=300))
    _, errors = demo.validate(seq, 'ttsky25a')
    assert errors == [
        'unknown field "enabled"',
        '"shuttle" is "tt09" but this chip is "ttsky25a"',
        'project 1: "ui_in" must be an integer 0..255, got 300',
    ]


def test_all_errors_reported():
    seq = copy.deepcopy(SEQ)
    seq['shuttle'] = 'tt09'
    seq['projects'].append(dict(ENTRY, ui_in=300))
    seq['projects'].append(dict(ENTRY, steps=[{'set': 1}]))
    _, errors = demo.validate(seq, 'ttsky25a')
    assert len(errors) == 3


class Shuttle:
    def __init__(self, designs):
        self.designs = designs

    def get(self, key):
        if key in self.designs:
            return self.designs[key]
        raise AttributeError(key)


class Design:
    def __init__(self, name, danger_level=0):
        self.name = name
        self.danger_level = danger_level


def test_projects_checked_against_chip():
    seq = copy.deepcopy(SEQ)
    seq['projects'] = [dict(ENTRY, address=1), dict(ENTRY, address=2),
                       dict(ENTRY, address=3), dict(ENTRY, address=5, subtile=2)]
    shuttle = Shuttle({1: Design('ok'), 3: Design('risky', danger_level=2),
                       '5-2': Design('sub')})
    _, errors = demo.validate(seq, 'ttsky25a', shuttle)
    assert errors == [
        'project 1: no project at address 2 on ttsky25a',
        'project 2: project 3 (risky) is not marked safe and would not be enabled',
    ]


def test_load_missing(tmp_path):
    assert demo.load(str(tmp_path / 'nope.json'), 'x') == ([], [f'cannot read {tmp_path / "nope.json"}'])


def test_load_bad_json(tmp_path):
    p = tmp_path / 'demo.json'
    p.write_text('{"version": 1,')
    entries, errors = demo.load(str(p), 'x')
    assert len(errors) == 1 and errors[0].startswith('not valid JSON')


def test_load_ok(tmp_path):
    p = tmp_path / 'demo.json'
    p.write_text(json.dumps(SEQ))
    assert demo.load(str(p), 'ttsky25a') == ([ENTRY], [])


def test_entry_key():
    assert demo.entry_key({'address': 907, 'subtile': 0}) == 907
    assert demo.entry_key({'address': 5, 'subtile': 2}) == '5-2'


@pytest.mark.parametrize('ini,expected', [
    ('[DEFAULT]\ndemo = yes\n', True),
    ('[DEFAULT]\ndemo = true\n', True),
    ('[DEFAULT]\ndemo = no\n', False),
    ('[DEFAULT]\n# demo = yes\n', False),
    ('[DEFAULT]\nproject = tt_um_x\n', False),
    ('[DEFAULT]\ndemo = 1\n', False),     # yes/no/true/false only
])
def test_demo_setting(tmp_path, ini, expected):
    p = tmp_path / 'config.ini'
    p.write_text(ini)
    assert demo.demo_setting(str(p)) is expected


def test_demo_setting_no_file(tmp_path):
    assert demo.demo_setting(str(tmp_path / 'none.ini')) is False


GAMEPAD = [{'gamepad': [{'buttons': ['start']}]}, {'wait_ms': 100}]


def test_gamepad_steps_valid():
    steps = [{'set': 0x81}, {'gamepad': []}, {'gamepad': [{'buttons': []}, {'buttons': ['b', 'r']}]},
             {'gamepad': [{'buttons': list(demo.GamepadButtons[:11])}]}, {'wait_ms': 10}]
    assert demo.validate(with_entry(ui_in=0x8f, steps=steps), 'ttsky25a')[1] == []


ORDER = 'in the order b, y, select, start, up, down, left, right, a, x, l, r'


@pytest.mark.parametrize('pad,expected', [
    ({}, '"gamepad" must be a list of 0 to 2 controllers, got {}'),
    ([{'buttons': []}] * 3, '"gamepad" must be a list of 0 to 2 controllers, got '
                            "[{'buttons': []}, {'buttons': []}, {'buttons': []}]"),
    (['a'], 'gamepad controller 1 must be an object with exactly one key, "buttons": a'),
    ([{'buttons': [], 'player': 1}], 'gamepad controller 1 must be an object with exactly one key, '
                                     "\"buttons\": {'buttons': [], 'player': 1}"),
    ([{'buttons': 'a'}], 'gamepad controller 1: "buttons" must be a list, got a'),
    ([{'buttons': []}, {'buttons': ['A']}], 'gamepad controller 2: unknown button A'),
    ([{'buttons': ['a', 'b']}], f'gamepad controller 1: "buttons" must name each button once, {ORDER}, '
                                "got ['a', 'b']"),
    ([{'buttons': ['b', 'b']}], f'gamepad controller 1: "buttons" must name each button once, {ORDER}, '
                                "got ['b', 'b']"),
    ([{'buttons': list(demo.GamepadButtons)}], 'gamepad controller 1: all 12 buttons at once '
                                               'reads as no controller'),
])
def test_bad_gamepad_steps(pad, expected):
    _, errors = demo.validate(with_entry(steps=[{'gamepad': pad}, {'wait_ms': 1}]), 'ttsky25a')
    assert errors == ['project 0 step 0: ' + expected]


def test_gamepad_pins_must_be_left_to_the_gamepad():
    _, errors = demo.validate(with_entry(ui_in=0x17, steps=[{'set': 0x40}] + GAMEPAD), 'ttsky25a')
    assert errors == [
        'project 0 step 0: "set" must keep bits 4..6 (the gamepad) clear, got 64',
        'project 0: "ui_in" must keep bits 4..6 (the gamepad) clear, got 23',
    ]
    # without a gamepad step those bits are ordinary inputs
    assert demo.validate(with_entry(ui_in=0x17, steps=[{'set': 0x40}, {'wait_ms': 1}]), 'ttsky25a')[1] == []


def test_gamepad_needs_a_clock():
    _, errors = demo.validate(with_entry(clock_hz=0, steps=GAMEPAD), 'ttsky25a')
    assert errors == ['project 0: "clock_hz" must be > 0 with "gamepad" steps: '
                      'the design reads the gamepad on its clock']
