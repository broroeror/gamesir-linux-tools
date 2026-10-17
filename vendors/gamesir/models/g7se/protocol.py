"""G7 SE rear-button remapping and report-rate protocol.

Record semantics verified on descriptor 6.30 with Nexus captures and Linux
roundtrips, and on 6.64 with Nexus 2.5.8 captures (one change per capture).
Cold connections require a fresh verified GIP v1 handshake.
Writes allow only complete L4/R4 records and the captured report-rate byte.
The module constants describe the selected firmware; select() switches them.
"""

VID = 0x3537
PID = 0x1010
TESTED_DESCRIPTOR = 0x0630
CONFIGURATION_VERIFIED = True  # Firmware 0630: authenticated reads and remap roundtrips.
# Firmware 6.64 enumerates under different ids and auto-detects the host: hot-
# plugged on Linux it offers 10a0 (XInput), drops off the bus ~2-4 ms after the
# config descriptor is read and comes back as 1082 (DirectInput, the id the
# Kaleid also uses). Plugged in across a cold boot it settles on 1069 (Xbox GIP)
# and xpad binds it; only that identity is configurable.
PID_GIP_664 = 0x1069
PID_XINPUT_664 = 0x10a0
PID_HID_664 = 0x1082


def is_g7se_product(product):
    return bool(product) and 'g7 se' in product.lower()


PROFILE_SIZE = 421
PROFILE_BANKS = (1, 2, 3)  # Nexus exposes three editable profiles.
POLL_RATES = ('250 Hz', '500 Hz', '1000 Hz')

def _percent(data):
    return len(data) == 1 and data[0] <= 100


def _flag(data):
    return len(data) == 1 and data[0] in (0, 1)


def _hair(data):
    # 00 off, 81 adaptive, 82 fixed (G7 Pro codes); factory banks hold 01, which
    # is shown as off and only ever written back as-is (restore/rollback).
    return len(data) == 1 and data[0] in (0x00, 0x01, 0x81, 0x82)


def _curve(data):
    # [type 0-3, intensity 0-100, 0, 0, x0 y0 x1 y1 x2 y2] (G7 Pro curve block)
    return len(data) == 10 and data[0] <= 3 and data[1] <= 100 and data[2:4] == b'\0\0'


# 6.64 profile settings with a verified plain write: on bank 3, each one changed
# exactly its own bytes and restored byte-exact (write_test_664.py, 2026-10-17).
# address -> (length, validator). Stick fields repeat at +0x20 (right stick),
# trigger fields at +0x1c (right trigger), as on the G7 Pro.
SETTINGS_664 = {
    0x0020: (1, _percent), 0x0021: (1, _percent),            # grip vibration L/R
    0x0022: (1, _percent), 0x0023: (1, _percent),            # trigger vibration L/R
    **{a + o: (1, _percent) for o in (0, 0x1c)                 # trigger dz / anti-dz
       for a in (0x00cf, 0x00d0, 0x00d1, 0x00d2)},
    **{a + o: (1, _percent) for o in (0, 0x20)                 # stick dz / anti-dz
       for a in (0x013f, 0x0140, 0x0141, 0x0142)},
    0x0153: (1, _percent), 0x0173: (1, _percent),            # stick sensitivity
    0x0151: (1, _flag), 0x0152: (1, _flag),                  # left stick invert X/Y
    0x0171: (1, _flag), 0x0172: (1, _flag),                  # right stick invert X/Y
    0x00dc: (10, _curve), 0x00f8: (10, _curve),              # trigger curves
    0x0144: (10, _curve), 0x0164: (10, _curve),              # stick curves
    0x013d: (1, _flag), 0x015d: (1, _flag),                  # trajectory circle/raw
    0x00d8: (1, _hair), 0x00f4: (1, _hair),                  # hair trigger mode
}

