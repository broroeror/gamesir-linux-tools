#!/usr/bin/env python3
"""
Read-only dump of every onboard sector — for inspecting what G HUB actually
writes, especially MACROS (which our reader-derived spec can't fully pin down).
Nothing here writes to the device.

Workflow to crack the macro format:
  1. sudo systemctl stop ratbagd
  2. sudo python3 vendors/logitech/dump_sectors.py > before.txt   # baseline
  3. In G HUB (Windows): assign a simple 1-key macro (e.g. type "a") to a button,
     and save it to the mouse's ONBOARD memory.
  4. Back on Linux: sudo python3 vendors/logitech/dump_sectors.py > after.txt
  5. diff before.txt after.txt  -> shows which sector got the macro, its exact
     bytes, and how the button now points at it. That's the ground truth.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402
import macros       # noqa: E402


def classify(data):
    if all(b == 0xFF for b in data):
        return 'empty (all 0xFF)'
    if len(data) >= 2 and onboard.crc16_ccitt(data[:-2]) == int.from_bytes(data[-2:], 'big'):
        p = onboard.OnboardProfile.decode(data)
        n = sum(1 for b in p.buttons if b.kind != 'unset')
        return f'valid-CRC sector (looks like a PROFILE: {p.report_rate_hz}Hz, {n} buttons set)'
    return 'DATA, no valid profile CRC (possible MACRO / other)'


def hexdump(data):
    for off in range(0, len(data), 16):
        row = data[off:off + 16]
        print(f'    {off:3d} 0x{off:02x}: {row.hex(" ")}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sector', default=None, help='dump ONE sector as a full hexdump (hex/dec)')
    ap.add_argument('--offset', default='0', help='also walk a macro starting at this offset (with --sector)')
    args = ap.parse_args()

    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found (wire it; stop ratbagd; run as root).')
        return 1
    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        size = info['sector_size']

        if args.sector is not None:                 # focused single-sector dump
            sec = int(args.sector, 0)
            off = int(args.offset, 0)
            data = dev.read_sector(sec, size)
            print(f'sector 0x{sec:04x} ({size} bytes):')
            hexdump(data)
            print(f'\n  walk from offset 0    : {macros.describe(data)}')
            print(f'  walk from offset 0x{off:02x} : {macros.describe(data[off:])}')
            return 0
        print(f'device: sector_size={size} sector_count={info["sector_count"]} '
              f'active=0x{active:04x} macro_format=0x{info["macro_format"]:02x}')

        # show the active profile's buttons — highlights any MACRO pointers G HUB set
        try:
            raw = dev.read_sector(active, size)
            prof = onboard.OnboardProfile.decode(raw)
            print(f'\nactive profile 0x{active:04x} buttons:')
            for i, b in enumerate(prof.buttons):
                if b.kind != 'unset':
                    extra = (f'  -> macro@sector 0x{b.macro_sector:04x} off 0x{b.macro_address:04x}'
                             if b.kind == 'macro' else '')
                    print(f'  #{i:<2} {b.kind:<13} {b.detail}{extra}')
        except Exception as e:
            print(f'(could not read active profile: {e})')

        print('\nall sectors:')
        for sec in range(info['sector_count']):
            try:
                data = dev.read_sector(sec, size)
            except Exception as e:
                print(f'  sector 0x{sec:04x}: read error ({e})')
                continue
            cls = classify(data)
            print(f'  sector 0x{sec:04x}: {cls}')
            if 'DATA' in cls:                       # a possible macro — show it
                print(f'    first 48 bytes: {data[:48].hex()}')
                print(f'    as macro     : {macros.describe(data)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
