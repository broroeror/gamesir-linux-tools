"""GameSir Super Nova -- USB identities and what is known of its protocol.

Recognised, not yet configured. GameSir's own app calls this pad "T4NPro"
(display name "Super Nova", key `NovaPro`) and ships three editions of it --
Black, Hatsune Miku and YYS -- all as DeviceTypeId 3.

IDENTITIES, from GameSir Connect 1.16.7's device table (main.js, Model "T4NPro"):

    3537:100e   wired (USB-C)   config collection on usage page 0xffff
    3537:103e   2.4 GHz dongle  config collection on usage page 0xfff0

⚠ 103e IS SHARED. The same table gives 103e as the dongle identity of the
T3 Pro (DeviceTypeId 0) too, and the dongle names itself only "GameSir-Dongle",
so the USB id alone cannot say which pad is paired. The pad answers
get_device_info with its type in the first data byte (03 = Super Nova; see
device_type_from_info), which is how GameSir's app tells them apart and how
any write path here must too.

OVER THE CABLE (observed 2026-10-10; wired configuration deliberately shelved):
    plugged in from OFF          -> 054c:09cc, a DualShock 4: one plain HID
                                    interface (EP 0x81 in / 0x02 out), no
                                    GameSir channel; GameSir Connect doesn't list it
    plugged in while ON in Xbox  -> 3537:100e, XInput only (xusb22 binds the
    mode over the dongle            whole device): no HID interface 1, no 0xffa0
                                    collection -- the dongle's config path is absent
  The mode is the pad's live state, not a stored setting: View + Menu does not
  change it once the cable is in, and the next cold plug-in is a DS4 again.
  Whether GameSir configures 100e at all (it lists usage page 0xffff for it,
  i.e. no HID page) was never captured. 100e stays input-only.

OBSERVED ON A REAL DONGLE (Windows device manager, 2026-10-10, rev 0110):
    interface 0   XInput (Xbox 360)          -> xpad on Linux; input works
    interface 1   HID: keyboard, mouse, consumer control, and a vendor
                  collection on usage page 0xffa0 (usage 1)

PROTOCOL -- decoded statically from GameSir's DLL, then CONFIRMED on the wire
by six USBPcap captures of GameSir Connect 1.16.7 driving a real Super Nova
over its dongle (2026-10-10; captures/0[1-6]_*.pcapng). Every request in the
captures decoded to a COMMANDS entry; none was unknown.

  Configuration is done by GameSir's native sapjoyuniapis_x86_v1.0.16.dll
  (sha256 4d24f4cb...5b4005), which reaches the pad with plain HID
  ReadFile/WriteFile -- reproducible over hidraw. Each command is a C++ class
  whose constructor stores a 16-bit code; one shared serializer
  (FUN_10001ce0) frames every request:

      request  [0x07] [len = payload + 3] [group] [op] [payload ...]
               (len counts every byte after the report id, itself included;
               0x05 replaces 0x07 for the firmware-update group only).
               Sent as a 32-byte interrupt OUT report on interface 1
               (endpoint 0x01), zero padded.
      get reply  [0x06] [len] [group] [op] [data ...]
      set reply  [0x06] 04    [group] [op] [status]   status 0 = success
               Both arrive as 64-byte interrupt IN reports on endpoint 0x82.

  A set's payload is byte-for-byte the data its get returns, so writes are
  read-modify-write; the app follows every set with save_config_page
  (07 03 08 03). LAYOUTS below gives each field's offset, every one of them
  pinned by a single-setting capture or by the app's own model converters.

  Corroborated independently by the app's JavaScript, which writes the
  vibration test as `07 07 0a 04 <left> <right> 00 00` (COMMANDS
  'set_vibrate_test', 4-byte payload). Tried from Linux on a real pad
  (2026-10-10): the pad answers status 0 and plays ONE short pulse that stops by
  itself; the strength follows the value as a percentage (0a weak, 64 strong);
  but either byte drives BOTH motors, so it previews a strength, not a side;
  all zeros does nothing (capture 02 only ever shows that form). It stores
  nothing: a backup diffed identical afterwards. The app also listens on the 0xffa0 collection
  for two unsolicited reports in the same framing:
      06 1a 0a 03 ...   live pad state (sticks, buttons, RGB triplets)
      06 05 0a 0d <f>   "profile changed on the pad"; bit 4 keys, 1 sticks,
                        2 triggers, 5 vibration, 6/7 lighting

  The app's defaults: one configuration page, stick deadzone 5-100, trigger
  deadzone 5-95, linear curves, vibration 75/75, motion off.

  VENDOR QUIRK worth not copying: the app re-derives every colour through HSV
  floats on each write, so one ABXY hue drifts 0x2a -> 0x29 every time ANY
  lighting-adjacent setting is saved (visible in captures 05 and 06). Writing
  back the bytes that were read avoids it.

Nothing is written to this pad until the bar every other model here cleared is
met on a Super Nova, FROM LINUX: a read/write round trip on real hardware,
confirmed from outside the app, restored with a zero diff. The wire format is
now known; that Linux round trip is what remains.
"""