# Per-firmware register layout.
#   6.30: 8-byte rear records (04 00 00 00 00 00 01 target, zeros = default);
#         one controller-wide rate byte that Nexus writes to all four banks.
#   6.64: a 1-byte target code at the end of each 7-byte button record, where
#         the default is the button's own code (L4 11, R4 12); the rate byte is
#         per profile (Nexus 2.5.8 wrote only the edited bank). Rate code 00 is
#         assumed to be 250 Hz like 6.30; 01 and 02 were captured.
LAYOUTS = {
    0x0630: dict(
        PID=0x1010, RATE_BANKS=(1, 2, 3, 4), RATE_PER_PROFILE=False, POLL_RATE=0x0036,
        REMAP_LEN=8, REMAP_SLOTS=(('L4', 0x00ab), ('R4', 0x00c7)), REMAP_DEFAULTS={},
        FULL_VIEW=False, SETTINGS={},
        GAMEPAD_TARGETS=(('Dpad Up', 1), ('Dpad Down', 2), ('Dpad Left', 3),
                         ('Dpad Right', 4), ('LB', 5), ('RB', 6), ('LS', 7), ('RS', 8),
                         ('A', 15), ('B', 16), ('X', 17), ('Y', 18), ('View', 22),
                         ('Menu', 23))),
    0x0664: dict(
        PID=PID_GIP_664, RATE_BANKS=PROFILE_BANKS, RATE_PER_PROFILE=True, POLL_RATE=0x0030,
        # Front buttons: 2-byte G7 Pro-style slots (flag 01 + target, 00 00 =
        # default), verified on bank 3 by tools/g7se_write_test_664.py. L4/R4
        # keep their captured 1-byte target form (their flag is always 01).
        REMAP_LEN=1, REMAP_SLOTS=(
            ('Dpad Up', 0x0042), ('Dpad Down', 0x0049), ('Dpad Left', 0x0050),
            ('Dpad Right', 0x0057), ('LB', 0x005e), ('RB', 0x0065), ('LS', 0x006c),
            ('RS', 0x0073), ('A', 0x007a), ('B', 0x0081), ('X', 0x0088), ('Y', 0x008f),
            ('View', 0x009d), ('Menu', 0x00a4), ('LT', 0x00d3), ('RT', 0x00ef),
            ('L4', 0x00b3), ('R4', 0x00c1)),
        REMAP_DEFAULTS={0x00b3: 0x11, 0x00c1: 0x12},
        # The 6.64 bank follows the G7 Pro register map (vibration 0x20.., trigger
        # blocks 0xcf/0xeb, stick blocks 0x13c/0x15c), so the whole bank is read
        # and shown read-only. Writes stay limited to the captured L4/R4/rate.
        FULL_VIEW=True, SETTINGS=SETTINGS_664,
        GAMEPAD_TARGETS=(('Dpad Up', 1), ('Dpad Down', 2), ('Dpad Left', 3),
                         ('Dpad Right', 4), ('LB', 5), ('RB', 6), ('LS', 7), ('RS', 8),
                         ('A', 9), ('B', 10), ('X', 11), ('Y', 12), ('View', 14),
                         ('Menu', 15), ('LT', 0x13), ('RT', 0x14))),
}
SUPPORTED_DESCRIPTORS = tuple(LAYOUTS)
CONFIG_PIDS = tuple(layout['PID'] for layout in LAYOUTS.values())
LAYOUT_PIDS = {layout['PID']: descriptor for descriptor, layout in LAYOUTS.items()}
RATE_BANKS = RATE_PER_PROFILE = POLL_RATE = None
REMAP_LEN = REMAP_SLOTS = REMAP_DEFAULTS = GAMEPAD_TARGETS = FULL_VIEW = SETTINGS = None
READ_CHUNK = 0x37  # bytes per register read reply on this channel


def select(descriptor):
    """Switch the module to a firmware layout. False (and no change) if unknown."""
    layout = LAYOUTS.get(descriptor)
    if layout is None:
        return False
    globals().update(layout, TESTED_DESCRIPTOR=descriptor)
    return True


select(TESTED_DESCRIPTOR)


def descriptor_name(descriptor=None):
    descriptor = TESTED_DESCRIPTOR if descriptor is None else descriptor
    return f'{descriptor >> 8}.{descriptor & 0xff:02x}'


def rate_banks(profile):
    """Banks one rate edit is written to."""
    return (profile,) if RATE_PER_PROFILE else RATE_BANKS


def remap_len(address):
    """Bytes in one source-button record at ``address``."""
    if REMAP_LEN == 1 and address not in REMAP_DEFAULTS:
        return 2                      # 6.64 front-button slot: flag + target
    return REMAP_LEN


def _targets():
    return dict((c, n) for n, c in GAMEPAD_TARGETS)


def remap_record(code, address=None):
    if remap_len(address) == 2:
        if address not in dict(REMAP_SLOTS).values():
            raise ValueError('Unsupported G7 SE remap source')
        if code == -1:
            return b'\0\0'
        if code not in _targets():
            raise ValueError('Unsupported G7 SE gamepad target')
        return bytes((1, code))
    if REMAP_LEN == 1:
        if address not in REMAP_DEFAULTS:
            raise ValueError('Unsupported G7 SE remap source')
        if code == -1:
            return bytes((REMAP_DEFAULTS[address],))
        if code not in dict((c, n) for n, c in GAMEPAD_TARGETS):
            raise ValueError('Unsupported G7 SE gamepad target')
        return bytes((code,))
    if code == -1:
        return bytes(8)
    if code not in dict((c, n) for n, c in GAMEPAD_TARGETS):
        raise ValueError('Unsupported G7 SE gamepad target')
    return b'\x04\x00\x00\x00\x00\x00\x01' + bytes((code,))


