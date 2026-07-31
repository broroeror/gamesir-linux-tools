#!/usr/bin/env python3
"""
Assign an onboard MACRO to a G502 X button — the real macro tool.
================================================================
Builds a macro with the macros.py engine, writes it into a free onboard sector
(the proven full-sector no-CRC write: WRITE_END returns a soft err 0x04 but the
bytes commit — we swallow it and read the sector back to confirm), and points a
button at it. Dry-run by default; --keep to persist. Same safety model as
remap.py: back up every profile first, gate on a minimal-diff profile change,
read-back-verify each write, restore the profile on any failure.

Examples (run wired, ratbagd stopped):
    sudo systemctl stop ratbagd
    sudo python3 vendors/logitech/macro.py --button 10 --type "gg ez"        # dry-run
    sudo python3 vendors/logitech/macro.py --button 10 --type "gg ez" --keep
    sudo python3 vendors/logitech/macro.py --button 10 --combo "ctrl+shift+esc" --keep
    sudo python3 vendors/logitech/macro.py --button 10 \
        --sequence "ctrl+c | wait:300 | ctrl+v" --keep
    sudo python3 vendors/logitech/macro.py --button 10 --clear --keep         # remove it

Macro spec (exactly one):
    --type TEXT        type a string (auto-shift for CAPS and symbols)
    --combo COMBO      one shortcut, e.g. ctrl+shift+c  /  alt+f4  /  enter
    --sequence STEPS   '|'-separated steps: ctrl+c | wait:300 | type:hello |
                       click:1 | key:enter  (bare tokens are combos/keys)
    --clear            remove the macro binding (button -> disabled)

v1 scope: one macro per ERASED sector (6..15), single sector (no cross-sector
JUMP chaining yet), and reassigning/clearing a button leaves the old macro as a
harmless orphan (a sector-ERASE/compaction op to reclaim it is a TODO).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402
import macros       # noqa: E402
from macros import Macro   # noqa: E402
import remap        # noqa: E402  (BACKUP_DIR / backup_all / diff_offsets)


def build_from_sequence(spec):
    """Parse a '|'-separated step list into a macro body."""
    m = Macro()
    steps = 0
    for raw in spec.split('|'):
        step = raw.strip()
        if not step:
            continue
        low = step.lower()
        if low.startswith('type:'):
            m.type(step[len('type:'):])
        elif low.startswith('wait:') or low.startswith('delay:'):
            m.pause(int(step.split(':', 1)[1]))
        elif low.startswith('click:'):
            m.click(int(step.split(':', 1)[1]))
        elif low.startswith('key:'):
            m.tap_name(step.split(':', 1)[1].strip())
        else:
            m.combo(step)                       # 'ctrl+c', 'enter', 'f5', 'a'
        steps += 1
    if steps == 0:
        raise ValueError('empty --sequence')
    return m.build()


def build_macro(args):
    """Return the macro body bytes, or None for --clear. Raises ValueError."""
    chosen = [args.type is not None, args.combo is not None,
              args.sequence is not None, args.clear]
    if sum(bool(c) for c in chosen) != 1:
        raise ValueError('give exactly one of --type / --combo / --sequence / --clear')
    if args.clear:
        return None
    if args.type is not None:
        body = Macro().type(args.type).build()
    elif args.combo is not None:
        body = Macro().combo(args.combo).build()
    else:
        body = build_from_sequence(args.sequence)
    if len(body) <= 1:                          # only END = nothing to do
        raise ValueError('macro is empty')
    return body


def find_free_macro_sector(dev, info, size, headers):
    """First ERASED (all-0xFF) sector in the free/macro region that is NOT a
    directory-listed profile sector (nor the directory itself). Returns the sector
    id, or None if none is free. Skipping listed sectors makes 'never overwrite a
    profile' STRUCTURAL, not just a consequence of a live profile never reading as
    all-0xFF."""
    listed = {s for s, _ in headers} | {0x0000}
    for s in range(info['profile_count'] + 1, info['sector_count']):
        if s in listed:
            continue
        if all(b == 0xFF for b in dev.read_sector(s, size)):
            return s
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--button', type=int, required=True, help='profile button index (0..N-1)')
    ap.add_argument('--type', default=None, help='type a string')
    ap.add_argument('--combo', default=None, help='one shortcut, e.g. ctrl+shift+c')
    ap.add_argument('--sequence', default=None, help="'|'-separated steps (see --help)")
    ap.add_argument('--clear', action='store_true', help='remove the macro (button -> disabled)')
    ap.add_argument('--profile', default=None, help='profile sector (hex/dec); default ACTIVE')
    ap.add_argument('--offset', type=lambda x: int(x, 0), default=0,
                    help='advanced: macro byte offset within its sector (default 0)')
    ap.add_argument('--keep', action='store_true', help='persist (default: dry-run)')
    args = ap.parse_args()

    try:
        body = build_macro(args)                # None for --clear
    except ValueError as e:
        print(f'error: {e}'); return 2

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (connect by wire; stop ratbagd; run as root).'); return 1

    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        headers = dev.profile_headers()
        size = info['sector_size']

        prof_sector = active if args.profile is None else int(args.profile, 0)
        hdr = next((h for h in headers if h[0] == prof_sector), None)
        if hdr is None:
            print(f'--profile 0x{prof_sector:04x} not in directory '
                  f'{[f"0x{s:04x}" for s, _ in headers]} — aborting.'); return 1
        if not (0 <= args.button < info['button_count']):
            print(f'button {args.button} out of range (0..{info["button_count"]-1})'); return 1

        # allocate a macro sector (assign only; --clear needs none)
        macro_sector = None
        if body is not None:
            if args.offset < 0 or args.offset + len(body) > size:
                print(f'macro is {len(body)} bytes at offset 0x{args.offset:02x} — does not fit '
                      f'in one {size}-byte sector (multi-sector chaining is a TODO).'); return 1
            macro_sector = find_free_macro_sector(dev, info, size, headers)
            if macro_sector is None:
                print(f'no free (erased) macro sector in {info["profile_count"]+1}..'
                      f'{info["sector_count"]-1} — clear some macros (a sector-ERASE op to reclaim '
                      f'orphans is a TODO).'); return 1
            image = macros.to_sector(body, size, crc=False, offset=args.offset)

        raw = dev.read_sector(prof_sector, size)
        prof = onboard.OnboardProfile.decode(raw, sector=prof_sector, enabled=hdr[1])
        if not prof.crc_ok:
            print(f'sector 0x{prof_sector:04x} CRC not OK on read — aborting.'); return 1

        before = prof.buttons[args.button]
        if body is None:
            new_binding = onboard.Button.disabled()
        else:
            new_binding = onboard.Button.macro_ptr(macro_sector, args.offset)
        prof.set_button(args.button, new_binding)
        new_prof = prof.to_bytes()

        offs = remap.diff_offsets(raw, new_prof)
        bslice = 32 + args.button * 4
        expected = set(range(bslice, bslice + 4)) | {size - 2, size - 1}
        safe = (onboard.OnboardProfile.decode(new_prof).crc_ok
                and set(offs).issubset(expected)
                and onboard.OnboardProfile.decode(raw).to_bytes() == raw
                and prof_sector < info['sector_count']
                and (macro_sector is None or macro_sector < info['sector_count']))

        print('== plan ==')
        if body is None:
            print(f'  action     : CLEAR macro on button #{args.button}')
        else:
            print(f'  macro      : {macros.describe(body)}  ({len(body)} bytes)')
            print(f'  -> sector  : 0x{macro_sector:04x} @0x{args.offset:02x}  (erased; full-sector, NO CRC)')
        print(f'  button #{args.button}  : {before.kind} "{before.detail}"  ->  '
              f'{new_binding.kind} "{new_binding.detail}"')
        print(f'  profile    : sector 0x{prof_sector:04x}' + ('  (ACTIVE)' if prof_sector == active else ''))
        print(f'  bytes changed: {offs}   safety gate: {"SAFE" if safe else "NOT SAFE"}')
        if before.kind == 'macro' and body is not None:
            print(f'  note       : button was already a macro (@0x{before.macro_sector:04x}); the old '
                  f'macro is orphaned (harmless).')
        print('  all buttons:')
        for i, b in enumerate(onboard.OnboardProfile.decode(raw).buttons):
            mark = '  <-- changing' if i == args.button else ''
            print(f'    #{i:<2} {b.kind:<13} {b.detail}{mark}')

        if not args.keep:
            print('\nDRY-RUN — nothing written. Add --keep to apply.'); return 0
        if not safe:
            print('\nABORT: safety invariants failed — not writing.'); return 1

        print('\n== backup =='); path = remap.backup_all(dev, info, headers)
        print(f'  saved all {len(headers)} profile sectors -> {path}')
        print('== APPLYING ==')
        try:
            if body is not None:
                # full-sector no-CRC macro image; write_full_sector_no_crc swallows the
                # expected WRITE_END 0x04; read the whole sector back to prove the commit.
                dev.write_full_sector_no_crc(macro_sector, image)
                if dev.read_sector(macro_sector, size) != image:
                    raise RuntimeError('macro sector read-back mismatch — bytes did NOT commit')
            dev.write_sector(prof_sector, new_prof)
            back = dev.read_sector(prof_sector, size)
            if back != new_prof:
                raise RuntimeError(f'profile read-back mismatch @ {remap.diff_offsets(new_prof, back)[:5]}')
        except Exception as e:
            print(f'  ** error: {e} — restoring profile from in-memory original')
            try:
                dev.write_sector(prof_sector, raw)
                print('  profile restored (macro pointer removed).')
            except Exception as e2:
                print(f'  ** RESTORE FAILED: {e2} — restore from {path} (line "{prof_sector:04x} ")')
            return 1

        rb = onboard.OnboardProfile.decode(back).buttons[args.button]
        print(f'  DONE. Button #{args.button} is now {rb.kind} "{rb.detail}".')
        if body is not None:
            print(f'    Press button #{args.button} — it should run: {macros.describe(body)}')
            print(f'  Undo: sudo python3 vendors/logitech/macro.py --button {args.button} --clear --keep')
            print(f'    (or restore the exact prior binding: python3 vendors/logitech/restore.py --file {path} --commit)')
        else:
            print(f'  The button\'s previous binding was "{before.detail}" — recover it from the backup:')
            print(f'    python3 vendors/logitech/restore.py --file {path} --commit')
        if prof_sector == active:
            print('  (Active profile — takes effect live; if not, switch profile & back or replug.)')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
