#!/usr/bin/env python3
"""
G-Shift proof: designate a trigger + one shift-layer binding, then feel it.
===========================================================================
G-Shift is a second button layer: while you HOLD the trigger button, every other
button uses its "shift" binding (the gbuttons bank at profile offset 96). This
sets one trigger (a primary button -> FUNCTION G_SHIFT) and one shift binding
(gbuttons[M]) so we can confirm on hardware whether it activates — and, crucially,
whether the trigger's parameter byte (which we can't observe, so are testing) is
right.

  sudo systemctl stop ratbagd
  sudo python3 vendors/logitech/gshift_test.py                       # dry-run
  sudo python3 vendors/logitech/gshift_test.py --keep                # apply + test

Defaults: trigger = button #10, shift binding = button #0 (left-click) -> key 'b'.
So after --keep: HOLD button #10 and click left — it should type 'b'. Release #10
and left-click works normally. Undo: restore the printed backup, or re-run
remap.py to reset button #10 and this tool with --to disabled on the gbutton.
Same safety model as remap.py (backup, gate, keep-on-success/restore-on-failure).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402
import remap        # noqa: E402  (reuse parse_binding / backup_all / diff_offsets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trigger', type=int, default=10, help='button to become the G-Shift trigger')
    ap.add_argument('--shift-button', type=int, default=0, help='button whose SHIFT binding we set')
    ap.add_argument('--to', default='key:b', help='shift-layer binding (default key:b)')
    ap.add_argument('--profile', default=None, help='profile sector (hex/dec); default: ACTIVE')
    ap.add_argument('--keep', action='store_true', help='persist (default: dry-run)')
    args = ap.parse_args()

    try:
        shift_binding = remap.parse_binding(args.to)
    except ValueError as e:
        print(f'error: {e}'); return 2

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (wire it; stop ratbagd; run as root).'); return 1

    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        headers = dev.profile_headers()
        size = info['sector_size']
        n_btn = info['button_count']

        sector = active if args.profile is None else int(args.profile, 0)
        hdr = next((h for h in headers if h[0] == sector), None)
        if hdr is None:
            print(f'profile 0x{sector:04x} not found'); return 1
        if not (0 <= args.trigger < n_btn and 0 <= args.shift_button < n_btn):
            print(f'button index out of range (0..{n_btn-1})'); return 1

        print('== backup =='); path = remap.backup_all(dev, info, headers)
        print(f'  saved -> {path}')

        raw = dev.read_sector(sector, size)
        prof = onboard.OnboardProfile.decode(raw, sector=sector, enabled=hdr[1])
        if not prof.crc_ok:
            print('target CRC not OK on read — aborting.'); return 1

        trig_before = prof.buttons[args.trigger]
        gshift_before = prof.gbuttons[args.shift_button]
        prof.set_button(args.trigger, onboard.Button.gshift_trigger())   # trigger (param 0xFF, TESTING)
        prof.set_gshift(args.shift_button, shift_binding)                # the shift-layer action
        new_bytes = prof.to_bytes()

        chk = onboard.OnboardProfile.decode(new_bytes)
        offs = remap.diff_offsets(raw, new_bytes)
        tslice = 32 + args.trigger * 4
        gslice = 96 + args.shift_button * 4
        expected = set(range(tslice, tslice + 4)) | set(range(gslice, gslice + 4)) | {size - 2, size - 1}
        safe = (chk.crc_ok and set(offs).issubset(expected)
                and onboard.OnboardProfile.decode(raw).to_bytes() == raw
                and sector < info['sector_count'])

        print()
        print('== planned change ==')
        print(f'  profile      : sector 0x{sector:04x}' + ('  (ACTIVE)' if sector == active else ''))
        print(f'  trigger      : button #{args.trigger}  {trig_before.kind} "{trig_before.detail}"'
              f'  ->  G-SHIFT trigger')
        print(f'  shift binding: button #{args.shift_button} (held-layer)  '
              f'{gshift_before.kind} "{gshift_before.detail}"  ->  {shift_binding.kind} "{shift_binding.detail}"')
        print(f'  bytes changed: {offs}')
        print(f'  safety gate  : {"SAFE" if safe else "NOT SAFE"}')

        if not args.keep:
            print('\nDRY-RUN — nothing written. Add --keep to apply and test.')
            return 0
        if not safe:
            print('\nABORT: safety invariants failed — not writing.'); return 1

        print(f'\n== APPLYING (keep) to sector 0x{sector:04x} ==')
        try:
            dev.write_sector(sector, new_bytes)
            back = dev.read_sector(sector, size)
            if back == new_bytes:
                print('  DONE. Now TEST it:')
                print(f'    HOLD button #{args.trigger}, then press button #{args.shift_button} '
                      f'— it should do: {shift_binding.detail}.')
                print(f'    (Release #{args.trigger}; button #{args.shift_button} works normally again.)')
                print(f'  Report back whether it fired — that tells us the trigger param byte is right.')
                print(f'  Undo: restore {path}, or reset button #{args.trigger} with remap.py.')
                return 0
            print(f'  ** read-back mismatch @ {remap.diff_offsets(new_bytes, back)[:5]} — restoring')
            dev.write_sector(sector, raw); return 1
        except Exception as e:
            print(f'  ** write error: {e} — restoring original')
            try:
                dev.write_sector(sector, raw); print('  restored.')
            except Exception as e2:
                print(f'  ** RESTORE FAILED: {e2} — restore from {path} (line "{sector:04x} ")')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