def decode_remap(record, address=None):
    record = bytes(record)
    if remap_len(address) == 2:
        if len(record) == 2 and address in dict(REMAP_SLOTS).values():
            if record[0] == 0:
                return -1
            if record[0] == 1 and record[1] in _targets():
                return record[1]
        raise ValueError('Unknown G7 SE button record; editing refused')
    if REMAP_LEN == 1:
        if len(record) == 1 and address in REMAP_DEFAULTS:
            if record[0] == REMAP_DEFAULTS[address]:
                return -1
            if record[0] in dict((c, n) for n, c in GAMEPAD_TARGETS):
                return record[0]
        raise ValueError('Unknown G7 SE rear-button record; editing refused')
    if record == bytes(8):
        return -1
    if len(record) != 8 or record != remap_record(record[-1]):
        raise ValueError('Unknown G7 SE rear-button record; editing refused')
    return record[-1]


def remap_write(sequence, profile, address, record):
    """Captured 64-byte write form, restricted to complete rear records."""
    if (not 0 <= sequence <= 255 or profile not in PROFILE_BANKS
            or address not in dict(REMAP_SLOTS).values()):
        raise ValueError('Unsupported G7 SE remap source/profile')
    record = bytes(record)
    decode_remap(record, address)
    body = bytes((3, profile)) + address.to_bytes(2, 'big') + bytes((len(record),)) + record
    return bytes((15, 0, sequence, 60)) + body.ljust(60, b'\0')


def rumble_packet(sequence, left, right, trigger_left=0, trigger_right=0):
    """Xbox GIP rumble (command 0x09), as xpad sends in GIP mode: 400 ms."""
    from vendors.gamesir.models.g7pro import protocol as g7
    return g7.rumble_packet(sequence, left, right, trigger_left, trigger_right)


def allowed_rumble(request):
    """Only the 13-byte GIP rumble/stop packet (grips + triggers), on 6.64."""
    request = bytes(request)
    if not FULL_VIEW or len(request) != 13 or request[:2] != b'\x09\x00' or request[2] == 0:
        return False
    lt, rt, left, right = (round(p * 255 / 100) for p in request[6:10])
    return request == rumble_packet(request[2], left, right, lt, rt)


def allowed_app_request(request):
    """Final production USB guard: no unrelated settings/profile/dock writes."""
    request = bytes(request)
    if len(request) == 13 and request[:1] == b'\x09':
        return allowed_rumble(request)
    try:
        if len(request) < 5 or request[:2] != b'\x0f\x00':
            return False
        sequence = request[2]
        if len(request) == 64 and request[3:5] == b'\x3c\x03':
            return request == settings_write(sequence, request[5],
                int.from_bytes(request[6:8], 'big'), request[9:9 + request[8]])
        if len(request) == 9 and request[3:5] == b'\x05\x04':
            if not allowed_setting_read(request[5], int.from_bytes(request[6:8], 'big'), request[8]):
                return False
        elif request[3:] not in (b'\x02\xf2\x00', b'\x01\x0b'):
            return False
        return request == nexus_request(sequence, request[3], request[4:])
    except (ValueError, IndexError):
        return False


def decode_rate(data):
    data = bytes(data)
    if len(data) != 1 or data[0] not in range(len(POLL_RATES)):
        raise ValueError('Unknown G7 SE report-rate value; editing refused')
    return data[0]


def rate_write(sequence, bank, data):
    data = bytes(data)
    decode_rate(data)
    if not 0 <= sequence <= 255 or bank not in RATE_BANKS:
        raise ValueError('Unsupported G7 SE report-rate bank/sequence')
    body = bytes((3, bank)) + POLL_RATE.to_bytes(2, 'big') + b'\x01' + data
    return bytes((15, 0, sequence, 60)) + body.ljust(60, b'\0')


def setting_write(sequence, bank, address, data):
    """Plain write of one verified profile setting (6.64 SETTINGS table)."""
    data = bytes(data)
    length, valid = SETTINGS[address]
    if (not 0 <= sequence <= 255 or bank not in PROFILE_BANKS
            or len(data) != length or not valid(data)):
        raise ValueError(f'Unsupported G7 SE value at 0x{address:04x}; editing refused')
    body = bytes((3, bank)) + address.to_bytes(2, 'big') + bytes((length,)) + data
    return bytes((15, 0, sequence, 60)) + body.ljust(60, b'\0')


