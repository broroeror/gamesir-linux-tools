"""GameSir G7 Pro vendor-USB protocol.

The G7 Pro's configuration identities expose a vendor-class interface rather
than hidraw.  This
module contains only model-specific facts; the shared command queue, native
Linux USB transport, and Qt bridge remain in their existing modules.

Protocol research credit: questionablesyntax/g7ctl's Apache-2.0 ``pyg7``
package.  This is an independent integration for Deadband's transport model.
"""

from __future__ import annotations

import struct
import time

from vendors.gamesir.usb_transport import InterruptHandle

VID = 0x3537
# Shadow Ember -- the edition this integration was built and verified against.
PID_WIRED = 0x109B
PID_DONGLE = 0x109C
# Amazon edition. Reported on issue #10 wired as 10ba with NO hidraw node at all,
# which is the vendor-class signature every other configuration identity has --
# 1022 by contrast comes up with two hidraw interfaces. This project's own G7 Pro
# also reported 10ba, and the original Windows USB capture of the config protocol
# was taken on that identity.
PID_AMZ_WIRED = 0x10BA
# Amazon edition's DONGLE config identity: what its 1022 dongle re-enumerates
# as after SHARE + MENU (dongle firmware 1.00 -> 1.46 across the switch). Same
# two ff/47/d0 interfaces and endpoints as 10ba.
PID_AMZ_DONGLE = 0x10BB
# White Trimode: 1003 on the cable, 1004 on its CHARGING DOCK (reported on #9 by
# an owner, whose pad names itself "GameSir-G7 Pro" in both).
#
# ⚠ 1004 IS SHARED. Mainline xpad also has 3537:1004 in its device table as the
# "GameSir T4 Kaleid", typed XTYPE_XBOX360. So a White Trimode on its dock is
# NAMED "GameSir T4 Kaleid" by the kernel and driven with the Xbox 360 protocol,
# while it actually speaks GIP (ff/47/d0) -- games get no input from it there.
# That is issue #14: "renamed my G7 Pro to a T4 Kaleid, no input outside
# Deadband". The "rename" is the kernel's label for that id; nothing writes a
# pad's identity. (This file previously called 1004 "a different product
# entirely" and blamed #14 on Deadband claiming it. Both were wrong: the
# collision is in xpad's table.) So 1004 is claimed only through is_g7_device(),
# which requires the device to call itself a G7 Pro -- the same product-string
# tie-break 0575 already uses for the Cyclone / idle 8K dongle.
PID_WT_WIRED = 0x1003
PID_WT_DOCK = 0x1004
# Wuchang Edition, identified and hardware-tested by its owner over USB.
PID_WUCHANG_WIRED = 0x10A7
PID_HID = 0x100A
PID_NATIVE = 0x1022
# THE BAR FOR THIS TUPLE: evidence from a real G7 Pro that config reads AND
# writes work on the identity -- never a pattern, never an upstream table alone.
#   109b/109c  write round-trip on @brcly's hardware.
#   10ba       on this project's own pad, 2026-09-30 (firmware 2.3.6): a full
#              read of all four profile banks + dock through the app's own export
#              (46/46 chunks, factory defaults), then an L4 -> A remap written
#              through the GUI and confirmed from OUTSIDE the app -- with Deadband
#              closed the kernel's xpad node emitted BTN_SOUTH for L4, where
#              before the write it emitted nothing -- then an unbind, after which
#              a full-pad diff against the pre-write backup showed zero changes.
#              2026-10-01: 60% written to grip/trigger vibration and dock
#              brightness, read back, restored, full-pad diff zero.
#   10bb       same pad over its dongle, same sequence: 46/46 chunks, identical
#              to the wired read; L4 -> A applied over wireless and confirmed in
#              an external gamepad tester with Deadband released; full-pad diff 0.
#   1003/1004  an owner (#9, 2026-09-15) ran Deadband wired and on the dock and
#              reported every value -- rebinds, sticks, vibration, dock
#              brightness -- read back exactly as set on Windows. That is the
#              read-confirmation #9 publicly set as the bar for re-enabling; the
#              WRITE side rests on the map being identical, now proven on three
#              other identities. Weaker than a watched round-trip, and noted as such.
#   10a7       Wuchang Edition, firmware 5.41, 2026-10-05: all 46 profile/dock
#              chunks read; paddle remaps saved and confirmed working by the
#              owner outside configuration mode; 35 Aim/Tilt writes read back
#              on an inactive profile, then all four profiles and the dock
#              restored byte-for-byte. Owner confirmed gyro-to-right-stick
#              response, input-range sensitivity and all four individual motor
#              tests. Configuration opens directly, without an identity switch.
CONFIG_PIDS = (PID_WIRED, PID_DONGLE, PID_AMZ_WIRED, PID_AMZ_DONGLE,
               PID_WT_WIRED, PID_WT_DOCK, PID_WUCHANG_WIRED)

