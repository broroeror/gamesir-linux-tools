"""GameSir G7 Pro vendor-USB protocol.

The G7 Pro's configuration identities expose a vendor-class interface rather
than hidraw.  This
module contains only model-specific facts; the shared command queue, native
Linux USB transport, and Qt bridge remain in their existing modules.

Protocol research credit: questionablesyntax/g7ctl's Apache-2.0 ``pyg7``
package.  This is an independent integration for Deadband's transport model.
"""

from __future__ import annotations

import time

from vendors.gamesir.usb_transport import InterruptHandle

VID = 0x3537
PID_WIRED = 0x109B
PID_DONGLE = 0x109C
PID_HID = 0x100A
PID_NATIVE = 0x1022
CONFIG_PIDS = (PID_WIRED, PID_DONGLE)
TRANSITION_PIDS = (PID_HID,)
ALL_PIDS = CONFIG_PIDS + TRANSITION_PIDS + (PID_NATIVE,)
# Compatibility names used by early versions of this integration.
PID_RECEIVER = PID_DONGLE
PID_COMPANION = PID_HID
IFACE = 0
EP_OUT = 0x02
EP_IN = 0x82
REPORT_SIZE = 64
READ_CHUNK = 0x37
PROFILE_BLOB_SIZE = 480
DOCK_BLOB_SIZE = 511

INPUT_MARKER = 0xE0
READ_MARKER = 0x05
RESPONSE_MARKER = 0x3C

# GameSir's physical-input group uses the same hat encoding as its enhanced
# reports.  Values 0..7 walk clockwise; 8 and 15 are both seen at rest.
DPAD_HAT = {
    0: 'up', 1: 'up-right', 2: 'right', 3: 'down-right',
    4: 'down', 5: 'down-left', 6: 'left', 7: 'up-left',
    8: 'neutral', 15: 'neutral',
}

HANDSHAKE_CHUNKS = (b'ga', b'me', b'si', b'ra', b'pp')
HANDSHAKE_FLUSH = bytes((0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))

# Default-layer records.  LT/RT are single-byte records at their own offsets;
# all other sources use fixed seven-byte records beginning at these addresses.
REMAP_SLOTS = (
    ('Dpad Up', 0x0042), ('Dpad Down', 0x0049),
    ('Dpad Left', 0x0050), ('Dpad Right', 0x0057),
    ('LB', 0x005E), ('RB', 0x0065), ('LS', 0x006C), ('RS', 0x0073),
    ('A', 0x007A), ('B', 0x0081), ('X', 0x0088), ('Y', 0x008F),
    ('View', 0x009D), ('Menu', 0x00A4), ('Share', 0x00AB),
    ('L4', 0x00B2), ('L5', 0x00B9), ('R4', 0x00C0), ('R5', 0x00C7),
    # Trigger allocate addresses sit one byte before their single-byte readback.
    ('LT', 0x00D3), ('RT', 0x00EF),
)
TRIGGER_REMAPS = {0x00D3, 0x00EF}
TRIGGER_REMAP_READ = {0x00D3: 0x00D4, 0x00EF: 0x00F0}

GAMEPAD_TARGETS = (
    ('Dpad Up', 0x01), ('Dpad Down', 0x02), ('Dpad Left', 0x03),
    ('Dpad Right', 0x04), ('LB', 0x05), ('RB', 0x06), ('LS', 0x07),
    ('RS', 0x08), ('A', 0x09), ('B', 0x0A), ('X', 0x0B), ('Y', 0x0C),
    ('Home', 0x0D), ('View', 0x0E), ('Menu', 0x0F), ('Share', 0x10),
    ('L4', 0x11), ('R4', 0x12), ('LT', 0x13), ('RT', 0x14),
    ('L5', 0x1F), ('R5', 0x20),
)
MOUSE_TARGETS = (
    ('Left Click', 0xC8), ('Middle Click', 0xC9), ('Right Click', 0xCA),
    ('Mouse 5', 0xCB), ('Mouse 4', 0xCC),
    ('Scroll Up', 0xCD), ('Scroll Down', 0xCE),
)
NUMPAD_ROWS = (
    (('Num /', 0x85, 1), ('Num *', 0x86, 1), ('Num -', 0x87, 1),
     ('Num +', 0x88, 1)),
    (('Num 7', 0x92, 1), ('Num 8', 0x93, 1), ('Num 9', 0x94, 1),
     ('Num Enter', 0x8A, 1.5)),
    (('Num 4', 0x8F, 1), ('Num 5', 0x90, 1), ('Num 6', 0x91, 1)),
    (('Num 1', 0x8C, 1), ('Num 2', 0x8D, 1), ('Num 3', 0x8E, 1)),
    (('Num 0', 0x8B, 2), ('Num .', 0x89, 1)),
)
NUMPAD_TARGETS = tuple((name, code) for row in NUMPAD_ROWS for name, code, _w in row)

