#!/usr/bin/env python3
"""Update Qt Linguist catalogs, then compile them for the shipped app."""
import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def qt_tool(name):
    for command in (f'pyside6-{name}', f'{name}6', name):
        path = shutil.which(command)
        if path:
            return path
    raise SystemExit(f'Install Qt Linguist tools ({name}) to update translations.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', action='store_true',
                        help='extract new GUI text before compiling catalogs')
    args = parser.parse_args()
    catalogs = sorted((ROOT / 'translations').glob('deadband_*.ts'))
    if args.update:
        subprocess.run([qt_tool('lupdate'), 'qml', 'i18n.py', '-no-obsolete',
                        '-locations', 'relative', '-ts', *map(str, catalogs)],
                       cwd=ROOT, check=True)
    for catalog in catalogs:
        subprocess.run([qt_tool('lrelease'), '-nounfinished', str(catalog)],
                       cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
