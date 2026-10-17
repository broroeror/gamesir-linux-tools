"""G7 SE rear-button remapping and report-rate protocol.

Record semantics verified on descriptor 6.30 with Nexus captures and Linux
roundtrips. Cold connections require a fresh verified GIP v1 handshake.
Writes allow only complete L4/R4 records and the captured report-rate byte.
"""

VID = 0x3537
PID = 0x1010
TESTED_DESCRIPTOR = 0x0630
CONFIGURATION_VERIFIED = True  # Firmware 0630: authenticated reads and remap roundtrips.
# Firmware 6.64 enumerates under different ids and auto-detects the host: hot-
# plugged on Linux it offers 10a0 (XInput), drops off the bus ~2-4 ms after the
# config descriptor is read and comes back as 1082 (DirectInput, the id the
# Kaleid also uses). Plugged in across a cold boot it settles on 1069 (Xbox GIP)
# and xpad binds it. Input only: no configuration reply has been verified there.
PID_GIP_664 = 0x1069
PID_XINPUT_664 = 0x10a0
PID_HID_664 = 0x1082
OTHER_PIDS = (PID_GIP_664, PID_XINPUT_664)


def is_g7se_product(product):
    return bool(product) and 'g7 se' in product.lower()


PROFILE_SIZE = 421
PROFILE_BANKS = (1, 2, 3)  # Nexus exposes three editable profiles.
RATE_BANKS = (1, 2, 3, 4)  # Nexus applies its controller-wide rate to all banks.
POLL_RATE = 0x0036
POLL_RATES = ('250 Hz', '500 Hz', '1000 Hz')
REMAP_SLOTS = (('L4', 0x00ab), ('R4', 0x00c7))
GAMEPAD_TARGETS = (('Dpad Up', 1), ('Dpad Down', 2), ('Dpad Left', 3),
                  ('Dpad Right', 4), ('LB', 5), ('RB', 6), ('LS', 7), ('RS', 8),
                  ('A', 15), ('B', 16), ('X', 17), ('Y', 18), ('View', 22), ('Menu', 23))


def remap_record(code):
    if code == -1:
        return bytes(8)
    if code not in dict((c, n) for n, c in GAMEPAD_TARGETS):
        raise ValueError('Unsupported G7 SE gamepad target')
    return b'\x04\x00\x00\x00\x00\x00\x01' + bytes((code,))


def decode_remap(record):
    record = bytes(record)
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
    decode_remap(record)
    body = bytes((3, profile)) + address.to_bytes(2, 'big') + bytes((8,)) + record
    return bytes((15, 0, sequence, 60)) + body.ljust(60, b'\0')


def allowed_app_request(request):
    """Final production USB guard: no unrelated settings/profile/dock writes."""
    request = bytes(request)
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
    body = bytes((3, bank, 0, POLL_RATE, 1)) + data
    return bytes((15, 0, sequence, 60)) + body.ljust(60, b'\0')


def settings_write(sequence, bank, address, data):
    if address == POLL_RATE:
        return rate_write(sequence, bank, data)
    return remap_write(sequence, bank, address, data)


def allowed_setting_read(bank, address, length):
    return ((bank in RATE_BANKS and address == POLL_RATE and length == 1)
            or (bank in PROFILE_BANKS and address in dict(REMAP_SLOTS).values() and length == 8))


def open_device(bus, address, sysfs):
    from pathlib import Path
    from vendors.gamesir.usb_transport import InterruptHandle, UsbTransportError
    if not CONFIGURATION_VERIFIED:
        raise UsbTransportError('G7 SE configuration disabled: cold-start replies unverified')
    root = Path(sysfs).resolve()
    if (root / 'bcdDevice').read_text().strip() != f'{TESTED_DESCRIPTOR:04x}':
        raise UsbTransportError('G7 SE remapping is tested only on firmware descriptor 6.30')
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