# Safe live-suffix lengths for the firmware's long-form writes.
LONG_SUFFIX = {
    0x013F: 13, 0x0140: 12, 0x0141: 12, 0x0142: 11,
    0x015F: 13, 0x0160: 12, 0x0161: 12, 0x0162: 11,
    0x00CF: 19, 0x00D0: 20, 0x00D1: 20, 0x00D2: 19,
    0x00EB: 19, 0x00EC: 20, 0x00ED: 20, 0x00EE: 19,
}


def blob_requests(category: int, length: int = PROFILE_BLOB_SIZE):
    """Return observed-safe chunk reads for one configuration blob."""
    return [(category, off, min(READ_CHUNK, length - off))
            for off in range(0, length, READ_CHUNK)]


def stitch_blob(category: int, length: int, result):
    """Assemble a blob using ``result(category, offset)`` or return None."""
    out = bytearray()
    for _cat, off, size in blob_requests(category, length):
        part = result(category, off)
        if part is None or len(part) < size:
            return None
        out.extend(part[:size])
    return bytes(out[:length])


def decode_remaps(blob: bytes):
    out = {}
    for name, addr in REMAP_SLOTS:
        if addr >= len(blob):
            out[name] = -1
        elif addr in TRIGGER_REMAPS:
            out[name] = blob[TRIGGER_REMAP_READ[addr]] or -1
        else:
            out[name] = blob[addr + 1] if blob[addr] == 1 else -1
    return out


def decode_profile(blob: bytes):
    """Decode the approved G7 surface from a 480-byte profile image."""
    def b(addr, default=0):
        return blob[addr] if addr < len(blob) else default

    def curve(addr):
        raw = blob[addr:addr + 10]
        pts = [[raw[i], raw[i + 1]] for i in (4, 6, 8)] if len(raw) >= 10 else []
        return {'type': min(b(addr), 3), 'intensity': b(addr + 1, 100), 'points': pts}

    return {
        'vib_l': b(0x20), 'vib_r': b(0x21), 'poll': min(b(0x30), 2),
        'vib_trigger_l': b(0x22), 'vib_trigger_r': b(0x23),
        'vib_force_l': bool(b(0x24) & 1), 'vib_sync_l': bool(b(0x24) & 2),
        'vib_force_r': bool(b(0x25) & 1), 'vib_sync_r': bool(b(0x25) & 2),
        'dpad_swap': bool(b(0x2B)), 'dpad_lock': bool(b(0x2D)),
        'st_traj': b(0x13D), 'rs_traj': b(0x15D),
        'st_dz_min': b(0x13F), 'st_dz_max': b(0x140),
        'st_adz_min': b(0x141), 'st_adz_max': b(0x142),
        'rs_dz_min': b(0x15F), 'rs_dz_max': b(0x160),
        'rs_adz_min': b(0x161), 'rs_adz_max': b(0x162),
        'lt_dz_min': b(0x0CF), 'lt_dz_max': b(0x0D0),
        'lt_adz_min': b(0x0D1), 'lt_adz_max': b(0x0D2),
        'rt_dz_min': b(0x0EB), 'rt_dz_max': b(0x0EC),
        'rt_adz_min': b(0x0ED), 'rt_adz_max': b(0x0EE),
        'lt_hair': {0x00: 0, 0x81: 1, 0x82: 2}.get(b(0x0D8), 0),
        'rt_hair': {0x00: 0, 0x81: 1, 0x82: 2}.get(b(0x0F4), 0),
        'st_curve': curve(0x144), 'rs_curve': curve(0x164),
        'lt_curve': curve(0x0DC), 'rt_curve': curve(0x0F8),
        'st_resolution': 12 - min(b(0x32), 4),
        'rs_resolution': 12 - min(b(0x52), 4),
        'st_invert_x': bool(b(0x151)), 'st_invert_y': bool(b(0x152)),
        'st_sensitivity': b(0x153, 50),
        'rs_invert_x': bool(b(0x171)), 'rs_invert_y': bool(b(0x172)),
        'rs_sensitivity': b(0x173, 50),
        'remap': decode_remaps(blob),
    }


