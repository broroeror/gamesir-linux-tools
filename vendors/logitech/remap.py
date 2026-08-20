#!/usr/bin/env python3
"""
Remap a G502 X button — the first real, usable editing tool.
============================================================
Point it at a button and a binding; dry-run by default, --keep to persist.
Always backs up first, gates on the same safety invariants as the tests, and if
a --keep write fails mid-way it restores the original bytes (keep-on-success,
restore-on-failure). Writing the ACTIVE profile is fine — it's config flash, not
firmware, and fully reversible (restore the backup, or re-run to set it back).

Examples (run wired, ratbagd stopped):
    sudo systemctl stop ratbagd
    sudo python3 vendors/logitech/remap.py --button 10 --to key:a          # dry-run
    sudo python3 vendors/logitech/remap.py --button 10 --to key:a --keep   # apply + keep
    sudo python3 vendors/logitech/remap.py --button 10 --to sniper --keep
    sudo python3 vendors/logitech/remap.py --button 10 --to prev-dpi --keep  # undo the above

Button index is the PROFILE slot (0..N-1); the dry-run prints each button's
current binding so you can identify which physical button you're changing.
Bindings: key:<char|name>  mouse:<n>  sniper  dpi-up  dpi-down  dpi-cycle  disabled
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _xdg_backup_dir():
    base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    return os.path.join(base, 'deadband', 'mouse-backups')


def backup_dirs():
    """Every directory that may hold profile snapshots, newest-convention first.
    Readers (restore, undo) search all of them; writes go to backup_dirs()[0]."""
    repo_dir = os.path.join(REPO, 'mouse-backups')
    xdg_dir = _xdg_backup_dir()
    # A git checkout keeps snapshots beside the tree (dev workflow, and where any
    # existing ones already live). An INSTALLED app lives under /usr/share, which
    # is root-owned, so writing there fails with EACCES -- use the XDG data dir.
    if os.access(REPO, os.W_OK):
        return [repo_dir, xdg_dir]
    return [xdg_dir, repo_dir]


BACKUP_DIR = backup_dirs()[0]

# minimal HID keyboard-usage map (extend as needed)
_NAMED_KEYS = {'space': 0x2C, 'enter': 0x28, 'return': 0x28, 'esc': 0x29,
               'escape': 0x29, 'tab': 0x2B, 'backspace': 0x2A, 'delete': 0x4C}


def key_usage(name):
    name = name.lower()
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if len(name) == 1 and 'a' <= name <= 'z':
        return 0x04 + (ord(name) - ord('a'))
    if len(name) == 1 and '1' <= name <= '9':
        return 0x1E + (ord(name) - ord('1'))
    if name == '0':
        return 0x27
    if name.startswith('f') and name[1:].isdigit() and 1 <= int(name[1:]) <= 12:
        return 0x3A + (int(name[1:]) - 1)              # F1..F12
    raise ValueError(f'unknown key name: {name!r}')


# Only functions whose byte2 "param" we're confident of: the DPI family uses 0x00
# (observed for shift-dpi 0x07 and prev-dpi 0x04). tilt/profile-switch functions
# use other param values we haven't verified on-device, so they're omitted until we do.
_FUNCTIONS = {'sniper': onboard.Button.sniper,                            # shift-dpi 0x07, byte2 0x00
              'dpi-up': lambda: onboard.Button.function_(0x03, param=0x00),    # next-dpi
              'dpi-down': lambda: onboard.Button.function_(0x04, param=0x00),  # prev-dpi (observed)
              'dpi-cycle': lambda: onboard.Button.function_(0x05, param=0x00), # cycle-dpi
              'disabled': onboard.Button.disabled}


def parse_binding(spec):
    if spec.startswith('key:'):
        return onboard.Button.key(key_usage(spec[4:]))
    if spec.startswith('mouse:'):
        n = int(spec[6:])
        return onboard.Button.mouse(1 << (n - 1))
    if spec in _FUNCTIONS:
        return _FUNCTIONS[spec]()
    raise ValueError(f'unknown binding {spec!r} (try key:a / mouse:5 / sniper / '
                     'dpi-up / dpi-down / dpi-cycle / disabled)')


def backup_all(dev, info, headers):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(BACKUP_DIR, f'g502x_profiles_{stamp}.txt')
    lines = [f'# G502 X onboard-profile backup {stamp}',
             f'# sector_size={info["sector_size"]} profiles={info["profile_count"]}']
    for sector, enabled in headers:
        raw = dev.read_sector(sector, info['sector_size'])
        lines.append(f'{sector:04x} {enabled} {raw.hex()}')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def diff_offsets(a, b):
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--button', type=int, required=True, help='profile button index (0..N-1)')
    ap.add_argument('--to', required=True, help='binding, e.g. key:a  mouse:5  sniper  disabled')
    ap.add_argument('--profile', default=None,
                    help='profile sector (hex/dec); default: the ACTIVE profile')
    ap.add_argument('--keep', action='store_true',
                    help='persist the change (default: dry-run, no writes)')
    args = ap.parse_args()

    try:
        new_binding = parse_binding(args.to)
    except ValueError as e:
        print(f'error: {e}')
        return 2

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (connect by wire; stop ratbagd; run as root).')
        return 1

    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        headers = dev.profile_headers()
        size = info['sector_size']

        sector = active if args.profile is None else int(args.profile, 0)
        hdr = next((h for h in headers if h[0] == sector), None)
        if hdr is None:
            print(f'profile sector 0x{sector:04x} not in the directory {[f"0x{s:04x}" for s,_ in headers]}')
            return 1
        if not (0 <= args.button < info['button_count']):
            print(f'button index {args.button} out of range (0..{info["button_count"]-1})')
            return 1

        print('== backup =='); path = backup_all(dev, info, headers)
        print(f'  saved all {len(headers)} sectors -> {path}')

        raw = dev.read_sector(sector, size)
        prof = onboard.OnboardProfile.decode(raw, sector=sector, enabled=hdr[1])
        if not prof.crc_ok:
            print(f'sector 0x{sector:04x} CRC not OK on read — aborting.')
            return 1

        before = prof.buttons[args.button]
        prof.set_button(args.button, new_binding)
        new_bytes = prof.to_bytes()

        chk = onboard.OnboardProfile.decode(new_bytes)
        offs = diff_offsets(raw, new_bytes)
        bslice = 32 + args.button * 4
        expected = set(range(bslice, bslice + 4)) | {size - 2, size - 1}
        safe = (chk.crc_ok and set(offs).issubset(expected)
                and onboard.OnboardProfile.decode(raw).to_bytes() == raw
                and sector < info['sector_count'])

        print()
        print('== planned change ==')
        print(f'  profile     : sector 0x{sector:04x}'
              + ('  (ACTIVE)' if sector == active else '  (not active)'))
        print(f'  button #{args.button}   : {before.kind} "{before.detail}"  ->  '
              f'{new_binding.kind} "{new_binding.detail}"')
        print(f'  bytes changed: {offs}')
        print(f'  safety gate : {"SAFE" if safe else "NOT SAFE"}')
        print('  all buttons (to find the one you mean):')
        for i, b in enumerate(onboard.OnboardProfile.decode(raw).buttons):
            mark = '  <-- changing' if i == args.button else ''
            print(f'    #{i:<2} {b.kind:<13} {b.detail}{mark}')

        if not args.keep:
            print()
            print('DRY-RUN — nothing written. Add --keep to apply.')
            return 0
        if not safe:
            print('\nABORT: safety invariants failed — not writing.')
            return 1

        print()
        print(f'== APPLYING (keep) to sector 0x{sector:04x} ==')
        try:
            wrote = dev.write_sector(sector, new_bytes)
            back = dev.read_sector(sector, size)
            if back == new_bytes:
                rb = onboard.OnboardProfile.decode(back)
                print(f'  DONE (wrote={wrote}). Button #{args.button} is now '
                      f'{rb.buttons[args.button].kind} "{rb.buttons[args.button].detail}".')
                print(f'  To undo: re-run --to <original> (was: {before.kind} "{before.detail}"), '
                      f'or restore {path}.')
                if sector == active:
                    print('  If it does not take effect immediately, switch the mouse profile and '
                          'back (or replug) so the pad reloads the active profile.')
                return 0
            print(f'  ** read-back mismatch @ {diff_offsets(new_bytes, back)[:5]} — restoring original')
            dev.write_sector(sector, raw)
            return 1
        except Exception as e:
            print(f'  ** write error: {e} — restoring original')
            try:
                dev.write_sector(sector, raw)
                print('  restored.')
            except Exception as e2:
                print(f'  ** RESTORE FAILED: {e2}  — restore manually from {path} (line "{sector:04x} ")')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