VID = 0x3537
PID_WIRED = 0x100E      # seen on a real pad, but only when already on in Xbox mode
PID_WIRED_DS4 = (0x054C, 0x09CC)   # what the cable gives from a cold plug-in
PID_DONGLE = 0x103E     # observed 2026-10-10; shared with the T3 Pro's dongle

# GameSir's DeviceTypeId for the Super Nova, as its pad reports it.
DEVICE_TYPE_ID = 3

# The live / notification HID collection on interface 1 (observed on the dongle).
LIVE_USAGE_PAGE = 0xFFA0
LIVE_INTERFACE = 1
REPORT_OUT = 0x07
REPORT_OUT_UPDATE = 0x05   # firmware-update group only; never sent by this project
REPORT_IN = 0x06
UPDATE_GROUP = 0x53

# Every command the vendor DLL can send, as (group, op). Extracted from each
# command class's constructor in sapjoyuniapis_x86_v1.0.16.dll; the address is
# where that constructor stores the code, so each entry can be re-checked.
COMMANDS = {
    'set_macro_step':                  (0x01, 0x01),   # 0x100058ca
    'get_macro_step':                  (0x01, 0x02),   # 0x10005a3e
    'set_stick_curve':                 (0x02, 0x01),   # 0x10005c9b
    'get_stick_curve':                 (0x02, 0x02),   # 0x10005e1e
    'set_stick_mapping':               (0x02, 0x03),   # 0x1000608a
    'get_stick_mapping':               (0x02, 0x04),   # 0x10006201
    'set_trigger_param':               (0x03, 0x01),   # 0x1000637a
    'get_trigger_param':               (0x03, 0x02),   # 0x100064f1
    'set_motion_curve':                (0x04, 0x01),   # 0x1000670d
    'get_motion_curve':                (0x04, 0x02),   # 0x1000688e
    'set_motion_mapping':              (0x04, 0x03),   # 0x10006aba
    'get_motion_mapping':              (0x04, 0x04),   # 0x10006c2a
    'set_key_mapping':                 (0x05, 0x01),   # 0x10006dff
    'get_key_mapping':                 (0x05, 0x02),   # 0x10006f7e
    'set_vibrate_param':               (0x06, 0x01),   # 0x100071b8
    'get_vibrate_param':               (0x06, 0x02),   # 0x100073ea
    'set_light_param':                 (0x07, 0x01),   # 0x10007548
    'get_light_param':                 (0x07, 0x02),   # 0x1000771a
    'set_light_color':                 (0x07, 0x03),   # 0x100078d5
    'get_light_color':                 (0x07, 0x04),   # 0x10007ae3
    'set_config_page':                 (0x08, 0x01),   # 0x10007cba
    'get_config_page':                 (0x08, 0x02),   # 0x10007e3a
    'save_config_page':                (0x08, 0x03),   # 0x10007f99
    'reset_config_page':               (0x08, 0x04),   # 0x100080f9
    'set_dpad_param':                  (0x09, 0x01),   # 0x10008258
    'get_dpad_param':                  (0x09, 0x02),   # 0x1000848a
    'set_device_type':                 (0x09, 0x03),   # 0x100085e8
    'get_device_type':                 (0x09, 0x04),   # 0x1000878a
    'get_device_info':                 (0x0A, 0x01),   # 0x100088ea
    'set_gamepad_state_report':        (0x0A, 0x02),   # 0x10008a4a
    'set_vibrate_test':                (0x0A, 0x04),   # 0x10008bc8
    'set_stick_trigger_calibration':   (0x0A, 0x05),   # 0x10008dba
    'get_stick_trigger_calibration':   (0x0A, 0x06),   # 0x10008f3a
    'set_gyro_calibration':            (0x0A, 0x07),   # 0x1000909a
    'get_gyro_calibration':            (0x0A, 0x08),   # 0x1000921a
    'set_light_color_test':            (0x0A, 0x09),   # 0x10009378
    'set_abxy_rotation_test':          (0x0A, 0x0A),   # 0x1000956a
    'exchange_bt_address':             (0x0A, 0x0B),   # 0x1000a043
    'exchange_bt_link_key':            (0x0A, 0x0C),   # 0x1000a206
    'get_version':                     (0x84, 0x01),   # 0x100098bd
    'get_mac_address':                 (0x84, 0x02),   # 0x10009a8d
    'set_isp_mode':                    (0x84, 0x03),   # 0x10009c57
    'set_pair_mode':                   (0x84, 0x04),   # 0x10009dc7
    'set_pair_info':                   (0x84, 0x0E),   # 0x1000a690
    'firmware_update':                 (0x53, 0x11),   # 0x1000a405 + 4 more
}