def decode_dock(blob: bytes):
    return {
        'dock_auto': bool(blob[0x1F6]) if len(blob) > 0x1F6 else False,
        'dock_brightness': blob[0x1F9] if len(blob) > 0x1F9 else 0,
    }


def parse_input(report, state):
    """Fold one G7 telemetry frame into the shared live-state dictionary."""
    if len(report) <= 60 or report[0] != 0x10 or report[3] != RESPONSE_MARKER \
            or report[4] != INPUT_MARKER:
        return False
    state['lx'], state['ly'], state['rx'], state['ry'] = report[5:9]
    # Bytes 9/10 are the processed (post-remap) buttons.  The controller view
    # depicts the physical controls being pressed, so use the raw/pre-binding
    # group at 55/56 instead.  Its first byte is a hat nibble plus XYAB and its
    # second byte contains shoulders, View/Menu and stick clicks.
    face, meta, extras = report[55], report[56], report[60]
    state['dpad'] = DPAD_HAT.get(face & 0x0F, 'unknown')
    state.update({
        'x': bool(face & 0x10), 'a': bool(face & 0x20),
        'b': bool(face & 0x40), 'y': bool(face & 0x80),
        'lb': bool(meta & 0x01), 'rb': bool(meta & 0x02),
        'view': bool(meta & 0x10), 'menu': bool(meta & 0x20),
        'ls': bool(meta & 0x40), 'rs': bool(meta & 0x80),
        'home': bool(extras & 0x01), 'share': bool(extras & 0x02),
        'l4': bool(extras & 0x08), 'r4': bool(extras & 0x10),
        'm': bool(extras & 0x20),
        'l5': bool(extras & 0x40), 'r5': bool(extras & 0x80),
        'lt': report[12], 'rt': report[13],
        'charging': report[32] == 1, 'battery': min(report[33], 100),
        'mode_ok': True,
    })
    return True


def connection_kind(pid: int):
    """True for wired, False for dongle, and None while changing identity."""
    if pid == PID_WIRED:
        return True
    if pid == PID_DONGLE:
        return False
    return None


def is_standard_input(report: bytes):
    """Whether ``report`` is a 20-byte standard XInput frame, not telemetry."""
    return len(report) == 20 and report[:2] == bytes((0x00, 0x14))


def handshake_packets():
    """Packets used by GameSir's app to leave the 100a HID identity."""
    packets = []
    for index, pair in enumerate(HANDSHAKE_CHUNKS):
        packet = bytearray(8)
        packet[1] = 0x08
        packet[3:5] = pair
        packets.append(bytes(packet))
        if index < len(HANDSHAKE_CHUNKS) - 1:
            packets.append(HANDSHAKE_FLUSH)
    return packets


def send_handshake(handle, interval=0.02, sleep=time.sleep):
    """Send the paced 100a-to-configurable identity transition handshake."""
    for packet in handshake_packets():
        handle.write(packet)
        sleep(interval)


def open_device(bus: int, address: int, sysfs: str):
    """Open a configuration-ready wired controller or wireless dongle."""
    return InterruptHandle.open(VID, CONFIG_PIDS, bus, address, sysfs,
                                IFACE, EP_OUT, EP_IN)


def open_transition_device(bus: int, address: int, sysfs: str):
    """Open only the 100a HID identity for its short transition handshake."""
    return InterruptHandle.open(VID, TRANSITION_PIDS, bus, address, sysfs,
                                IFACE, EP_OUT, EP_IN)


def firmware_from_payload(payload: bytes):
    text = payload[:len(payload) & ~1].decode('utf-16-le', 'replace').split('\0')[0]
    first = text[:4]
    return (f'{int(first[1])}.{int(first[2])}.{int(first[3])}'
            if len(first) == 4 and first.isdigit() else None)


def wait_for_result(result, category, offset, timeout=2.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = result(category, offset)
        if value is not None:
            return value
        time.sleep(0.025)
    return None
