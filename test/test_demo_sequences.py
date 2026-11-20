'''
Tests for bin/check_demo_sequences.py, and a check of every sequence
actually bundled in demos/ (structure only: the release build checks the
addresses against the live shuttle indexes).

Run with:
    PYTHONPATH=src:microcotb/src pytest test/test_demo_sequences.py
'''
import importlib.util
import json
from pathlib import Path

import pytest

from ttboard import demo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'check_demo_sequences', ROOT / 'bin' / 'check_demo_sequences.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

INDEX = {'projects': [
    {'macro': 'tt_um_a', 'address': 10},
    {'macro': 'tt_um_risky', 'address': 11, 'danger_level': 'medium'},
    {'macro': 'tt_um_group', 'address': 12, 'type': 'group'},
    {'macro': 'tt_um_sub', 'address': 12, 'type': 'subtile', 'subtile_addr': 1,
     'subtile_addr_bits': 2},
]}


def entry(address, subtile=0):
    return {'address': address, 'subtile': subtile, 'duration_ms': 1000,
            'clock_hz': 0, 'ui_in': 0, 'steps': []}


@pytest.fixture
def dirs(tmp_path):
    demos = tmp_path / 'demos'
    indexes = tmp_path / 'shuttles'
    demos.mkdir()
    indexes.mkdir()
    (indexes / 'tt09.json').write_text(json.dumps(INDEX))

    def write(name, *entries, shuttle='tt09'):
        (demos / name).write_text(json.dumps(
            {'version': 1, 'shuttle': shuttle, 'projects': list(entries)}))
    return str(demos), str(indexes), write


def test_good_sequence(dirs):
    demos, indexes, write = dirs
    write('tt09.demo.json', entry(10), entry(12, 1))
    assert checker.check(demos, indexes) == []
    assert checker.main([demos, indexes]) == 0


def test_problems_reported(dirs):
    demos, indexes, write = dirs
    write('tt09.demo.json', entry(10), entry(11), entry(12), entry(99))
    assert checker.check(demos, indexes) == [
        'tt09.demo.json: project 1: project 11 (tt_um_risky) is not marked safe and would not be enabled',
        'tt09.demo.json: project 2: no project at address 12 on tt09',
        'tt09.demo.json: project 3: no project at address 99 on tt09',
    ]
    assert checker.main([demos, indexes]) == 1


def test_shuttle_field_must_match_file_name(dirs):
    demos, indexes, write = dirs
    write('tt09.demo.json', entry(10), shuttle='tt10')
    assert checker.check(demos, indexes) == [
        'tt09.demo.json: "shuttle" is "tt10" but this chip is "tt09"']


def test_shuttle_without_index(dirs):
    demos, indexes, write = dirs
    write('tt99.demo.json', entry(10), shuttle='tt99')
    problems = checker.check(demos, indexes)
    assert len(problems) == 1 and problems[0].startswith('tt99.demo.json: no shuttle index')


def test_other_files_ignored(dirs):
    demos, indexes, write = dirs
    (Path(demos) / 'README.md').write_text('hello')
    assert checker.check(demos, indexes) == []


BUNDLED = sorted((ROOT / 'demos').glob('*.demo.json'))


@pytest.mark.parametrize('path', BUNDLED, ids=[p.name for p in BUNDLED])
def test_bundled_sequences_are_well_formed(path):
    shuttle_id = path.name[:-len('.demo.json')]
    _entries, errors = demo.load(str(path), shuttle_id)
    assert errors == []