# Unsolicited reports the pad sends on the live collection.
NOTIFY_GAMEPAD_STATE = (0x0A, 0x03)
NOTIFY_PROFILE_CHANGED = (0x0A, 0x0D)

# Commands that can brick the pad, wipe its calibration or break pairing.
# encode_request() refuses them outright: this project has no reason to send
# any of these, and a wrong guess is not recoverable from Linux.
FORBIDDEN = frozenset((
    'set_isp_mode', 'firmware_update', 'set_pair_mode', 'set_pair_info',
    'exchange_bt_address', 'exchange_bt_link_key', 'set_device_type',
    'set_stick_trigger_calibration', 'set_gyro_calibration',
    'reset_config_page',
))
_FORBIDDEN_CODES = frozenset(COMMANDS[n] for n in FORBIDDEN)

# Reads, safe to send for probing: they change nothing on the pad.
READ_ONLY = frozenset(n for n in COMMANDS if n.startswith('get_'))


def encode_request(group, op, payload=b''):
    """Frame one command the way the vendor DLL's serializer does."""
    if (group, op) in _FORBIDDEN_CODES or group == UPDATE_GROUP:
        raise ValueError(f'command {group:#04x}/{op:#04x} is forbidden')
    payload = bytes(payload)
    if len(payload) + 3 > 0xFF:
        raise ValueError('payload too long')
    return bytes((REPORT_OUT, len(payload) + 3, group, op)) + payload


def decode_reply(report):
    """(group, op, body) for a reply/notification on report 0x06, or None for
    anything else. A get's body is its data; a set's body is one status byte
    (see set_succeeded)."""
    report = bytes(report)
    if len(report) < 4 or report[0] != REPORT_IN or report[1] < 3:
        return None
    end = min(len(report), 1 + report[1])     # len counts all but the report id
    return report[2], report[3], report[4:end]


def set_succeeded(body):
    """A set's reply body is a single status byte, 0 on success."""
    return len(body) == 1 and body[0] == 0


def device_type_from_info(body):
    """GameSir DeviceTypeId from a get_device_info body (3 = Super Nova,
    0 = T3 Pro). Observed body: 03 01 06 <6-byte address> <battery> 00."""
    return body[0] if body else None


# get_device_info body byte 9: battery percent, or 0xff while charging (the pad
# gives no percentage then). Logged on the dongle 2026-10-10: 100 -> 96 -> 94
# over ~3 h of play, then ff with the pad on a charger. Byte 10 stayed 0 in both.
INFO_BATTERY = 9
INFO_BATTERY_CHARGING = 0xFF


