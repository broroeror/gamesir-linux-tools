#!/usr/bin/env python3
"""
GameSir Super Nova - configuration probe, backup and verified writes
====================================================================
The bring-up tool for the Super Nova, ahead of it being configurable in the
app. Talks to the pad's HID config channel directly (see
vendors/gamesir/models/supernova/); nothing else in Deadband touches it yet.

    python3 supernova_tool.py find                  where is it, which identity
    python3 supernova_tool.py info                  device type, firmware
    python3 supernova_tool.py backup FILE           every setting -> JSON
    python3 supernova_tool.py diff FILE             pad now vs a backup
    python3 supernova_tool.py restore FILE --yes    write a backup back
    python3 supernova_tool.py set vibration --left 50
    python3 supernova_tool.py set remap A B         make A act as B
    python3 supernova_tool.py set trigger-deadzone RT 10
    python3 supernova_tool.py set stick-deadzone L 10

Every `set` first saves a timestamped backup next to the tool and prints the
command that restores it. Writes are read-modify-write, read back and compared
before saving; any mismatch puts the original back and saves nothing.
`--dry-run` reads the pad and prints what would be written without writing.
`-v` logs every frame. Run with access to /dev/hidraw* (the GameSir udev rule
covers it).
"""

import argparse
import json
import os
import sys
import time

from vendors.gamesir.models.supernova import config as nova
from vendors.gamesir.models.supernova import protocol as sn
from vendors.gamesir.models.supernova import transport

HERE = os.path.dirname(os.path.abspath(__file__))

# Xbox names for the face buttons; everything else uses GameSir's own names.
BUTTON_ALIASES = {'A': 'CRO', 'B': 'CIR', 'X': 'SQU', 'Y': 'TRI',
                  'LB': 'L1', 'LT': 'L2', 'LS': 'L3', 'RB': 'R1', 'RT': 'R2',
                  'RS': 'R3', 'VIEW': 'Sel', 'MENU': 'Sta', 'DPAD_LEFT': 'Left',
                  'DPAD_RIGHT': 'Right', 'DPAD_UP': 'Up', 'DPAD_DOWN': 'Under'}


def button(name):
    key = BUTTON_ALIASES.get(name.upper(), name)
    for k, code in sn.KEYS.items():
        if k.lower() == key.lower():
            return code
    raise SystemExit(f'unknown button {name!r}; known: '
                     + ', '.join(sorted(BUTTON_ALIASES) + sorted(sn.KEYS)))


def side(name, left, right):
    n = name.upper()
    if n in left:
        return 0
    if n in right:
        return 1
    raise SystemExit(f'expected one of {left + right}, got {name!r}')


def open_link(args):
    nodes = transport.find_nodes()
    if args.node:
        node = args.node
    elif len(nodes) == 1:
        node = nodes[0][0]
    elif not nodes:
        raise SystemExit('No Super Nova config channel found (3537:103e / 100e with '
                         'a 0xffa0 HID collection). Is the dongle plugged in and the '
                         'pad switched on? `python3 doctor.py` shows what is there.')
    else:
        raise SystemExit('Several found; pick one with --node: '
                         + ', '.join(n for n, _ in nodes))
    log = (lambda s: print('   ' + s, file=sys.stderr)) if args.verbose else None
    try:
        return transport.SuperNovaLink(node, log)
    except PermissionError:
        raise SystemExit(f'Permission denied on {node}. Install 70-gamesir.rules '
                         '(see README) and replug the dongle.')


class DryRunLink:
    """Passes reads through; prints writes instead of sending them."""

    def __init__(self, link):
        self.link = link

    def request(self, name, payload=b''):
        if name.startswith('get_'):
            return self.link.request(name, payload)
        frame = sn.encode_request(*sn.COMMANDS[name], payload)
        print(f'   [dry run] would send {name}: {frame.hex(" ")}')
        raise SystemExit('dry run: stopping before the first write')


def write_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write('\n')


def cmd_find(args):
    nodes = transport.find_nodes()
    if not nodes:
        print('none found')
    for node, pid in nodes:
        print(f'{node}  3537:{pid:04x}  ({sn.identity_name(pid)})')


def cmd_info(args):
    with open_link(args) as link:
        body = link.request('get_device_info')
        kind = sn.device_type_from_info(body)
        print(f'device type   {kind}' + ('  (Super Nova)' if kind == sn.DEVICE_TYPE_ID
                                         else '  (NOT a Super Nova)'))
        version = link.request('get_version', bytes((0x02,)))
        print(f'device info   {body.hex(" ")}')
        pct, charging = sn.battery_from_info(body)
        print('battery       ' + ('charging' if charging else
                                  f'{pct} %' if pct is not None else 'unknown'))
        print(f'version (02)  {version.hex(" ")}')


def cmd_backup(args):
    with open_link(args) as link:
        snap = nova.snapshot(link)
    snap['saved'] = time.strftime('%Y-%m-%d %H:%M:%S')
    write_json(args.file, snap)
    print(f'{len(snap["blocks"])} blocks saved to {args.file}')


