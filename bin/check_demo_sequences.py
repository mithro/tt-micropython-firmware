'''
Check the demo sequences bundled with the firmware (demos/<shuttle>.demo.json)
against the shuttle indexes, with the same validation the board runs, so a
bad sequence fails the build instead of a demo board at a booth.

usage: check_demo_sequences.py DEMOS_DIR SHUTTLE_INDEX_DIR

SHUTTLE_INDEX_DIR holds <shuttle>.json files as fetched by the release
build (fields address, subtile_addr, danger_level, type, macro).

@author: Tim 'mithro' Ansell
'''
import json
import os
import sys

from ttboard.demo import load
from ttboard.project_design import DangerLevel

SUFFIX = '.demo.json'


class IndexShuttle:
    '''Looks projects up the way the board's project mux does.'''

    def __init__(self, index: dict):
        self.projects = {}
        for p in index.get('projects', []):
            if p.get('type') == 'group':
                continue   # groups can't be enabled
            address = int(p['address'])
            subtile = int(p.get('subtile_addr', 0))
            key = f'{address}-{subtile}' if subtile else address
            self.projects[key] = p

    def get(self, key):
        if key not in self.projects:
            raise AttributeError(f'Unknown project ({key})')
        p = self.projects[key]

        class Design:
            name = p['macro']
            danger_level = DangerLevel.string_to_level(p['danger_level']) \
                if 'danger_level' in p else DangerLevel.SAFE
        return Design()


def check(demos_dir: str, index_dir: str) -> list:
    '''Returns a list of "file: problem" strings, empty if all is well.'''
    problems = []
    names = sorted(f for f in os.listdir(demos_dir) if f.endswith(SUFFIX))
    for name in names:
        shuttle_id = name[:-len(SUFFIX)]
        path = os.path.join(demos_dir, name)
        index_path = os.path.join(index_dir, f'{shuttle_id}.json')
        if not os.path.exists(index_path):
            problems.append(f'{name}: no shuttle index {index_path} (shuttle not in the release?)')
            continue
        with open(index_path) as fh:
            shuttle = IndexShuttle(json.load(fh))
        _entries, errors = load(path, shuttle_id, shuttle)
        problems.extend(f'{name}: {e}' for e in errors)
    return problems


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    demos_dir, index_dir = argv
    problems = check(demos_dir, index_dir)
    n = len([f for f in os.listdir(demos_dir) if f.endswith(SUFFIX)])
    for p in problems:
        print(f'ERROR {p}')
    print(f'{n} demo sequence(s) checked, {len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