def battery_from_info(body):
    """(percent or None, charging) from a get_device_info body. None when the
    body is too short or the byte is neither 0..100 nor the charging marker."""
    if len(body) <= INFO_BATTERY:
        return None, False
    value = body[INFO_BATTERY]
    if value == INFO_BATTERY_CHARGING:
        return None, True
    return (value if value <= 100 else None), False


# --- payload layouts -------------------------------------------------------
# Byte offsets inside a get's data == inside the matching set's payload. Each
# is pinned by a single-setting capture (02..06) and/or by GameSir Connect's
# own converters (main.js getDeviceModel: pl / fl / _l / ll / gl).

# get/set_vibrate_param (6 bytes). Percent, the app's level n = 25 * n
# (capture 02: left 75 -> 50 -> 25 sent as 4b -> 32 -> 19). The app writes
# bytes 4-5 as 0 although the pad reads them back as 75.
VIB_LEFT, VIB_RIGHT = 0, 1
VIB_LEN = 6

# get/set_key_mapping (16 bytes; get's request payload is [page, key]).
#   0 page   1 key   2 trigger   3..5 colour h,s,v   6 mapping key (source)
#   7 toggle   8 turbo mode   9 turbo times (app writes 1 when off; factory 0)
#  10 mapping type (0 vacant, 1 gamepad, ...)   11 key count   12..15 codes
# Capture 03 (A -> B) changed byte 9 0 -> 1 and byte 12 0x01 -> 0x00.
KEY_SOURCE, KEY_TURBO_TIMES, KEY_TYPE, KEY_COUNT, KEY_CODES = 6, 9, 10, 11, 12
KEY_LEN = 16
KEY_TYPE_VACANT, KEY_TYPE_GAMEPAD = 0, 1
# Button codes, GameSir's SAPJoyUniKey (main.js); Xbox naming in comments.
KEYS = {
    'CIR': 0x00,   # B
    'CRO': 0x01,   # A
    'TRI': 0x02,   # Y
    'SQU': 0x03,   # X
    'L1': 0x04, 'L2': 0x05, 'L3': 0x06, 'R1': 0x07, 'R2': 0x08, 'R3': 0x09,
    'Sel': 0x0A, 'Sta': 0x0B, 'Left': 0x0C, 'Right': 0x0D, 'Up': 0x0E,
    'Under': 0x0F, 'FL1': 0x24, 'FR1': 0x25, 'T1': 0x26, 'T2': 0x27,
    'T3': 0x28, 'C1': 0x29, 'C2': 0x2A, 'C3': 0x2B, 'C4': 0x2C, 'Camera': 0x2D,
}

# Both curve blocks carry the app's 10-point list (main.js fl/pl
# getDeviceModel): begin dz, begin anti-dz, x0,y0, x1,y1, x2,y2, end dz,
# end anti-dz -- as offsets from the block's POINTS start:
P_DZ_BEGIN, P_ADZ_BEGIN, P_CURVE_X, P_DZ_END, P_ADZ_END = 0, 1, (2, 4, 6), 8, 9

# get/set_trigger_param (16 bytes; request payload [trigger], 0 = LT, 1 = RT)
#   0 trigger   1 hair type (0 linear)   2 hair begin   3 hair end
#   4..13 points   14 curve type   15 curvature
# Default read: 00 00 0a 14 | 05 00 13 10 32 32 51 54 5f 64 | 00 32
# Capture 05 (RT deadzone 5 -> 4 -> 7 -> 10): byte 4 05 -> 04 -> 07 -> 0a.
TRIG_POINTS = 4
TRIG_LEN = 16

# get/set_stick_curve (21 bytes; request payload [stick, page], 0 = left)
#   0 stick 1 page 2 key 3 trigger 4..6 colour h,s,v 7 type (raw/circle)
#   8 axis ratio   9..18 points   19 curve type   20 curvature
# Default read: 00 00 00 00 00 00 00 01 32 | 05 00 14 10 35 32 55 54 64 64 | 00 32
# Capture 04 (left deadzone 5 -> 3 -> 10): byte 9 05 -> 03 -> 0a.
STICK_POINTS = 9
STICK_LEN = 21

