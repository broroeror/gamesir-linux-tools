#!/usr/bin/env python3
"""
STAGE 3 — write a real BUTTON REMAP, gated and reversible.
==========================================================
Same safe pattern as write_test.py, but exercises the editing API: remap a
button on a DISABLED profile to a keyboard key, prove it lands byte-exact, then
revert. Demonstrates a headline bucket-1 feature (keyboard keys on buttons) end
to end with net-zero effect on the mouse.

  sudo systemctl stop ratbagd
  sudo python3 vendors/logitech/remap_test.py            # dry-run (no writes)
  sudo python3 vendors/logitech/remap_test.py --commit   # write remap + verify + revert

The change here is button #10 -> keyboard 'a' (HID usage 0x04). Send-key encoding
([0x80,0x02,mods,key]) is standard HID++ (matches Solaar); the revert makes it
safe to try even though this unit's factory profiles use no keyboard bindings.
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

TARGET_BUTTON = 10                     # which button index to remap
NEW_BINDING = onboard.Button.key(0x04)  # -> keyboard 'a'


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
        size = info['sector_size']

        print('== backup ==')
        path = backup_all(dev, info, headers)
        print(f'  saved all {len(headers)} sectors -> {path}')

        target = next(((s, e) for s, e in reversed(headers) if s != active and not e), None)
        if target is None:
            print('No safe (disabled, non-active) profile to test on — aborting.')
            return 1
        sector, enabled = target

        raw = dev.read_sector(sector, size)
        prof = onboard.OnboardProfile.decode(raw, sector=sector, enabled=enabled)
        if not prof.crc_ok:
            print(f'Target sector 0x{sector:04x} CRC not OK on read — aborting.')
            return 1

        before = prof.buttons[TARGET_BUTTON]
        prof.set_button(TARGET_BUTTON, NEW_BINDING)
        new_bytes = prof.to_bytes()

        # --- pre-write safety invariants ---
        chk = onboard.OnboardProfile.decode(new_bytes)
        offs = diff_offsets(raw, new_bytes)
        bslice = 32 + TARGET_BUTTON * 4
        expected = set(range(bslice, bslice + 4)) | {size - 2, size - 1}
        minimal_ok = set(offs).issubset(expected)
        roundtrip_ok = (onboard.OnboardProfile.decode(raw).to_bytes() == raw)
        writable_ok = sector < info['sector_count']
        safe = chk.crc_ok and minimal_ok and roundtrip_ok and writable_ok

        print()
        print('== planned change (dry-run) ==')
        print(f'  target      : sector 0x{sector:04x} (disabled; active is 0x{active:04x})')
        print(f'  button #{TARGET_BUTTON}   : {before.kind} "{before.detail}"  ->  '
              f'{NEW_BINDING.kind} "{NEW_BINDING.detail}"')
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

        print()
        print(f'== COMMIT ==  (remapping button #{TARGET_BUTTON} on DISABLED sector 0x{sector:04x}; reverts)')
        ok_write = ok_revert = False
        try:
            wrote = dev.write_sector(sector, new_bytes)
            back = dev.read_sector(sector, size)
            ok_write = (back == new_bytes)
            print(f'  wrote={wrote}  read-back == intended: {ok_write}'
                  + ('' if ok_write else f'  ** MISMATCH @ {diff_offsets(new_bytes, back)[:5]} **'))
            if ok_write:
                rb = onboard.OnboardProfile.decode(back)
                print(f'  verified on device: button #{TARGET_BUTTON} is now '
                      f'{rb.buttons[TARGET_BUTTON].kind} "{rb.buttons[TARGET_BUTTON].detail}"')
        except Exception as e:
            print(f'  ** WRITE/verify raised: {e}')
        finally:
            print('== REVERT ==')
            try:
                dev.write_sector(sector, raw)
                back2 = dev.read_sector(sector, size)
                ok_revert = (back2 == raw)
                print(f'  read-back == original: {ok_revert}'
                      + ('' if ok_revert else f'  ** MISMATCH @ {diff_offsets(raw, back2)[:5]} **'))
            except Exception as e:
                print(f'  ** REVERT FAILED: {e}')
                print(f'  ** RESTORE MANUALLY from the backup: {path} (line "{sector:04x} ")')

        print()
        if ok_write and ok_revert:
            print('REMAP WRITE VERIFIED: wrote a real keyboard remap, confirmed it landed on the '
                  'device, reverted it, confirmed byte-identical to before. Net effect: ZERO.')
            return 0
        print(f'INCOMPLETE — see above. If the profile looks wrong, restore from {path}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
