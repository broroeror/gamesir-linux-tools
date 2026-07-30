#!/usr/bin/env python3
"""
STAGE 2 — first real WRITE, gated and reversible.
=================================================
Proves the write path end-to-end while touching the mouse as little and as
safely as possible:

  1. BACK UP all profile sectors to a timestamped file (always, even in dry-run).
  2. Target a DISABLED profile (never the active one) and flip its report rate
     (1000<->500 Hz) — a trivial, reversible, non-active change.
  3. DRY-RUN by default: show exactly which bytes would change + the new CRC,
     and WRITE NOTHING. Re-run with --commit to actually write.
  4. With --commit: write -> read-back-verify byte-exact -> then REVERT to the
     original bytes -> read-back-verify again. Net effect on the mouse: ZERO.

This is config memory, not firmware — a bad write is recoverable (restore the
backup, or a G HUB factory reset), never a brick. Run wired, with ratbagd stopped:

    sudo systemctl stop ratbagd
    sudo python3 vendors/logitech/write_test.py            # dry-run (no writes)
    sudo python3 vendors/logitech/write_test.py --commit   # write + verify + revert
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP_DIR = os.path.join(REPO, 'mouse-backups')


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
    ap.add_argument('--commit', action='store_true',
                    help='actually write to the device (default: dry-run, no writes)')
    args = ap.parse_args()

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (connect by wire; stop ratbagd; run as root).')
        return 1

    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        headers = dev.profile_headers()

        print('== backup ==')
        path = backup_all(dev, info, headers)
        print(f'  saved all {len(headers)} sectors -> {path}')

        # Target the LAST disabled profile (never the active one).
        target = next(((s, e) for s, e in reversed(headers) if s != active and not e), None)
        if target is None:
            print('No safe (disabled, non-active) profile to test on — aborting.')
            return 1
        sector, enabled = target

        raw = dev.read_sector(sector, info['sector_size'])
        prof = onboard.OnboardProfile.decode(raw, sector=sector, enabled=enabled)
        if not prof.crc_ok:
            print(f'Target sector 0x{sector:04x} CRC not OK on read — aborting.')
            return 1

        size = info['sector_size']

        def hz(ms):                                # guarded (a blank profile could be 0)
            return round(1000 / ms) if ms else 0

        old_ms = prof.report_rate_ms
        new_ms = 2 if old_ms == 1 else 1           # nudge the rate (1000<->500 for the usual 1ms case)
        prof.report_rate_ms = new_ms
        new_bytes = prof.to_bytes()

        # --- pre-write safety invariants — ALL must hold before any --commit ---
        chk = onboard.OnboardProfile.decode(new_bytes)          # new image self-consistent?
        offs = diff_offsets(raw, new_bytes)
        expected = {0, size - 2, size - 1}                      # report-rate byte + 2 CRC bytes
        minimal_ok = set(offs).issubset(expected)               # ONLY those bytes changed?
        roundtrip_ok = (onboard.OnboardProfile.decode(raw).to_bytes() == raw)  # codec exact on THIS sector
        writable_ok = sector < info['sector_count']             # not a ROM/non-writable sector
        safe = chk.crc_ok and minimal_ok and roundtrip_ok and writable_ok

        print()
        print('== planned change (dry-run) ==')
        print(f'  target      : sector 0x{sector:04x} (disabled; active is 0x{active:04x}; '
              f'sector_count {info["sector_count"]})')
        print(f'  report rate : {hz(old_ms)} Hz -> {hz(new_ms)} Hz  (byte0 {old_ms}->{new_ms})')
        print(f'  bytes changed: {offs}   (want {sorted(expected)})')
        print(f'  safety gate : crc_ok={chk.crc_ok} minimal_diff={minimal_ok} '
              f'sector_roundtrip={roundtrip_ok} writable={writable_ok}  =>  '
              f'{"SAFE" if safe else "NOT SAFE"}')

        if not args.commit:
            print()
            print('DRY-RUN — nothing written. Re-run with --commit to apply (after go-ahead).')
            return 0

        if not safe:
            print()
            print('ABORT: pre-write safety invariants did not all pass — refusing to write.')
            return 1

        # ---- COMMIT: write, verify, and ALWAYS revert (even on error), verify ----
        # NB read-back uses a full-sector compare; read_profile proved this device
        # stores our bytes (incl. CRC) verbatim and write_count is stable, so a
        # mismatch means a real problem, not a benign normalization.
        print()
        print(f'== COMMIT ==  (writing DISABLED sector 0x{sector:04x}; reverts immediately)')
        ok_write = ok_revert = False
        try:
            wrote = dev.write_sector(sector, new_bytes)
            back = dev.read_sector(sector, size)
            ok_write = (back == new_bytes)
            print(f'  wrote={wrote}  read-back == intended: {ok_write}'
                  + ('' if ok_write else f'  ** MISMATCH @ {diff_offsets(new_bytes, back)[:5]} **'))
        except Exception as e:
            print(f'  ** WRITE/verify raised: {e}')
        finally:
            # the revert is attempted no matter what happened above
            print('== REVERT ==')
            try:
                dev.write_sector(sector, raw)
                back2 = dev.read_sector(sector, size)
                ok_revert = (back2 == raw)
                print(f'  read-back == original: {ok_revert}'
                      + ('' if ok_revert else f'  ** MISMATCH @ {diff_offsets(raw, back2)[:5]} **'))
            except Exception as e:
                print(f'  ** REVERT FAILED: {e}')
                print(f'  ** RESTORE MANUALLY from the backup: {path}')
                print(f'  ** (the line beginning "{sector:04x} " holds the original bytes)')

        print()
        if ok_write and ok_revert:
            print('WRITE PATH VERIFIED: wrote a change, confirmed it, reverted it, confirmed the '
                  'profile is byte-identical to before. Net effect: ZERO.')
            return 0
        print(f'WRITE PATH INCOMPLETE — see above. If the profile looks wrong, restore from {path}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