# get/set_stick_mapping (12 bytes; request payload [stick]) -- the app rewrites
# it unchanged around every stick curve write (capture 04). Layout per main.js
# SAPJOYUNI_STICKMAPPING: stick, angle, inner range, outer range, dir x, dir y,
# mode, state, mice sens x, mice sens y, mice dir x, mice dir y.
# Default read: 00 28 28 50 00 00 00 01 32 32 00 00
STICKMAP_LEN = 12

# get/set_light_param (3 bytes): brightness, speed, mode. Capture 06:
# brightness 0x2a -> 0x4f, and the panel colour's V byte follows it.
LIGHT_BRIGHTNESS, LIGHT_SPEED, LIGHT_MODE = 0, 1, 2
LIGHT_LEN = 3


# The pad's factory 10-point lists (capture 01: both sticks alike, both
# triggers alike): dz, anti-dz, (x0,y0) (x1,y1) (x2,y2), end dz, end anti-dz.
FACTORY_POINTS = {
    STICK_POINTS: (5, 0, 20, 16, 53, 50, 85, 84, 100, 100),
    TRIG_POINTS: (5, 0, 19, 16, 50, 50, 81, 84, 95, 100),
}
# How far a curve's normalised x may sit from the factory's and still count
# as the factory curve (drifted by rounding, not shaped by a user). Linux,
# 2026-10-10: several applies rescaling from the pad's own state left the left
# stick at x 18/53/87 for the factory 20/53/85 -- 0.02 off in normalised x.
FACTORY_SHAPE_TOLERANCE = 0.05


def _round_half_up(x):
    return int(x + 0.5)


def _rescaled(x, dz_from, dz_to, end):
    return _round_half_up(dz_to + (x - dz_from) * (end - dz_to) / (end - dz_from))


def has_factory_shape(data, points_at):
    """Is this block's curve the factory one, possibly rescaled to another
    deadzone and drifted by rounding? Every y, anti-deadzone and the end
    deadzone must equal the factory's exactly (none of them is ever rescaled),
    and each x, normalised over the live range, must be within the tolerance."""
    ref = FACTORY_POINTS.get(points_at)
    if ref is None:
        return False
    pts = data[points_at:points_at + 10]
    if any(pts[i] != ref[i] for i in (P_ADZ_BEGIN, 3, 5, 7, P_DZ_END, P_ADZ_END)):
        return False
    dz, end = pts[P_DZ_BEGIN], pts[P_DZ_END]
    rdz = ref[P_DZ_BEGIN]
    if dz >= end:
        return False
    return all(abs((pts[ix] - dz) / (end - dz) - (ref[ix] - rdz) / (end - rdz))
               <= FACTORY_SHAPE_TOLERANCE for ix in P_CURVE_X)


def with_begin_deadzone(data, points_at, new_dz):
    """Copy of a stick/trigger curve block with its begin deadzone moved,
    rescaling the three curve x coordinates the way GameSir's app does:

        x' = round_half_up(dz + (x - dz_from) * (end - dz) / (end - dz_from))

    The x and dz_from it rescales from:
      * a factory-shaped curve (has_factory_shape): the FACTORY points, so
        repeated changes never accumulate rounding, a return to the factory
        deadzone gives back the factory curve exactly, and a curve already
        drifted is repaired. From the factory curve this is exactly what
        GameSir's app sends: all 18 x values in captures 04 and 05.
      * any other curve (shaped in GameSir's app): the block as read, which is
        what GameSir's app does for every curve.
    y and every other byte are copied unchanged."""
    out = bytearray(data)
    p = points_at
    old, end = out[p + P_DZ_BEGIN], out[p + P_DZ_END]
    if not 0 <= new_dz < end or old >= end:
        raise ValueError(f'deadzone {new_dz} must be below the end ({end})')
    if has_factory_shape(data, p):
        ref = FACTORY_POINTS[p]
        dz_from = ref[P_DZ_BEGIN]
        src_x = {ix: ref[ix] for ix in P_CURVE_X}
    else:
        dz_from = old
        src_x = {ix: data[p + ix] for ix in P_CURVE_X}
    out[p + P_DZ_BEGIN] = new_dz
    for ix in P_CURVE_X:
        out[p + ix] = _rescaled(src_x[ix], dz_from, new_dz, end)
    return bytes(out)