def cmd_diff(args):
    with open(args.file) as f:
        backup = json.load(f)
    with open_link(args) as link:
        now = nova.snapshot(link)
    changes = nova.diff(backup, now)
    if not changes:
        print('identical: the pad matches the backup exactly')
        return
    for key, (was, cur) in changes.items():
        print(f'{key}\n   backup {was}\n   now    {cur}')
    sys.exit(1)


def cmd_restore(args):
    with open(args.file) as f:
        backup = json.load(f)
    with open_link(args) as link:
        current = nova.snapshot(link)
        writes, skipped = nova.restore_plan(current, backup)
        for block, data in writes:
            print(f'write {block.key}: {data.hex(" ")}')
        for key in skipped:
            print(f'cannot restore {key} (write layout unconfirmed)')
        if not writes:
            print('nothing to write')
            return
        if not args.yes:
            print('dry run; add --yes to write these blocks')
            return
        written, skipped, remaining = nova.restore(link, backup)
    print(f'wrote {len(written)} block(s) and saved')
    if remaining:
        print('still different: ' + ', '.join(remaining))
        sys.exit(1)
    print('verified: the pad matches the backup exactly')


def apply_one(args, describe, change):
    """Back up, then read-modify-write-verify-save one block."""
    with open_link(args) as raw:
        link = DryRunLink(raw) if args.dry_run else raw
        snap = nova.snapshot(raw)
        path = os.path.join(HERE, time.strftime('supernova-backup-%Y%m%d-%H%M%S.json'))
        if not args.dry_run:
            snap['saved'] = time.strftime('%Y-%m-%d %H:%M:%S')
            write_json(path, snap)
            print(f'backup saved: {path}')
        block, new = change(raw)
        old = nova.read_block(raw, block)
        print(f'{describe}\n   {block.key}\n   was {old.hex(" ")}\n   new {new.hex(" ")}')
        nova.write_block(link, block, new)
        nova.save(link)
    print('written, read back identical, saved.')
    print(f'to undo:  python3 supernova_tool.py restore {path} --yes')


def cmd_set(args):
    what = args.what
    if what == 'vibration':
        def change(link):
            block = nova.BLOCKS['vibrate_param']
            data = bytearray(nova.read_block(link, block))
            if args.left is not None:
                data[sn.VIB_LEFT] = args.left
            if args.right is not None:
                data[sn.VIB_RIGHT] = args.right
            return block, bytes(data)
        if args.left is None and args.right is None:
            raise SystemExit('give --left and/or --right (percent, 0-100)')
        for v in (args.left, args.right):
            if v is not None and not 0 <= v <= 100:
                raise SystemExit('vibration is a percentage, 0-100')
        apply_one(args, f'vibration left={args.left} right={args.right}', change)
    elif what == 'remap':
        if len(args.values) != 2:
            raise SystemExit('usage: set remap SOURCE TARGET   (e.g. set remap A B)')
        src, dst = button(args.values[0]), button(args.values[1])

        def change(link):
            block = nova.BLOCKS[f'key_mapping/00/{src:02x}']
            return block, sn.with_key_target(nova.read_block(link, block), dst)
        apply_one(args, f'remap {args.values[0]} -> {args.values[1]}', change)
    elif what in ('trigger-deadzone', 'stick-deadzone'):
        if len(args.values) != 2:
            raise SystemExit(f'usage: set {what} SIDE PERCENT')
        if what == 'trigger-deadzone':
            n = side(args.values[0], ['LT', 'L'], ['RT', 'R'])
            key, points = f'trigger_param/{n:02x}', sn.TRIG_POINTS
        else:
            n = side(args.values[0], ['L', 'LS', 'LEFT'], ['R', 'RS', 'RIGHT'])
            key, points = f'stick_curve/{n:02x}/00', sn.STICK_POINTS
        dz = int(args.values[1])

        def change(link):
            block = nova.BLOCKS[key]
            return block, sn.with_begin_deadzone(nova.read_block(link, block), points, dz)
        apply_one(args, f'{what} {args.values[0]} -> {dz}', change)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--node', help='hidraw node (default: auto-detect)')
    ap.add_argument('-v', '--verbose', action='store_true', help='log every frame')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('find').set_defaults(fn=cmd_find)
    sub.add_parser('info').set_defaults(fn=cmd_info)
    for name, fn in (('backup', cmd_backup), ('diff', cmd_diff)):
        p = sub.add_parser(name)
        p.add_argument('file')
        p.set_defaults(fn=fn)
    p = sub.add_parser('restore')
    p.add_argument('file')
    p.add_argument('--yes', action='store_true', help='actually write')
    p.set_defaults(fn=cmd_restore)
    p = sub.add_parser('set')
    p.add_argument('what', choices=('vibration', 'remap', 'trigger-deadzone',
                                    'stick-deadzone'))
    p.add_argument('values', nargs='*')
    p.add_argument('--left', type=int)
    p.add_argument('--right', type=int)
    p.add_argument('--dry-run', action='store_true',
                   help='read the pad, print what would be written, write nothing')
    p.set_defaults(fn=cmd_set)
    args = ap.parse_args()
    try:
        args.fn(args)
    except (nova.PadError, TimeoutError, ValueError) as e:
        raise SystemExit(f'stopped: {e}')


if __name__ == '__main__':
    main()
