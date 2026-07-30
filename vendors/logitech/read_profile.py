#!/usr/bin/env python3
"""
READ-ONLY validation: dump the G502 X's onboard profiles.
=========================================================
Proves the HID++ transport (hidpp.py) + onboard codec (onboard.py) against the
real device WITHOUT writing a single byte to the mouse. It:
  * finds the HID++ hidraw node and reads the 0x8100 store info,
  * reads every profile sector and decodes it,
  * VERIFIES each profile's stored CRC against our own computation (a strong
    signal that both the read and our layout understanding are correct),
  * reports whether the G-Shift second layer holds any bindings — i.e. whether a
    prior Piper/libratbag save wiped it.

Run it (the mouse's HID++ node is root-owned, and ratbagd must not hold the
device at the same time):

    sudo systemctl stop ratbagd
    sudo python3 vendors/logitech/read_profile.py
    # ratbagd re-activates on demand next time Piper needs it

Nothing here writes to the device; it is safe to run repeatedly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hidpp        # noqa: E402
import onboard      # noqa: E402


def main():
    dev = hidpp.find_device()
    if dev is None:
        print('No HID++ G502 X found. Checklist:')
        print('  * is the mouse connected (wired or via its Lightspeed receiver)?')
        print('  * run under sudo (the HID++ hidraw node is root-owned), and')
        print('  * `sudo systemctl stop ratbagd` first so it is not holding the device.')
        return 1

    with dev:
        info = dev.onboard_info()
        print('== ONBOARD_PROFILES (0x8100) store ==')
        print(f'  profile_format 0x{info["profile_format"]:02x}  '
              f'macro_format 0x{info["macro_format"]:02x}  '
              f'memory_model 0x{info["memory_model_id"]:02x}')
        print(f'  profiles {info["profile_count"]}  buttons {info["button_count"]}  '
              f'sector_size {info["sector_size"]}  '
              f'G-Shift bank present: {info["has_gshift"]}')

        try:
            active = dev.current_profile()
        except Exception:
            active = None
        headers = dev.profile_headers()
        print(f'  directory: {len(headers)} profile(s); active sector '
              f'{"0x%04x" % active if active is not None else "?"}')
        print()

        any_gshift = False
        roundtrip_all_ok = True
        for sector, enabled in headers:
            # Read exactly what getInfo reports (255 bytes here). The firmware
            # rejects any read running past offset 239 (offset+16 > 255), so we
            # must NOT over-read to 256; the 2-byte CRC trailer is the last 2
            # bytes of these 255 ([253:255]), and the codec checks it size-agnostically.
            raw = dev.read_sector(sector, info['sector_size'])
            prof = onboard.OnboardProfile.decode(raw, sector=sector, enabled=enabled)
            marker = '  <== ACTIVE' if active == sector else ''
            print(prof.dump() + marker)
            # STAGE 1 GATE (in-memory, NO device write): re-encode from the decoded
            # fields and prove it reproduces the exact bytes we read.
            reenc = prof.to_bytes()
            if reenc == raw:
                print('  round-trip : encode(decode)==raw  OK  (byte-exact, %d B)' % len(raw))
            else:
                roundtrip_all_ok = False
                diff = next((i for i in range(min(len(raw), len(reenc))) if raw[i] != reenc[i]), None)
                print('  round-trip : ** MISMATCH ** first diff @offset %s (len raw=%d reenc=%d)'
                      % (diff, len(raw), len(reenc)))
                if diff is not None:
                    print('               raw[%d]=0x%02x reenc[%d]=0x%02x'
                          % (diff, raw[diff], diff, reenc[diff]))
            print()
            any_gshift = any_gshift or prof.gshift_configured

        print('== round-trip gate ==')
        print('  ' + ('ALL profiles re-encode byte-exact — the codec reproduces every byte, '
                      'so read-modify-write is safe to build the write path on.' if roundtrip_all_ok
                      else 'Some profiles did NOT round-trip (see above) — the encoder needs a fix '
                           'BEFORE any write path.'))
        print()
        print('== G-Shift verdict ==')
        if any_gshift:
            print('  Your G-Shift layer still holds bindings — it was NOT wiped.')
        else:
            print('  No G-Shift bindings found in any profile. Either you never set')
            print('  any, or the earlier Piper save wiped them (both look identical here).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