# Product ids belonging to OTHER GameSir devices, from mainline xpad. An id here
# may appear in CONFIG_PIDS ONLY if it is also in SHARED_PIDS, i.e. is resolved
# per device by is_g7_device(); smoke_test enforces that and exercises the check.
OTHER_PRODUCT_PIDS = {
    0x1004: 'T4 Kaleid',
    0x100F: 'Nova 2 Lite',
    0x1010: 'G7 SE',
}
SHARED_PIDS = {PID_WT_DOCK: 'T4 Kaleid'}


def is_g7_device(pid, product):
    """Is this device a G7 Pro? Only a SHARED id needs asking: it counts as a G7
    Pro when its own product string says so ("GameSir-G7 Pro"). No string means
    no claim -- fail closed, so a real T4 Kaleid is never driven as a G7 Pro."""
    if pid not in SHARED_PIDS:
        return True
    return bool(product) and 'g7 pro' in product.lower().replace('-', ' ')


# Display names for the editions Deadband will configure. The register map is
# NOT branched per edition -- upstream uses one map everywhere and drives ids it
# has never seen, which is consistent with one board in several shells. That
# reasoning makes a new edition PLAUSIBLE; on its own it is not enough to put one
# here.
EDITIONS = {
    PID_WIRED: 'Shadow Ember',
    PID_DONGLE: 'Shadow Ember (dongle)',
    PID_AMZ_WIRED: 'Amazon edition',
    PID_AMZ_DONGLE: 'Amazon edition (dongle)',
    PID_WT_WIRED: 'White Trimode',
    PID_WT_DOCK: 'White Trimode (dock)',
    PID_WUCHANG_WIRED: 'Wuchang Edition (wired)',
}

# Editions seen on a real G7 Pro but with no confirmation that config reads back
# correctly. They get input plus an honest "not supported yet" instead of a bare
# hex id, and no udev grant, since Deadband never opens them. Promoting one means
# the confirmation, a CONFIG_PIDS entry and a 70-gamesir.rules line in one commit.
UNCONFIRMED_EDITIONS = {
    0x105E: 'Zenless Zone Zero (dongle)',
    # Observed locally with standard xpad input. A bounded configuration
    # query returned no data; keep this identity on the input-only path.
    0x10A8: 'USB 10a8 (firmware 5.18)',
}
UNCONFIRMED_PIDS = tuple(UNCONFIRMED_EDITIONS)


def edition_name(pid):
    """A human name for a G7 Pro USB id, or None if we've never seen it."""
    if pid in EDITIONS:
        return EDITIONS[pid]
    return UNCONFIRMED_EDITIONS.get(pid)
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
    0x01A0: 13, 0x01A1: 12, 0x01A2: 12, 0x01A3: 11,
    0x01C2: 13, 0x01C3: 12, 0x01C4: 12, 0x01C5: 11,
}

