'''
Build a shuttle's curated demo playlist for the firmware.

Reads a shuttle index (SHUTTLE.json, fetched with the "demo" field) and,
if any project carries "demo" settings, writes SHUTTLE.demo.json next to
it in the /demo.json format, so ttboard.demo can use it when the board's
own /demo.json has no playlist for that shuttle.

Entries use addresses ("ADDR-SUBTILE") rather than macro names, as the
firmware renames some projects (e.g. Wokwi ones) on the board.

usage: extract_demo_playlist.py SHUTTLE.json [SHUTTLE.json ...]

@author: Tim 'mithro' Ansell
'''
import json
import os
import sys

DEMO_KEYS = ['seconds', 'clock_hz', 'ui_in', 'uio_oe_pico', 'uio_in']


def playlist_from_index(index: dict):
    '''Return the demo playlist config for an index, or None if it has none.'''
    projects = []
    for p in index.get('projects', []):
        settings = p.get('demo')
        if not isinstance(settings, dict):
            continue
        entry = {'address': f"{int(p['address'])}-{int(p.get('subtile_addr', 0))}"}
        for k in DEMO_KEYS:
            if k in settings:
                entry[k] = settings[k]
        projects.append(entry)
    if not projects:
        return None
    return {'version': 1, 'shuttles': {index['id']: {'projects': projects}}}


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        with open(path) as fh:
            index = json.load(fh)
        conf = playlist_from_index(index)
        if conf is None:
            print(f'{path}: no demo projects')
            continue
        base = path[:-len('.json')] if path.endswith('.json') else path
        out = f'{base}.demo.json'
        with open(out, 'w') as fh:
            json.dump(conf, fh, separators=(',', ':'))
        n = len(conf['shuttles'][index['id']]['projects'])
        print(f'{path}: wrote {n} demo projects to {os.path.basename(out)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