# --- the app's view: the four features with verified writes ----------------
# Buttons the app lets a user rebind, by the names the 'cyclone' diagram uses
# (controller_profile REMAP_SLOTS), mapped to GameSir's key codes. This is
# GameSir Connect's own T4NPro CanMappingKeys list; FL1/FR1 are the back
# buttons (its Mapping table calls them L4/R4).
REMAP_SOURCES = (
    ('A', KEYS['CRO']), ('B', KEYS['CIR']), ('X', KEYS['SQU']), ('Y', KEYS['TRI']),
    ('LB', KEYS['L1']), ('LT', KEYS['L2']), ('LS', KEYS['L3']),
    ('RB', KEYS['R1']), ('RT', KEYS['R2']), ('RS', KEYS['R3']),
    ('Dpad Up', KEYS['Up']), ('Dpad Down', KEYS['Under']),
    ('Dpad Left', KEYS['Left']), ('Dpad Right', KEYS['Right']),
    ('L4', KEYS['FL1']), ('R4', KEYS['FR1']),
    ('View', KEYS['Sel']), ('Menu', KEYS['Sta']), ('Capture', KEYS['Camera']),
)
# What a button can be mapped TO: other gamepad buttons only (GameSir's
# MappingList minus NC/"disabled", whose write shape is unverified). The code
# stored in the app's config is GameSir's key code itself.
REMAP_TARGETS = tuple((n, c) for n, c in REMAP_SOURCES if n not in ('L4', 'R4'))

# Virtual addresses: the app stages edits by (bank, addr), so the profile
# gives each feature an address in a namespace only editor.py decodes. They
# never reach the wire. High byte = command group, low byte = index.
VADDR_STICK_DZ = 0x0200          # + 0 left, + 1 right (RS_OFFSET = 1)
VADDR_TRIG_DZ = 0x0300           # + 0 LT, + 1 RT (RT_OFFSET = 1)
VADDR_KEY = 0x0500               # | key code
VADDR_VIB = 0x0600               # + VIB_LEFT / VIB_RIGHT


KEY_TURBO_MODE = 8
KEY_TURBO_OFF = 0


def with_key_target(data, target):
    """Copy of a key-mapping block mapped to one gamepad button: type gamepad,
    one code.

    Turbo times: a remap to ANOTHER button writes 1, as GameSir's app does
    (capture 03) and as every write verified on hardware did. Mapping a button
    back to ITSELF with turbo off writes the factory 0 instead -- the value every
    untouched button carries (capture 01) -- so a reset button is byte-identical
    to one never remapped, where GameSir's app would leave 1 behind."""
    out = bytearray(data)
    own = out[KEY_SOURCE]
    out[KEY_TYPE] = KEY_TYPE_GAMEPAD
    out[KEY_COUNT] = 1
    if target == own and out[KEY_TURBO_MODE] == KEY_TURBO_OFF:
        out[KEY_TURBO_TIMES] = 0
    else:
        out[KEY_TURBO_TIMES] = max(out[KEY_TURBO_TIMES], 1)
    out[KEY_CODES:KEY_CODES + 4] = bytes((target, 0, 0, 0))
    return bytes(out)

# The dongle is the one identity with writes round-tripped on hardware from
# Linux (2026-10-10; see CHANGELOG.md): remap, vibration, trigger and stick
# deadzones, each verified outside the app and restored with a zero diff. It is
# shared with the T3 Pro, so a session must confirm device type 3 first.
CONFIG_PIDS = (PID_DONGLE,)
# Named so the app and the diagnostics can say "Super Nova" instead of a bare
# hex id. Never opened for configuration, never written. The wired id has not
# been seen on a real pad.
INPUT_ONLY_PIDS = (PID_WIRED,)
ALL_PIDS = CONFIG_PIDS + INPUT_ONLY_PIDS
SHARED_PIDS = {PID_DONGLE: 'T3 Pro'}

IDENTITY_NAMES = {
    PID_WIRED: 'wired',
    PID_DONGLE: 'dongle',
}


def identity_name(pid):
    """'wired' / 'dongle' for a known Super Nova id, else None."""
    return IDENTITY_NAMES.get(pid)
