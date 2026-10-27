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
    # config imports `remap` by its bare name, a different module object from
    # vendors.logitech.remap: patch the one config calls, or the fakes' backups
    # land in the real mouse-backups folder
    config.remap.backup_all = lambda *a, **k: os.path.join(tempfile.mkdtemp(), 'b.txt')

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

    print('\n== review 2026-10-14 (L4, L5, L7, L8, L9) ==')
    # L5: a name padded with 0xFF (Solaar's convention) must round-trip, or the
    # safety gate refuses every edit to that profile
    dev = FakeMouse()
    raw = bytearray(dev.s[3])
    raw[160:208] = 'abc'.encode('utf-16le') + b'\xff' * 42
    raw[-2:] = onboard.crc16_ccitt(bytes(raw[:-2])).to_bytes(2, 'big')
    dev.s[3] = raw
    check('a 0xFF-padded name round-trips',
          onboard.OnboardProfile.decode(bytes(raw)).to_bytes() == bytes(raw))
    ok, msg = config.apply_edits(dev, INFO, HEADERS, 3, sensor={'dpi': {0: 1600}})
    check('...so that profile can still be edited', ok, msg)
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 3, 'xyz')
    check('...and renamed, keeping its 0xFF padding',
          ok and bytes(dev.s[3][166:208]) == b'\xff' * 42, msg)
    # L8: the limit is 24 UTF-16 units; an emoji is two
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, '🎮' * 13)
    check('13 emoji (26 UTF-16 units) are refused clearly', not ok and 'at most 24' in msg, msg)
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, '🎮 Gaming 🎮')
    check('a short emoji name fits', ok and len(dev.s[2]) == SIZE, msg)
    # L9: out-of-range macro steps are refused, not silently wrapped
    for label, fn in (('scroll 200', lambda: config.macros.wheel(200)),
                      ('mouse button 17', lambda: config.macros.mouse_press(1 << 16))):
        try:
            fn()
            check(f'{label} is refused', False)
        except ValueError as e:
            check(f'{label} is refused', True, str(e))
    check('scroll -128..127 still encodes',
          config.macros.wheel(-128)[1] == 0x80 and config.macros.wheel(127)[1] == 0x7f)
    # L4: a revert that doesn't read back must not claim "reverted"
    class StuckMouse(FakeMouse):
        def write_sector(self, sec, data):
            pass                                    # nothing ever lands
    dev = StuckMouse()
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, 'New')
    check('a write that never lands is reported', not ok, msg)
    class RevertFails(FakeMouse):
        def write_sector(self, sec, data):
            self.s[sec] = bytearray(b'\x00' * len(data))   # corrupts every write
    dev = RevertFails()
    ok, msg = config.rename_profile(dev, INFO, HEADERS, 2, 'New')
    check("an unconfirmed revert doesn't say reverted",
          not ok and "couldn't be confirmed" in msg, msg)
    # L7: an unreadable macro map is named as such, not "0 free slots"
    dev = FakeMouse()
    real = config.referenced_macro_sectors
    config.referenced_macro_sectors = lambda *a: (_ for _ in ()).throw(ValueError('opcode 0x99'))
    try:
        ok, msg = config.apply_edits(dev, INFO, HEADERS, 1, macro_changes={3: macro('x')})
        check('an incomplete macro scan says so', not ok and 'in use' in msg
              and 'Free unused' not in msg, msg)
    finally:
        config.referenced_macro_sectors = real

    print('\n== #28: a mouse still on its factory (ROM) profiles ==')
    class FactoryMouse(FakeMouse):
        """Like a mouse that never met G HUB: RAM directory blank, profile slots
        erased, two factory profiles in ROM (0x0101/0x0102) that carry no CRC."""
        def __init__(self):
            super().__init__()
            self.s[0] = bytearray(b'\xff' * SIZE)
            for sec in range(1, 6):
                self.s[sec] = bytearray(b'\xff' * SIZE)
            rom2 = bytearray(self.s[ROM_GOOD]); rom2[0] = 2      # 500 Hz, like the real one
            self.s[ROM_JUNK] = rom2
            self.current = ROM_GOOD
        def _mem_read16(self, idx, sector, offset):
            return bytes(self.s[sector][offset:offset + 16])
        def get_feature_index(self, fid):
            return 10
        def oob_headers(self):
            return [(ROM_GOOD, 1), (ROM_JUNK, 1)]
        def profile_headers(self):
            d = self.s[0]
            if d[:4] in (b'\x00' * 4, b'\xff' * 4):
                return self.oob_headers()
            out, o = [], 0
            while d[o:o + 2] != b'\xff\xff':
                out.append(((d[o] << 8) | d[o + 1], d[o + 2])); o += 4
            return out
        def current_profile(self):
            return self.current
        def set_current_profile(self, sec):
            self.current = sec
            return sec
    dev = FactoryMouse()
    check('a factory-only mouse is recognised', config.factory_only(dev))
    ok, msg = config.setup_editable_profiles(dev, INFO)
    check('setup succeeds', ok, msg)
    check('the profile list now names slots 1 and 2', dev.profile_headers() == [(1, 1), (2, 1)],
          str(dev.profile_headers()))
    d = bytes(dev.s[0])
    check('the profile list has a valid CRC',
          onboard.crc16_ccitt(d[:-2]) == int.from_bytes(d[-2:], 'big'))
    check('the list is laid out like G HUB writes it',
          d[:12] == bytes.fromhex('000101000002010 0ffff0000'.replace(' ', '')))
    p1 = onboard.OnboardProfile.decode(bytes(dev.s[1])); p2 = onboard.OnboardProfile.decode(bytes(dev.s[2]))
    check('both copies verify', p1.crc_ok and p2.crc_ok)
    check('the copies keep the factory settings',
          dev.s[1][:-2] == dev.s[ROM_GOOD][:-2] and dev.s[2][0] == 2)
    check('the mouse switched to the copy of its active profile', dev.current == 1)
    check('slots 3-5 untouched', all(set(dev.s[x]) == {0xFF} for x in (3, 4, 5)))
    ok, msg = config.setup_editable_profiles(dev, INFO)
    check('running it again changes nothing', ok and 'already' in msg, msg)
    ok, msg = config.apply_edits(dev, INFO, dev.profile_headers(), 1, sensor={'dpi': {0: 1600}})
    check('...and the profile can now be edited', ok, msg)

    dev = FactoryMouse()
    dev.s[2] = bytearray(make_profile('mine'))             # something already in slot 2
    before = {k: bytes(v) for k, v in dev.s.items()}
    ok, msg = config.setup_editable_profiles(dev, INFO)
    check('a slot holding unknown data is never overwritten', not ok and 'left alone' in msg, msg)
    check('...and nothing at all was written', {k: bytes(v) for k, v in dev.s.items()} == before)

    # #28's mouse: the RAM directory isn't blank, it LISTS the ROM sectors
    dev = FactoryMouse()
    listing = bytes.fromhex('01010100' '01020100' 'ffff0000')
    dev.s[0] = bytearray(listing + b'\xff' * (SIZE - len(listing)))
    check('a profile list naming only factory sectors counts as factory-only',
          dev.profile_headers() == [(ROM_GOOD, 1), (ROM_JUNK, 1)] and config.factory_only(dev))
    ok, msg = config.setup_editable_profiles(dev, INFO)
    check('...and setup replaces it with editable slots 1 and 2',
          ok and dev.profile_headers() == [(1, 1), (2, 1)] and dev.current == 1, msg)
    dev = FactoryMouse()
    listing = bytes.fromhex('00010100' '00020100' 'ffff0000')
    dev.s[0] = bytearray(listing + b'\xff' * (SIZE - len(listing)))
    check('a mouse that lists editable slots is not factory-only', not config.factory_only(dev))

    class FailsOnList(FactoryMouse):
        def write_sector(self, sec, data):
            if sec == 0:
                raise OSError('dropped')
            super().write_sector(sec, data)
    dev = FailsOnList()
    ok, msg = config.setup_editable_profiles(dev, INFO)
    check('if the profile list fails, the mouse keeps its factory profiles',
          not ok and config.factory_only(dev) and dev.current == ROM_GOOD, msg)

    print('\n== a macro already on the mouse reads back into editable steps ==')
    mac = config.macros
    defs = [
        {'steps': [{'t': 'key', 'combo': 'ctrl+c', 'hold': 0, 'delay': 30},
                   {'t': 'key', 'combo': 'ctrl+v', 'hold': 50, 'delay': 0}]},
        {'steps': [{'t': 'text', 'text': 'Hello, World!', 'delay': 20},
                   {'t': 'key', 'combo': 'enter', 'hold': 0, 'delay': 0}]},
        {'steps': [{'t': 'click', 'button': 1, 'hold': 10, 'delay': 30},
                   {'t': 'click', 'button': 5, 'hold': 0, 'delay': 0}], 'repeat': True},
        {'steps': [{'t': 'media', 'code': 0xCD, 'delay': 0},
                   {'t': 'scroll', 'delta': -3, 'delay': 100}]},
        {'steps': [{'t': 'key', 'combo': 'shift+alt+f4', 'hold': 0, 'delay': 0},
                   {'t': 'key', 'combo': 'rctrl+num5', 'hold': 5, 'delay': 5}], 'speed': 2.0},
    ]
    for d in defs:
        body = config.build_macro_body(d)
        back = config.steps_from_ops([r for r in mac.walk(body) if r[0] != 'end'])
        check('decoded macro rebuilds byte for byte: '
              + ' · '.join(config.macro_step_label(x) for x in d['steps']),
              back is not None and config.build_macro_body(back) == body)
    for label, raw in (('overlapping keys', mac.press(4) + mac.press(5) + mac.release(4) + mac.release(5)),
                       ('a leading pause', mac.delay(10) + mac.press(4) + mac.release(4)),
                       ('a mouse move', bytes([0x61, 0, 1, 0, 1])),
                       ('two buttons at once', mac.mouse_press(3) + mac.mouse_release(3))):
        ops = [r for r in mac.walk(raw + mac.END) if r[0] != 'end']
        check(f'a macro with {label} is not shown as something else',
              config.steps_from_ops(ops) is None)

    long = {'steps': [{'t': 'text', 'text': 'The quick brown fox jumps over the lazy dog. ' * 3,
                       'delay': 10}]}
    body = config.build_macro_body(long)
    chunks = mac.split_body(body, SIZE, 4)
    secs = [7, 9, 12, 13][:len(chunks)]

    class ChainMouse:
        mem = {}

        def read_sector(self, sec, size):
            return self.mem[sec]
    for k, (sec, chunk) in enumerate(zip(secs, chunks)):
        tail = mac.jump(secs[k + 1], 0) if k + 1 < len(chunks) else b''
        ChainMouse.mem[sec] = mac.to_sector(chunk + tail, SIZE)
    ops = config.read_macro_ops(ChainMouse(), secs[0], 0, SIZE)
    back = config.steps_from_ops(ops) if ops is not None else None
    check(f'a macro chained over {len(chunks)} sectors reads back whole',
          len(chunks) > 1 and back is not None and config.build_macro_body(back) == body)
    ChainMouse.mem[15] = mac.to_sector(mac.press(4) + mac.release(4) + mac.jump(15, 0), SIZE)
    check('a chain that loops on itself is refused', config.read_macro_ops(ChainMouse(), 15, 0, SIZE) is None)

    dev = FakeMouse()
    ok, msg = config.apply_edits(dev, INFO, HEADERS, 1, macro_changes={3: macro('saved')})
    saved = config.profile_bindings(dev, 1, SIZE)['macros'].get(3)
    check('profile_bindings returns the saved macro for the macros tab',
          ok and saved and [s.get('text') for s in saved['steps']] == ['saved'], msg)

    print()
    if failures:
        print(f'FAILED ({len(failures)}): ' + '; '.join(failures))
        return 1
    print('All offline checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
