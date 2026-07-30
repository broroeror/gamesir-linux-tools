#!/usr/bin/env python3
"""
Macro proof: write a "type text" macro to a free sector, point a button at it,
and feel it fire — steps 2-4 of the macro engine, gated and reversible.
==============================================================================
  sudo systemctl stop ratbagd
  sudo python3 vendors/logitech/macro_test.py                       # dry-run
  sudo python3 vendors/logitech/macro_test.py --keep                # write + test
  sudo python3 vendors/logitech/macro_test.py --undo                # remove it again

Defaults: macro = type "hi", written as a FULL-sector image (macro + 0xFF fill,
NO CRC) into the first ERASED macro sector (6..15), pointed at button #10 on the
ACTIVE profile at --offset (default 0; G HUB uses 0x74). WRITE_END returns the
expected err 0x04 (a soft CRC check) but the bytes commit anyway — we swallow that
0x04 and PROVE the write by reading the sector back. After --keep, press button
#10 — it should type "hi". Safety: writes the macro sector ONLY if it's currently
empty (all 0xFF); backs up the macro + profile sectors first; read-back-verifies
every write; restores on failure.
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402
import macros       # noqa: E402
import remap        # noqa: E402  (BACKUP_DIR / diff_offsets)

import glob


def save_backup(dev, size, sectors):
    os.makedirs(remap.BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = os.path.join(remap.BACKUP_DIR, f'g502x_macrotest_{stamp}.txt')
    lines = [f'# G502 X macro-test backup {stamp} (sector <hex> <enabled> <bytes>)']
    for sec in sectors:
        lines.append(f'{sec:04x} 0 {dev.read_sector(sec, size).hex()}')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def do_undo(dev, size):
    files = sorted(glob.glob(os.path.join(remap.BACKUP_DIR, 'g502x_macrotest_*.txt')))
    if not files:
        print('no macro-test backup found to undo.'); return 1
    path = files[-1]
    print(f'== undo from {path} ==')
    # Parse entries. KEY: the device validates the sector CRC on write (WRITE_END
    # rejects an invalid CRC with err 0x04), so an all-0xFF "empty" sector CANNOT
    # be written back. We don't need to — restoring the PROFILE removes the macro
    # pointer, and an orphaned macro sector is harmless (nothing points at it; a
    # sector-ERASE op (TODO) would reclaim it). Restore valid-CRC sectors; leave empty ones.
    def valid_crc(d):
        return len(d) >= 2 and onboard.crc16_ccitt(d[:-2]) == int.from_bytes(d[-2:], 'big')

    entries = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        p = line.split()
        entries.append((int(p[0], 16), bytes.fromhex(p[2])))
    entries.sort(key=lambda e: 0 if valid_crc(e[1]) else 1)   # profiles (valid CRC) first

    ok = True
    for sec, data in entries:
        if len(data) != size:
            print(f'  0x{sec:04x}: size mismatch — skip'); ok = False; continue
        if not valid_crc(data):
            print(f'  0x{sec:04x}: was empty (0xFF) — left as an orphaned macro (harmless; '
                  f'nothing points at it; a sector-ERASE op (TODO) would reclaim it)')
            continue
        try:
            dev.write_sector(sec, data)
            good = (dev.read_sector(sec, size) == data)
        except Exception as e:
            print(f'  0x{sec:04x}: ** restore failed: {e} **'); ok = False; continue
        ok = ok and good
        print(f'  0x{sec:04x}: {"restored" if good else "** MISMATCH **"}')
    if ok:
        print('undo complete — button restored (macro pointer removed).')
        return 0
    print(f'** UNDO INCOMPLETE — see above. Backup: {path}')
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--button', type=int, default=10)
    ap.add_argument('--text', default='hi')
    ap.add_argument('--offset', type=lambda x: int(x, 0), default=0,
                    help='byte offset of the macro within its sector (G HUB uses 0x74; default 0)')
    ap.add_argument('--profile', default=None, help='profile sector (hex/dec); default ACTIVE')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--undo', action='store_true')
    args = ap.parse_args()

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (wire it; stop ratbagd; run as root).'); return 1

    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        headers = dev.profile_headers()
        size = info['sector_size']

        if args.undo:
            return do_undo(dev, size)

        prof_sector = active if args.profile is None else int(args.profile, 0)
        if prof_sector not in {s for s, _ in headers}:      # must be a REAL profile
            print(f'--profile 0x{prof_sector:04x} is not a real profile sector '
                  f'{[f"0x{s:04x}" for s, _ in headers]} — aborting.'); return 1
        if not (0 <= args.button < info['button_count']):
            print(f'button {args.button} out of range (0..{info["button_count"]-1})'); return 1

        # Find the first ERASED (all-0xFF) sector in the free/macro region (6..15).
        # Flash programs only 1->0, so a fresh macro can only be WRITTEN into already-
        # erased space — we can't overwrite an existing macro without a sector erase.
        macro_sector = None
        for s in range(6, info['sector_count']):
            if all(b == 0xFF for b in dev.read_sector(s, size)):
                macro_sector = s
                break
        if macro_sector is None:
            print('no empty macro sector free in 6..15 — orphaned test macros have filled it '
                  '(a sector ERASE op is a TODO). Nothing free to write to.'); return 1

        try:
            body = macros.type_text(args.text)
        except ValueError as e:
            print(f'error: {e}'); return 2
        if args.offset < 0 or args.offset + len(body) > size:
            print(f'macro ({len(body)} bytes) at offset 0x{args.offset:02x} does not fit '
                  f'in one {size}-byte sector.'); return 1
        # FULL-sector image: macro at args.offset, 0xFF fill, NO CRC — G HUB's
        # macro-sector format. write_full_sector_no_crc swallows the expected err
        # 0x04 at WRITE_END (the bytes commit anyway).
        image = macros.to_sector(body, size, crc=False, offset=args.offset)

        raw = dev.read_sector(prof_sector, size)
        prof = onboard.OnboardProfile.decode(raw, sector=prof_sector)
        if not prof.crc_ok:
            print('profile CRC not OK on read — aborting.'); return 1
        before = prof.buttons[args.button]
        prof.set_button(args.button, onboard.Button.macro_ptr(macro_sector, args.offset))
        new_prof = prof.to_bytes()

        prof_offs = remap.diff_offsets(raw, new_prof)
        bslice = 32 + args.button * 4
        expected = set(range(bslice, bslice + 4)) | {size - 2, size - 1}
        safe = (onboard.OnboardProfile.decode(new_prof).crc_ok
                and set(prof_offs).issubset(expected)
                and onboard.OnboardProfile.decode(raw).to_bytes() == raw
                and macro_sector < info['sector_count']
                and prof_sector < info['sector_count'])

        print('== planned macro ==')
        print(f'  macro        : "{args.text}"  ->  {macros.describe(body)}  ({len(body)} bytes)')
        print(f'  macro sector : 0x{macro_sector:04x}  @offset 0x{args.offset:02x}  '
              f'(empty; FULL-sector image, NO CRC, WRITE_END 0x04 swallowed — like G HUB)')
        print(f'  button #{args.button}   : {before.kind} "{before.detail}"  ->  macro pointer '
              f'[00 {macro_sector & 0xFF:02x} {(args.offset >> 8) & 0xFF:02x} {args.offset & 0xFF:02x}]')
        print(f'  profile      : sector 0x{prof_sector:04x}' + ('  (ACTIVE)' if prof_sector == active else ''))
        print(f'  profile bytes changed: {prof_offs}')
        print(f'  safety gate  : profile_minimal={set(prof_offs).issubset(expected)} '
              f'=> {"SAFE" if safe else "NOT SAFE"}')

        if not args.keep:
            print('\nDRY-RUN — nothing written. Add --keep to apply, or --undo to remove a prior one.')
            return 0
        if not safe:
            print('\nABORT: safety invariants failed.')
            return 1

        path = save_backup(dev, size, [macro_sector, prof_sector])
        print(f'\n  backed up macro+profile sectors -> {path}')
        print(f'== APPLYING ==')
        try:
            # macro: FULL-sector image (macro + 0xFF fill, NO CRC) into the erased
            # sector, exactly how G HUB stores macros. WRITE_END returns err 0x04
            # (a soft CRC check) but the firmware commits the bytes anyway;
            # write_full_sector_no_crc swallows that one 0x04. We PROVE the commit by
            # reading the WHOLE sector back and comparing to the image — this is the
            # read-back the old code skipped by letting the 0x04 raise.
            dev.write_full_sector_no_crc(macro_sector, image)
            readback = dev.read_sector(macro_sector, size)
            if readback != image:
                raise RuntimeError(
                    'macro sector read-back mismatch — bytes did NOT commit '
                    f'(got {readback[:16].hex()} ... want {image[:16].hex()} ...)')
            dev.write_sector(prof_sector, new_prof)
            if dev.read_sector(prof_sector, size) != new_prof:
                raise RuntimeError('profile read-back mismatch')
        except Exception as e:
            print(f'  ** error: {e} — restoring from backup')
            return do_undo(dev, size)

        print('  DONE — macro bytes CONFIRMED in flash (read-back matched). Now TEST it:')
        print(f'    Press button #{args.button} — it should type "{args.text}".')
        print(f'    If nothing happens, the offset may matter — retry at G HUB\'s 0x74:')
        print(f'      sudo python3 vendors/logitech/macro_test.py --undo')
        print(f'      sudo python3 vendors/logitech/macro_test.py --keep --offset 0x74')
        print(f'  Undo: sudo python3 vendors/logitech/macro_test.py --undo')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