def settings_write(sequence, bank, address, data):
    if address == POLL_RATE:
        return rate_write(sequence, bank, data)
    if SETTINGS and address in SETTINGS:
        return setting_write(sequence, bank, address, data)
    return remap_write(sequence, bank, address, data)


def view_requests(bank):
    """Chunked reads covering one whole profile bank (read-only view)."""
    return [(bank, off, min(READ_CHUNK, PROFILE_SIZE - off))
            for off in range(0, PROFILE_SIZE, READ_CHUNK)]


def stitch_view(bank, result):
    """Assemble a bank from ``result(bank, offset)`` replies, or None."""
    out = bytearray()
    for _bank, off, size in view_requests(bank):
        part = result(bank, off)
        if part is None or len(part) < size:
            return None
        out.extend(part[:size])
    return bytes(out)


def allowed_setting_read(bank, address, length):
    if FULL_VIEW and bank in PROFILE_BANKS and (bank, address, length) in view_requests(bank):
        return True
    if SETTINGS and bank in PROFILE_BANKS and SETTINGS.get(address, (None,))[0] == length:
        return True
    return ((bank in RATE_BANKS and address == POLL_RATE and length == 1)
            or (bank in PROFILE_BANKS and address in dict(REMAP_SLOTS).values()
                and length == remap_len(address)))


def open_device(bus, address, sysfs):
    from pathlib import Path
    from vendors.gamesir.usb_transport import InterruptHandle, UsbTransportError
    if not CONFIGURATION_VERIFIED:
        raise UsbTransportError('G7 SE configuration disabled: cold-start replies unverified')
    root = Path(sysfs).resolve()
    if (root / 'bcdDevice').read_text().strip() != f'{TESTED_DESCRIPTOR:04x}':
        raise UsbTransportError('G7 SE firmware changed since its layout was selected')
    return InterruptHandle.open(VID, (PID,), bus, address, sysfs, 0, 2, 0x82)


def nexus_request(sequence, command, payload):
    """Verified short Nexus reads, heartbeats and information requests.

    The app write guard further restricts profile reads to rear-button records.
    Startup and diagnostics can read the full captured profile range.
    """
    payload = bytes(payload)
    if command == 0x02:
        allowed = payload == b'\xf2\x00'
    elif command == 0x01:
        allowed = payload in (b'\x09', b'\x0b')  # firmware / active-profile information
    elif command == 0x05:
        allowed = (len(payload) == 5 and payload[0] == 4
                   and 1 <= payload[1] <= 4 and 1 <= payload[4] <= 55
                   and int.from_bytes(payload[2:4], 'big') + payload[4] <= PROFILE_SIZE)
    else:
        allowed = False
    if not allowed or not 0 <= sequence <= 255:
        raise ValueError('Not an allowed G7 SE read request')
    return bytes((0x0f, 0, sequence, command)) + payload


# 6.30 echoes the request's sequence byte in its replies; 6.64 stamps replies
# with its own counter instead (seen on 1069: request 0b answered as 0a). The
# bank/offset/length echo in match_read still binds a reply to its request.
SEQUENCE_ECHO = {0x0630: True, 0x0664: False}


def reply_sequence_ok(reply, sequence):
    return not SEQUENCE_ECHO.get(TESTED_DESCRIPTOR, True) or (
        len(reply) > 2 and reply[2] == sequence)


def match_read(reply, profile, offset, length):
    """Accept only complete replies echoing the entire read tuple."""
    reply = bytes(reply)
    echo = bytes((5, profile)) + offset.to_bytes(2, 'big') + bytes((length,))
    if (1 <= profile <= 4 and 1 <= length <= 55 and 0 <= offset <= PROFILE_SIZE - length
            and 9 + length <= len(reply) <= 64 and reply[:2] == b'\x10\x00'
            and reply[3] == 0x3c and reply[4:9] == echo):
        return reply[9:9 + length]
    return None


def gip_power_on(sequence):
    """xpad's standard volatile input initialization, not a settings write.

    drivers/input/joystick/xpad.c: xboxone_power_on, sent to all Xbox One pads.
    No other GIP power, authentication or identity-transition command is allowed.
    """
    if not 0 <= sequence <= 255:
        raise ValueError('Sequence must fit in one byte')
    return bytes((5, 0x20, sequence, 1, 0))
