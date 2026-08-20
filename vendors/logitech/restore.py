#!/usr/bin/env python3
"""
Restore G502 X onboard profiles from a backup file.
====================================================
Writes backed-up sectors back to the mouse byte-exact — the real undo behind
every tool's "restore the backup" note. Dry-run by default; --commit to apply.
Only writes sectors that actually differ (skip-if-unchanged), sanity-checks each
backup sector's CRC before trusting it, and read-back-verifies every write.

  sudo systemctl stop ratbagd
  sudo python3 vendors/logitech/restore.py                 # dry-run, newest backup
  sudo python3 vendors/logitech/restore.py --commit        # restore newest backup
  sudo python3 vendors/logitech/restore.py --file <path> --commit
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402
import remap        # noqa: E402  (reuse BACKUP_DIR / diff_offsets)


def latest_backup():
    files = sorted(f for d in remap.backup_dirs()
                   for f in glob.glob(os.path.join(d, 'g502x_profiles_*.txt')))
    return files[-1] if files else None


def parse_backup(path):
    """-> [(sector, enabled, bytes)]. Lines: '<sector_hex> <enabled> <hex>'."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f'malformed backup line: {line!r}')
            entries.append((int(parts[0], 16), int(parts[1]), bytes.fromhex(parts[2])))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=None, help='backup file (default: newest in mouse-backups/)')
    ap.add_argument('--commit', action='store_true', help='actually write (default: dry-run)')
    args = ap.parse_args()

    path = args.file or latest_backup()
    if not path or not os.path.exists(path):
        print('No backup found in ' + ' or '.join(remap.backup_dirs())
              + '. Pass --file <path>.')
        return 1
    try:
        entries = parse_backup(path)
    except ValueError as e:
        print(f'error reading backup: {e}')
        return 2
    if not entries:
        print(f'backup {path} has no profile entries.')
        return 1

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (wire it; stop ratbagd; run as root).')
        return 1

    with dev:
        info = dev.onboard_info()
        size = info['sector_size']
        print(f'== restore from {path} ==')

        plan = []
        skipped = 0        # backup sectors we refuse to restore (size / CRC / non-writable / read-fail)
        # _enabled is the directory's enabled flag; restore is CONTENT-only (the
        # directory sector 0x0000 isn't backed up), so it's not applied here.
        for sector, _enabled, data in entries:
            note = ''
            if len(data) != size:
                note = f'size {len(data)} != device {size} — SKIP'; skipped += 1
            elif not onboard.OnboardProfile.decode(data).crc_ok:
                note = 'backup CRC invalid — SKIP'; skipped += 1
            elif sector >= info['sector_count']:
                note = 'not a writable sector — SKIP'; skipped += 1
            else:
                try:
                    current = dev.read_sector(sector, size)
                except Exception as e:
                    print(f'  sector 0x{sector:04x}: read failed ({e}) — SKIP'); skipped += 1
                    continue
                # body-only compare: write_sector no-ops on a CRC-only difference,
                # so treat a CRC-only diff as 'already matches' (avoids a false
                # "INCOMPLETE" when the writer would skip it anyway).
                if current[:-2] == data[:-2]:
                    note = 'already matches — skip'
                else:
                    note = f'WOULD RESTORE ({len(remap.diff_offsets(current, data))} bytes differ)'
                    plan.append((sector, data))
            print(f'  sector 0x{sector:04x}: {note}')

        if not args.commit:
            print(f'\nDRY-RUN — nothing written. {len(plan)} sector(s) would be restored'
                  + (f', {skipped} skipped' if skipped else '') + '; add --commit to apply.')
            return 0
        if not plan:
            print('\nNothing to restore — device already matches the backup.')
            return 0

        print(f'\n== COMMIT: restoring {len(plan)} sector(s) ==')
        all_ok = True
        for sector, data in plan:
            try:
                dev.write_sector(sector, data)
                back = dev.read_sector(sector, size)
                ok = (back == data)
                all_ok = all_ok and ok
                print(f'  sector 0x{sector:04x}: {"restored OK" if ok else "** MISMATCH @ %s **" % remap.diff_offsets(data, back)[:5]}')
            except Exception as e:
                all_ok = False
                print(f'  sector 0x{sector:04x}: ** write error: {e} **')

        tail = f' ({skipped} sector(s) skipped)' if skipped else ''
        print(('\nRESTORE COMPLETE.' + tail) if all_ok
              else ('\nRESTORE INCOMPLETE — see mismatches above.' + tail))
        return 0 if all_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
