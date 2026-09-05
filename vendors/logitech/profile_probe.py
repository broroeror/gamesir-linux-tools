#!/usr/bin/env python3
"""
READ-ONLY probe of the onboard profile layout. Writes NOTHING to the mouse.

Answers two questions that can't be settled from the spec:

  1. Does reading a NON-ACTIVE profile sector actually return that profile, or
     does the device hand back whichever profile is currently active? (If the
     latter, the app can't preview a profile without switching to it first.)

  2. Where do the factory (out-of-box) profiles really live, and do they
     verify? "Reset to defaults" restores from them, and it currently reports
     that the factory profile doesn't verify.

Run:  python3 vendors/logitech/profile_probe.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402


def fingerprint(raw):
    """A short, human-comparable summary of a profile sector: if two sectors
    print the same fingerprint, they hold the same profile."""
    prof = onboard.OnboardProfile.decode(raw, sector=0)
    btns = ','.join((b.detail or b.kind)[:10] for b in prof.buttons[:4])
    return (f'crc={"ok " if prof.crc_ok else "BAD"} '
            f'name={prof.name!r:12} rate={prof.report_rate_hz}Hz '
            f'dpi={prof.resolutions[:3]} btn0-3=[{btns}]')


def main():
    dev = hidpp.find_device()
    if dev is None:
        print('mouse not found (connected? udev rule installed?)')
        return 1
    with dev:
        info = dev.onboard_info()
        active = dev.current_profile()
        print('=== onboard info ===')
        for k in ('profile_count', 'oob_count', 'sector_count', 'sector_size',
                  'button_count', 'memory_model_id', 'profile_format'):
            print(f'  {k:16} = {info[k]}')
        print(f'  active profile   = 0x{active:04x}')
        size = info['sector_size']

        print('\n=== directories (raw first 24 bytes) ===')
        for label, base in (('RAM 0x0000', hidpp.RAM_DIRECTORY),
                            ('ROM 0x0100', hidpp.ROM_DIRECTORY)):
            try:
                raw = b''.join(dev._mem_read16(info['feature_index'], base, o)
                               for o in (0, 16))
                print(f'  {label}: {raw[:24].hex(" ")}')
            except Exception as e:
                print(f'  {label}: unreadable ({e})')
        print(f'  parsed live directory : {dev.profile_headers()}')
        try:
            rom_dir = dev._directory(info['feature_index'], hidpp.ROM_DIRECTORY)
            print(f'  parsed ROM directory  : {rom_dir}')
        except Exception as e:
            print(f'  parsed ROM directory  : unreadable ({e})')

        print('\n=== live profile sectors ===')
        print('  (if these are all IDENTICAL, the device is returning the active')
        print('   profile no matter which sector is asked for)')
        for sector, enabled in dev.profile_headers():
            try:
                raw = dev.read_sector(sector, size)
                mark = ' <-- ACTIVE' if sector == active else ''
                print(f'  0x{sector:04x} en={enabled}  {fingerprint(raw)}{mark}')
            except Exception as e:
                print(f'  0x{sector:04x}: unreadable ({e})')

        print('\n=== factory (ROM) candidates ===')
        cands = []
        try:
            cands += [s for s, _ in dev._directory(info['feature_index'],
                                                   hidpp.ROM_DIRECTORY)]
        except Exception:
            pass
        # the usual convention is ROM address = RAM address | 0x0100
        cands += [s | 0x0100 for s, _ in dev.profile_headers()]
        for sector in sorted(set(cands)):
            try:
                raw = dev.read_sector(sector, size)
                if set(raw) in ({0x00}, {0xFF}):
                    print(f'  0x{sector:04x}: blank ({raw[0]:#04x} fill)')
                    continue
                print(f'  0x{sector:04x}: {fingerprint(raw)}')
            except Exception as e:
                print(f'  0x{sector:04x}: unreadable ({e})')
    print('\nNothing was written.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
