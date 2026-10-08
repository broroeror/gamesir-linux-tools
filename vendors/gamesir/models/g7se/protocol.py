"""G7 SE remap-only protocol, deliberately independent of G7 Pro.

Record semantics verified on descriptor 6.30 with Nexus captures and Linux
roundtrips. Cold connections require a fresh verified GIP v1 handshake.
Only complete L4/R4 records and fourteen captured targets are defined here.
"""

VID = 0x3537
PID = 0x1010
TESTED_DESCRIPTOR = 0x0630
CONFIGURATION_VERIFIED = True  # Firmware 0630: authenticated reads and remap roundtrips.
PROFILE_SIZE = 421
PROFILE_BANKS = (1, 2, 3)  # Nexus exposes three editable profiles.
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
            return request == remap_write(sequence, request[5],
                int.from_bytes(request[6:8], 'big'), request[9:17])
        if len(request) == 9 and request[3:5] == b'\x05\x04':
            if request[5] not in PROFILE_BANKS or request[8] != 8:
                return False
            if int.from_bytes(request[6:8], 'big') not in dict(REMAP_SLOTS).values():
                return False
        elif request[3:] not in (b'\x02\xf2\x00', b'\x01\x0b'):
            return False
        return request == nexus_request(sequence, request[3], request[4:])
    except (ValueError, IndexError):
        return False


def open_device(bus, address, sysfs):
    from pathlib import Path
    from vendors.gamesir.usb_transport import InterruptHandle, UsbTransportError
    if not CONFIGURATION_VERIFIED:
        raise UsbTransportError('G7 SE configuration disabled: cold-start replies unverified')
    root = Path(sysfs).resolve()
    if (root / 'bcdDevice').read_text().strip() != '0630':
        raise UsbTransportError('G7 SE remapping is tested only on firmware descriptor 6.30')
    return InterruptHandle.open(VID, (PID,), bus, address, sysfs, 0, 2, 0x82)


def nexus_initialize(sequence):
    """Captured transient GIP startup candidate; Linux behavior not yet verified."""
    if not 1 <= sequence <= 255:
        raise ValueError('Startup sequence must be nonzero and fit in a byte')
    return bytes((5, 0x20, sequence, 1, 5))


def nexus_silent_rumble(sequence):
    """Captured companion startup packet; all four motor amplitudes are zero."""
    if not 1 <= sequence <= 255:
        raise ValueError('Startup sequence must be nonzero and fit in a byte')
    return bytes((9, 0, sequence, 9, 0, 15, 0, 0, 0, 0, 255, 0, 235))


def packet(sequence, command, payload):
    """Only allow the three read-only discovery commands and their payloads."""
    payload = bytes(payload)
    if command == 0x02:
        allowed = payload == b'\xf2\x00'
    elif command == 0x01:
        allowed = payload in (b'\x09', b'\x0b')  # firmware / active-profile candidates
    elif command == 0x05:
        allowed = (len(payload) == 5 and payload[0] == 4
                   and 1 <= payload[1] <= 4 and 1 <= payload[4] <= 55
                   and int.from_bytes(payload[2:4], 'big') + payload[4] <= 480)
    else:
        allowed = False
    if not allowed or not 0 <= sequence <= 255:
        raise ValueError('Not an allowed G7 SE discovery request')
    return bytes((0x0f, 0, sequence, command)) + payload + bytes(60 - len(payload))


def read_request(sequence, profile, offset, length):
    return packet(sequence, 5, bytes((4, profile)) + offset.to_bytes(2, 'big')
                  + bytes((length,)))


def nexus_request(sequence, command, payload):
    """Exact short OUT transfer observed in Nexus Legacy 1.5.3.0 captures.

    Reuse the diagnostic read-only allowlist, removing USB padding. Windows
    reads are 9 bytes, heartbeats 6, and information queries 5.
    """
    request = packet(sequence, command, payload)
    return request[:4 + len(payload)]


def fixed_length_read_request(sequence, profile, offset, length):
    """Unverified SE framing candidate using advertised 60-byte vendor size.

    Preserve the existing read-only inner command 04 and read tuple. Only the
    GIP payload length changes from 5 to 60; no register-write inner 03 allowed.
    """
    request = bytearray(read_request(sequence, profile, offset, length))
    request[3] = 60
    return bytes(request)


def match_read(reply, profile, offset, length):
    """Accept only complete candidate replies echoing the entire read tuple."""
    reply = bytes(reply)
    echo = bytes((5, profile)) + offset.to_bytes(2, 'big') + bytes((length,))
    if (1 <= profile <= 4 and 1 <= length <= 55 and 0 <= offset <= 480 - length
            and 9 + length <= len(reply) <= 64 and reply[:2] == b'\x10\x00'
            and reply[3] == 0x3c and reply[4:9] == echo):
        return reply[9:9 + length]
    return None


def legacy_packet(command, payload=b''):
    """Existing GameSir family framing; diagnostic candidates only on G7 SE."""
    payload = bytes(payload)
    allowed = command == 0xf2 and not payload
    if command == 4:
        allowed = (len(payload) == 4 and 1 <= payload[0] <= 4
                   and 1 <= payload[3] <= 55
                   and int.from_bytes(payload[1:3], 'big') + payload[3] <= 480)
    if not allowed:
        raise ValueError('Not an allowed legacy GameSir discovery request')
    return bytes((0x0f, command)) + payload + bytes(62 - len(payload))


def match_legacy_read(reply, profile, offset, length):
    reply = bytes(reply)
    echo = bytes((0x10, 5, profile)) + offset.to_bytes(2, 'big') + bytes((length,))
    if (1 <= profile <= 4 and 1 <= length <= 55 and 0 <= offset <= 480 - length
            and 6 + length <= len(reply) <= 64 and reply[:6] == echo):
        return reply[6:6 + length]
    return None


def gip_power_on(sequence):
    """xpad's standard volatile input initialization, not a settings write.

    drivers/input/joystick/xpad.c: xboxone_power_on, sent to all Xbox One pads.
    No other GIP power, authentication or identity-transition command is allowed.
    """
    if not 0 <= sequence <= 255:
        raise ValueError('Sequence must fit in one byte')
    return bytes((5, 0x20, sequence, 1, 0))