# G7 Pro captures: g7ctl/PROTOCOL.md, Motion (test72–test77).
# Tilt has a 0x22 stride, except Invert Yaw; Invert Roll is Aim-only.
MOTION_MAP = {
    'enum_unknown_index': -1,
    'act_method': 0x19C, 'act_buttons': (0x19D,),
    'xaxis': 0x19E, 'xaxis_modes': (('Yaw', 1), ('Yaw + Roll', 3)),
    'dz_min': 0x1A0, 'dz_max': 0x1A1, 'dz_wide': False,
    'adz_min': 0x1A2, 'adz_max': 0x1A3, 'adz_wide': False,
    'curve': 0x1A5, 'curve_npts': 3, 'curve_points_offset': 4,
    'curve_strength': False, 'curve_mode_only_custom': True,
    'curve_presets': (
        bytes.fromhex('00 64 00 00 28 28 80 81 d7 d7'),
        bytes.fromhex('01 64 00 00 5e 17 ae 4f e8 a2'),
        bytes.fromhex('02 64 00 00 28 4c 80 81 d7 b3'),
    ),
    'inverts': (('Invert Roll', 0x1B2), ('Invert Y', 0x1B3), ('Invert Yaw', 0x1B4)),
    'tilt_inverts': (None, 0x1D5, 0x1D4),
    'xaxis_gates_inverts': True,
    'xy_scale': 0x1B5, 'output': 0x1B7, 'sens': None, 'tilt_offset': 0x22,
    # Convenience sensitivity control over the captured dz_max endpoint.
    # No independent overall-gain register has been confirmed on this model.
    'range_sensitivity': True,
    'outputs': (('Left Stick', 1), ('Right Stick', 2), ('Button Binds', 3), ('Mouse', 4)),
    'overlap_area': 0x1B8,
    'dir_macros': (0x1B9, 0x1BA, 0x1BB, 0x1BC),
    'direction_empty': 0xFF, 'buttons': GAMEPAD_TARGETS,
    # A section's whole storage block, and what to fill a BLANK one with. Seen on
    # an Amazon edition (10ba, fw 2.36): profile 1's Aim/Tilt blocks were zeros
    # apart from the deadzones (how they got that way is unknown). Writing single
    # fields into such a block leaves the axis mode and curve invalid, and the
    # firmware ignores the output setting (gyro drove the LEFT stick with Right
    # Stick selected, vertical axis only with Left). Writing this complete block
    # made the same pad aim with the right stick on both axes. Values are the
    # Wuchang's stored defaults (tests/test_motion.py CAPTURE) with activation
    # set to Off, so initialising never switches the gyro on by itself.
    'block_len': 0x22,
    'default_blocks': {
        'Aim': bytes.fromhex('00 ff 03 01 00 64 00 64 01 00 64 00 00 29 29 80 80 d6 d6 '
                             'ff ff 01 00 00 00 32 32 01 00 ff ff ff ff ff'),
        'Tilt': bytes.fromhex('00 ff 02 01 05 64 00 64 01 00 64 00 00 28 29 81 80 d7 d6 '
                              'ff ff 01 00 00 00 32 32 00 00 ff ff ff ff ff'),
    },
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
        'motion': decode_motion(blob),
    }


def motion_fields():
    """Documented scalar fields, including Tilt's two exceptions."""
    mp = MOTION_MAP
    common = ('act_method', 'xaxis', 'dz_min', 'dz_max', 'adz_min', 'adz_max',
              'xy_scale', 'output', 'overlap_area')
    for section, off in (('Aim', 0), ('Tilt', mp['tilt_offset'])):
        fields = {key: mp[key] + off for key in common}
        fields['act_button'] = mp['act_buttons'][0] + off
        for key, addr in zip(('up', 'down', 'left', 'right'), mp['dir_macros']):
            fields['direction_' + key] = addr + off
        inv = mp['tilt_inverts'] if off else tuple(a for _n, a in mp['inverts'])
        for key, addr in zip(('invert_roll', 'invert_y', 'invert_yaw'), inv):
            if addr is not None:
                fields[key] = addr
        yield section, fields, mp['curve'] + off


