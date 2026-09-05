#!/usr/bin/env python3
"""
Offline checks for the mouse write paths — NO HARDWARE NEEDED.

These cover the code that can damage a user's stored settings: macro slot
allocation, profile renaming, which profile an edit lands in, and restoring
factory defaults. Every case here is one that actually went wrong at some
point, so they're regressions, not hypotheticals.

Run:  python3 vendors/logitech/offline_checks.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from vendors.logitech import config, onboard, remap   # noqa: E402

SIZE, NSEC, NPROF, NBTN = 255, 16, 5, 11
INFO = {'sector_size': SIZE, 'sector_count': NSEC, 'profile_count': NPROF,
        'button_count': NBTN}
HEADERS = [(s, 1) for s in range(1, 6)]
ROM_GOOD, ROM_JUNK = 0x0101, 0x0102

failures = []


def check(label, cond, detail=''):
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'  — {detail}' if detail else ''))
    if not cond:
        failures.append(label)


def make_profile(name='', rate_hz=1000):
    """A valid, fully-initialised profile. Buttons must be explicitly disabled:
    a zeroed button decodes as a MACRO pointing at sector 0, which sends the
    reference walk chasing a dangling pointer."""
    p = onboard.OnboardProfile.decode(bytes(SIZE))
    for i in range(len(p.buttons)):
        p.set_button(i, onboard.Button.disabled())
    for i in range(len(p.gbuttons)):
        p.set_gshift(i, onboard.Button.disabled())
    for i in range(onboard.N_RESOLUTIONS):
        p.set_dpi(i, 800 + i * 400)
    p.set_report_rate_hz(rate_hz)
    p.name = name
    return bytearray(p.to_bytes())


class FakeMouse:
    """Enough of the HID++ device to exercise the write paths."""

    def __init__(self):
        self.s = {s: make_profile(f'P{s}') for s in range(1, 6)}
        for i in range(NPROF + 1, NSEC):
            self.s[i] = bytearray(b'\xff' * SIZE)        # erased macro region
        rom = make_profile('', 1000)
        rom[-2:] = b'\x00\x00'      # ROM copies carry no CRC we can verify
        self.s[ROM_GOOD] = rom
        self.s[ROM_JUNK] = bytearray(b'\x5a' * SIZE)

    def read_sector(self, sec, size):
        return bytes(self.s[sec][:size])

    def write_sector(self, sec, data):
        self.s[sec] = bytearray(data)

    def write_full_sector_no_crc(self, sec, image):
        self.s[sec] = bytearray(image)

    def profile_headers(self):
        return list(HEADERS)

    def profile_name(self, sec):
        raw = bytes(self.s[sec][160:208])
        return ''.join(c for c in raw.decode('utf-16le', errors='ignore')
                       if c.isprintable()).strip()


def free(dev):
    return len(config.free_macro_sectors(dev, INFO, HEADERS))


def macro(text):
    return {'steps': [{'t': 'text', 'text': text}]}


def main():
    remap.backup_all = lambda *a, **k: os.path.join(tempfile.mkdtemp(), 'b.txt')

    print('\n== macro slots: editing one button must not leak a slot ==')
    dev = FakeMouse()
    start = free(dev)
    for body in ('alpha', 'bravo', 'charlie'):
        ok, msg = config.apply_edits(dev, INFO, HEADERS, 1,
                                     macro_changes={3: macro(body)})
        if not ok:
            check('three edits of one button', False, msg)
            break
    else:
        check('three edits of one button cost one slot', free(dev) == start - 1,
              f'{start} -> {free(dev)} free')
        live = onboard.OnboardProfile.decode(dev.read_sector(1, SIZE)).buttons[3]
        check('the button runs the LAST macro applied',
              config._macro_body_at(dev, SIZE, live.macro_sector, live.macro_address)
              == config.build_macro_body(macro('charlie')))

    print('\n== profile names ==')
    dev = FakeMouse()
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, 'FPS')
    check('rename writes the name', ok and dev.profile_name(2) == 'FPS', msg)
    check('the profile still verifies after a rename',
          onboard.OnboardProfile.decode(dev.read_sector(2, SIZE)).crc_ok)
    ok, _ = config.rename_profile(dev, INFO, HEADERS, 2, 'x' * 25)
    check('a 25-character name is rejected', not ok)
    ok, _ = config.rename_profile(dev, INFO, HEADERS, 9, 'nope')
    check('a non-profile sector is rejected', not ok)
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, '')
    check('a name can be cleared', ok and dev.profile_name(2) == '', msg)

    config.rename_profile(dev, INFO, HEADERS, 3, 'Work')
    config.apply_bindings(dev, INFO, HEADERS, 3, {0: onboard.Button.mouse(0x01)})
    config.rename_profile(dev, INFO, HEADERS, 3, 'Work 2')
    after = onboard.OnboardProfile.decode(dev.read_sector(3, SIZE))
    check('renaming leaves bindings alone',
          after.name == 'Work 2' and after.buttons[0].kind == 'send-button')

    # An unnamed profile is 0x00 or 0xFF filler; 0xFF decodes to U+FFFF, which is
    # unprintable AND non-empty, so a bad filter both draws tofu boxes and defeats
    # the caller's "Profile N" fallback.
    def clean(raw):
        return ''.join(c for c in raw.decode('utf-16le', errors='ignore')
                       if c.isprintable()).strip()
    for label, raw, want in (
            ('0xFF padding reads as unnamed', b'\xff' * 48, ''),
            ('0x00 padding reads as unnamed', b'\x00' * 48, ''),
            ('name survives 0xFF padding',
             'FPS'.encode('utf-16le') + b'\xff' * 42, 'FPS'),
            ('a full 24-char name survives',
             ('x' * 24).encode('utf-16le'), 'x' * 24)):
        check(label, clean(raw) == want, repr(clean(raw)))

    print('\n== edits land in the SELECTED profile ==')
    dev = FakeMouse()
    ok, msg = config.apply_edits(dev, INFO, HEADERS, 4, macro_changes={2: macro('hi')})
    p1 = onboard.OnboardProfile.decode(dev.read_sector(1, SIZE))
    p4 = onboard.OnboardProfile.decode(dev.read_sector(4, SIZE))
    check('the edited profile got the macro', ok and p4.buttons[2].kind == 'macro', msg)
    check('another profile was untouched', p1.buttons[2].kind == 'unset')

    print('\n== factory restore ==')
    dev = FakeMouse()
    check('the ROM copy does NOT verify (as on real hardware)',
          not onboard.OnboardProfile.decode(dev.read_sector(ROM_GOOD, SIZE)).crc_ok)
    ok, msg = config.reset_profile_to_oob(dev, INFO, HEADERS, 3, ROM_GOOD)
    check('restores from a ROM copy whose stored CRC is unverifiable', ok, msg)
    written = onboard.OnboardProfile.decode(dev.read_sector(3, SIZE))
    check('what we WROTE verifies', written.crc_ok)
    check('the restored profile has factory values',
          written.report_rate_hz == 1000 and written.resolutions[0] == 800)
    ok, msg = config.reset_profile_to_oob(dev, INFO, HEADERS, 3, ROM_GOOD)
    check('a second reset is a no-op', ok and msg == 'already at factory defaults', msg)

    live = dev.read_sector(4, SIZE)
    ok, msg = config.reset_profile_to_oob(dev, INFO, HEADERS, 4, ROM_JUNK)
    check('junk factory data is refused', not ok, msg)
    check('...and the live profile is untouched', dev.read_sector(4, SIZE) == live)

    print()
    if failures:
        print(f'FAILED ({len(failures)}): ' + '; '.join(failures))
        return 1
    print('All offline checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