def decode_motion(blob):
    """Lossless documented motion values for schema-4 exports (raw enum codes)."""
    result = {}
    for section, fields, curve in motion_fields():
        result[section] = {key: blob[addr] for key, addr in fields.items()}
        result[section]['curve'] = list(blob[curve:curve + 10])
    return result


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
    # The extras byte is 57, NOT 60 -- an off-by-three on the index, not a
    # different report format: byte 57's bit layout (home 0x01, share 0x02,
    # l4 0x08, r4 0x10, m 0x20) matches what the old code expected at byte 60
    # exactly. L5/R5 are the exception, sitting in byte 58 at 0x01/0x02 rather
    # than 57's high bits. All measured on a fw 2.36 Amazon-edition pad; byte 56
    # (lb/rb/view/menu/ls/rs) was already correct, confirmed via LB.
    #
    # Byte 60 is ANALOG. Byte 60 is an ANALOG value -- measured
    # on a fw 2.36 Amazon-edition pad it runs 0 -> 80 -> 186 -> 255 as RT is
    # pulled, so reading it as a bitfield lit L4/R4/L5/R5 together on any firm
    # trigger pull, while the real paddles lit nothing. Byte 9 is the POST-remap
    # button state (a paddle bound to A shows up there as A); 55/56 stay the
    # pre-remap group so the diagram keeps showing physical controls.
    face, meta = report[55], report[56]
    pad_a, pad_b = report[57], report[58]
    state['dpad'] = DPAD_HAT.get(face & 0x0F, 'unknown')
    state.update({
        'x': bool(face & 0x10), 'a': bool(face & 0x20),
        'b': bool(face & 0x40), 'y': bool(face & 0x80),
        'lb': bool(meta & 0x01), 'rb': bool(meta & 0x02),
        'view': bool(meta & 0x10), 'menu': bool(meta & 0x20),
        'ls': bool(meta & 0x40), 'rs': bool(meta & 0x80),
        'home': bool(pad_a & 0x01), 'share': bool(pad_a & 0x02),
        'l4': bool(pad_a & 0x08), 'r4': bool(pad_a & 0x10),
        'm': bool(pad_a & 0x20),
        'l5': bool(pad_b & 0x01), 'r5': bool(pad_b & 0x02),
        'lt': report[12], 'rt': report[13],
        'charging': report[32] == 1, 'battery': min(report[33], 100),
        'mode_ok': True,
        # Report 0x10/E0 carries six signed little-endian sensor channels.
        # Scale factors and the physical axis orientation are not calibrated.
        # Raw 10a7/fw 5.41 capture, flat and still: bytes 17..22 have
        # median (0, 0, 0); bytes 23..28 retain the gravity vector.
        'gyro': struct.unpack_from('<3h', report, 17),
        'accel': struct.unpack_from('<3h', report, 23),
        'imu_time': time.monotonic(),
    })
    return True


# Which config identities are the WIRED face and which are the dongle. Kept as
# sets rather than branches in connection_kind() so smoke_test can assert every
# CONFIG_PID appears in exactly one: this table failed to grow when 10ba was
# added, so Amazon-edition owners got a blank wired/wireless hint (issue #10).
# That is the third table in this project to drift from CONFIG_PIDS, hence the
# check instead of the good intention.
WIRED_PIDS = (PID_WIRED, PID_AMZ_WIRED, PID_WT_WIRED, PID_WUCHANG_WIRED)
DONGLE_PIDS = (PID_DONGLE, PID_AMZ_DONGLE, PID_WT_DOCK)    # the dock is the wireless link


def connection_kind(pid: int):
    """True for wired, False for dongle, and None while changing identity."""
    if pid in WIRED_PIDS:
        return True
    if pid in DONGLE_PIDS:
        return False
    return None


def is_standard_input(report: bytes):
    """Whether ``report`` is a 20-byte standard XInput frame, not telemetry."""
    return len(report) == 20 and report[:2] == bytes((0x00, 0x14))


def rumble_packet(sequence: int, left: int, right: int,
                  trigger_left: int = 0, trigger_right: int = 0):
    """GIP direct four-motor command: 400 ms, no repeats.

    MS-GIPUSB 3.1.5.6.1 specifies percentages and a duration in 10 ms units.
    Unlike vendor commands this is a 13-byte GIP packet, not a 64-byte report.
    Zero duration cancels all motors; it is also used for the explicit stop.
    Payload order is LT, RT, left grip, right grip, as in xone's
    driver/gamepad.c:gip_gamepad_pkt_rumble. Enable all four channels so
    zero amplitudes also silence motors not selected for an isolated test.
    """
    amplitudes = [max(0, min(255, int(v)))
                  for v in (trigger_left, trigger_right, left, right)]
    percentages = [(v * 100 + 127) // 255 for v in amplitudes]
    return bytes((0x09, 0x00, sequence, 0x09, 0x00, 0x0F,
                  *percentages, 40 if any(percentages) else 0, 0x00, 0x00))


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
