"""
GameSir Nova 2 Lite (T4N2) — vendor HID protocol (0xFF7A)
=========================================================
Reverse-engineered from GameSir Connect's `sapjoyuniapis_t4n2_x86_v2604013.dll`
and hardware-verified on a physical Nova 2 Lite (3537:100f wired, fw 1.82).

Transport & Node Selection
--------------------------
The Nova 2 Lite enumerates as:
  * 3537:100f — wired USB ("GameSir-Nova 2 Lite")
  * 3537:1098 — 2.4 GHz wireless dongle ("GameSir-Nova 2 Lite Dongle")

On Linux it exposes multiple HID interfaces; the vendor command and live-input
channel is the interface whose HID report descriptor declares Usage Page 0xFF7A
(`06 7a ff`) with 64-byte unnumbered Input/Output reports. Because the descriptor
declares no Report IDs:
  * Output writes via hidapi take a leading 0x00 report-ID byte + 64 payload
    bytes (65 bytes total).
  * Input reads via hidapi/hidraw return 64 bytes starting directly at byte 0
    (the command opcode), shifted by -1 relative to Windows ReadFile buffers.

Checksum
--------
For an N-byte command packet `buf[0..N-1]`, `buf[N-1] = sum(buf[0:N-1]) & 0xFF`,
padded with trailing zeros to 64 bytes.
"""

import os
import struct
import time

import hidcompat as hid
import vendors.gamesir.config as _cy

VID = 0x3537
PID_WIRED = 0x100F
PID_DONGLE = 0x1098

CONFIG_PIDS = (PID_WIRED, PID_DONGLE)
WIRED_PIDS = (PID_WIRED,)
DONGLE_PIDS = (PID_DONGLE,)

VENDOR_USAGE_PAGE_BYTES = b'\x06\x7a\xff'
REPORT_LEN = 64

# --- Register address map (synthetic bank-1 layout matching Cyclone offsets) ---
VIB_L = _cy.VIB_L               # 0x0020
VIB_R = _cy.VIB_R               # 0x0021
DPAD_SWAP = 0x002B              # 0x23 0x04
DPAD_LOCK = 0x002D              # 0x23 0x01

LT_DZ_MIN = _cy.LT_DZ_MIN       # 0x01f1
LT_DZ_MAX = _cy.LT_DZ_MAX       # 0x01f2
LT_HAIR = _cy.LT_HAIR           # 0x01fa
RT_OFFSET = _cy.RT_OFFSET       # 0x1c
RT_DZ_MIN = _cy.RT_DZ_MIN       # 0x020d
RT_DZ_MAX = _cy.RT_DZ_MAX       # 0x020e
RT_HAIR = _cy.RT_HAIR           # 0x0216

ST_TRAJ = _cy.ST_TRAJ           # 0x0227
ST_DZ_MIN = _cy.ST_DZ_MIN       # 0x0229
ST_DZ_MAX = _cy.ST_DZ_MAX       # 0x022a
ST_ADZ_MIN = _cy.ST_ADZ_MIN     # 0x022b
ST_ADZ_MAX = _cy.ST_ADZ_MAX     # 0x022c
ST_CURVE = _cy.ST_CURVE         # 0x022e
RS_OFFSET = _cy.RS_OFFSET       # 0x20
RS_TRAJ = _cy.RS_TRAJ           # 0x0247
RS_DZ_MIN = _cy.RS_DZ_MIN       # 0x0249
RS_DZ_MAX = _cy.RS_DZ_MAX       # 0x024a
RS_ADZ_MIN = _cy.RS_ADZ_MIN     # 0x024b
RS_ADZ_MAX = _cy.RS_ADZ_MAX     # 0x024c
RS_CURVE = _cy.RS_CURVE         # 0x024e

REMAP_SLOTS = tuple(_cy.REMAP_SLOTS)
GAMEPAD_TARGETS = tuple(_cy.REMAP_TARGETS[:-1]) + (
    ('View', 0x0E),
    ('Menu', 0x0F),
    ('Capture', 0x10),
    _cy.REMAP_TARGETS[-1],      # ('Disabled', 0xFF)
)

# T4N2 hardware button codes used by 0xF1 (Get/SetGamepadKeyMapping)
_SLOT_TO_HW_KEY = {
    'Dpad Up':    0xB0,
    'Dpad Down':  0xB1,
    'Dpad Left':  0xB2,
    'Dpad Right': 0xB3,
    'A':          0xB4,
    'B':          0xB5,
    'X':          0xB7,
    'Y':          0xB8,
    'LB':         0xBA,
    'RB':         0xBB,
    'View':       0xBC,
    'Menu':       0xBD,
    'LT':         0xBE,
    'RT':         0xBF,
    'LS':         0xC0,
    'RS':         0xC1,
    'L4':         0xCB,
    'R4':         0xCD,
    'Capture':    0xD4,
}
_HW_KEY_DISABLED = 0xD2

_ADDR_TO_SLOT = {addr: name for name, addr in REMAP_SLOTS}
_ADDR_TO_HW_KEY = {addr: _SLOT_TO_HW_KEY[name] for name, addr in REMAP_SLOTS}
_TARGET_CODE_TO_NAME = {code: name for name, code in GAMEPAD_TARGETS if code != 0xFF}
_TARGET_CODE_TO_HW = {
    code: _SLOT_TO_HW_KEY[name]
    for name, code in GAMEPAD_TARGETS
    if code != 0xFF and name in _SLOT_TO_HW_KEY
}
_HW_TO_TARGET_CODE = {hw: code for code, hw in _TARGET_CODE_TO_HW.items()}

# Cached composite state from hardware reads, used when patching individual
# fields inside composite T4N2 packets (0xF0 stick config, 0x25 vibration,
# 0x21 hair trigger).
_stick_state = {
    1: [5, 0, 25, 25, 50, 50, 75, 75, 100, 100, 0, 100],
    2: [5, 0, 25, 25, 50, 50, 75, 75, 100, 100, 0, 100],
}
_curve_ui_cache = {1: None, 2: None}
_vib_state = [75, 75]
_hair_hw_state = [2, 2]   # 1 = On, 2 = Off
_hair_ui_cache = {
    LT_HAIR: [0x00, 0x0A, 0x5A],
    RT_HAIR: [0x00, 0x0A, 0x5A],
}


def reset_session_state():
    """Reset cached composite packet state on device bind/disconnect."""
    _stick_state[1] = [5, 0, 25, 25, 50, 50, 75, 75, 100, 100, 0, 100]
    _stick_state[2] = [5, 0, 25, 25, 50, 50, 75, 75, 100, 100, 0, 100]
    _curve_ui_cache[1] = None
    _curve_ui_cache[2] = None
    _vib_state[:] = [75, 75]
    _hair_hw_state[:] = [2, 2]
    _hair_ui_cache[LT_HAIR] = [0x00, 0x0A, 0x5A]
    _hair_ui_cache[RT_HAIR] = [0x00, 0x0A, 0x5A]


def connection_kind(pid: int):
    """True for wired (100f), False for wireless dongle (1098)."""
    if pid in WIRED_PIDS:
        return True
    if pid in DONGLE_PIDS:
        return False
    return None


def is_vendor_node(devnode: str) -> bool:
    """True if devnode's sysfs report_descriptor declares Usage Page 0xFF7A."""
    name = os.path.basename(devnode)
    rdesc_path = os.path.join('/sys/class/hidraw', name, 'device', 'report_descriptor')
    try:
        with open(rdesc_path, 'rb') as f:
            desc = f.read()
        return VENDOR_USAGE_PAGE_BYTES in desc
    except OSError:
        return False


def pick_vendor_node(devnodes):
    """Return the 0xFF7A vendor hidraw node from a controller's node list."""
    if not devnodes:
        return None
    for n in devnodes:
        if is_vendor_node(n):
            return n
    return devnodes[0]


def frame_packet(prefix_bytes, total_len: int) -> bytes:
    """Build a 65-byte hidapi write buffer (leading 0x00 report ID + 64B report)
    with the T4N2 additive checksum at `buf[total_len - 1]`."""
    buf = list(prefix_bytes) + [0x00] * (REPORT_LEN - len(prefix_bytes))
    if 1 <= total_len <= REPORT_LEN:
        buf[total_len - 1] = sum(buf[:total_len - 1]) & 0xFF
    return bytes([0x00] + buf[:REPORT_LEN])


def device_info_packet() -> bytes:
    """GetDeviceInfo query (`01 01 00`)."""
    return bytes([0x00, 0x01, 0x01, 0x00] + [0x00] * (REPORT_LEN - 3))


def enable_stream_packet() -> bytes:
    """SetGamepadStateReport(Mapped): enables live 0xF4 input reports."""
    return frame_packet([0xF3, 0x01, 0x05, 0x02], 5)


def disable_stream_packet() -> bytes:
    """SetGamepadStateReport(Original): restores normal HID reporting."""
    return frame_packet([0xF3, 0x01, 0x05, 0x00], 5)


def rumble_packet(left: int, right: int) -> bytes:
    """Direct motor vibration packet (`04 <left> 08 <right> 08 00 08 00 08`)."""
    l_val = max(0, min(255, int(left)))
    r_val = max(0, min(255, int(right)))
    payload = [0x04, l_val, 0x08, r_val, 0x08, 0x00, 0x08, 0x00, 0x08]
    return bytes([0x00] + payload + [0x00] * (REPORT_LEN - len(payload)))


def streams_live_data(devnode: str, secs: float = 0.5) -> bool:
    """Check whether `devnode` is a live Nova 2 Lite 0xFF7A vendor interface."""
    if not is_vendor_node(devnode):
        return False
    try:
        d = hid.device()
        d.open_path(devnode.encode())
        d.set_nonblocking(True)
    except Exception:
        return False
    live = False
    try:
        try:
            d.write(device_info_packet())
        except Exception:
            return False
        t0 = time.time()
        while time.time() - t0 < secs:
            try:
                data = d.read(64, timeout_ms=50)
            except OSError:
                break
            if not data:
                continue
            if data[0] == 0x01 and len(data) >= 12 and data[1] != 0x00:
                live = True
                break
            if data[0] in (0xF4, 0xF3, 0xF5, 0xF0, 0xF1, 0x25, 0x23, 0x21, 0x07):
                live = True
                break
    finally:
        try:
            d.close()
        except Exception:
            pass
    return live


def parse_device_info(data) -> dict:
    """Decode a 0x01 GetDeviceInfo reply into firmware/battery/charging fields."""
    if not data or len(data) < 18 or data[0] != 0x01 or data[1] == 0x00:
        return {}
    out = {}
    fw_lo, fw_hi = data[10], data[11]
    if fw_hi or fw_lo:
        out['firmware'] = f'{fw_hi}.{fw_lo:02x}'
    bat_raw = data[16] & 0x0F
    if bat_raw <= 5:
        out['battery'] = min(100, bat_raw * 25)
    out['charging'] = (data[17] == 0x02) or (bat_raw >= 5)
    return out


_DPAD_MAP = {
    (0, 0): 'neutral',
    (0, -1): 'up',
    (1, -1): 'up-right',
    (1, 0): 'right',
    (1, 1): 'down-right',
    (0, 1): 'down',
    (-1, 1): 'down-left',
    (-1, 0): 'left',
    (-1, -1): 'up-left',
}


def _s16_to_u8(val: int, invert: bool = False) -> int:
    if invert:
        val = -val
    return max(0, min(255, round((val + 32768) * 255 / 65535)))


def parse_input(data) -> dict:
    """Decode a 23-byte 0xF4 live gamepad state report into Deadband's `state` dict."""
    if not data or len(data) < 22 or data[0] != 0xF4:
        return {}
    b4, b5, b6, b7 = data[4], data[5], data[6], data[7]
    up = bool(b6 & 0x01)
    down = bool(b6 & 0x02)
    left = bool(b6 & 0x04)
    right = bool(b6 & 0x08)
    dx = (1 if right else 0) - (1 if left else 0)
    dy = (1 if down else 0) - (1 if up else 0)

    lx_s16, ly_s16, rx_s16, ry_s16 = struct.unpack_from('<4h', bytes(data[:16]), 8)
    lt, rt = data[16], data[17]
    out = {
        'lx': _s16_to_u8(lx_s16, invert=False),
        'ly': _s16_to_u8(ly_s16, invert=True),
        'rx': _s16_to_u8(rx_s16, invert=False),
        'ry': _s16_to_u8(ry_s16, invert=True),
        'lt': lt,
        'rt': rt,
        'lt_d': lt > 0,
        'rt_d': rt > 0,
        'dpad': _DPAD_MAP.get((dx, dy), 'neutral'),
        'a': bool(b4 & 0x01),
        'b': bool(b4 & 0x02),
        'x': bool(b4 & 0x08),
        'y': bool(b4 & 0x10),
        'lb': bool(b4 & 0x40),
        'rb': bool(b4 & 0x80),
        'view': bool(b5 & 0x04),
        'menu': bool(b5 & 0x08),
        'home': bool(b5 & 0x10),
        'ls': bool(b5 & 0x20),
        'rs': bool(b5 & 0x40),
        'share': bool(b5 & 0x80),
        'l4': bool(b6 & 0x80),
        'r4': bool(b7 & 0x01),
        'm': bool(b7 & 0x40),
    }
    fw_lo, fw_hi = data[20], data[21]
    if fw_hi or fw_lo:
        out['firmware'] = f'{fw_hi}.{fw_lo:02x}'
    return out


# --- Register Read / Write Translation --------------------------------------

def _stick_id_for_addr(addr: int):
    if ST_TRAJ <= addr < ST_TRAJ + RS_OFFSET:
        return 1, addr - ST_TRAJ
    if RS_TRAJ <= addr < RS_TRAJ + RS_OFFSET:
        return 2, addr - RS_TRAJ
    return None, None


def read_request_packet(bank: int, addr: int, length: int):
    """Return the 65-byte T4N2 query packet for reading `(bank, addr, length)`."""
    if addr in (VIB_L, VIB_R):
        return frame_packet([0x25, 0x01, 0x0D] + [0x00] * 9, 13)
    if addr == DPAD_SWAP:
        return frame_packet([0x23, 0x04, 0x06, 0x00, 0x00], 6)
    if addr == DPAD_LOCK:
        return frame_packet([0x23, 0x01, 0x06, 0x00, 0x00], 6)
    if addr == LT_DZ_MIN:
        return frame_packet([0x07, 0x05, 0x06, 0x00, 0x00], 6)
    if addr == LT_DZ_MAX:
        return frame_packet([0x07, 0x07, 0x06, 0x00, 0x00], 6)
    if addr == RT_DZ_MIN:
        return frame_packet([0x07, 0x06, 0x06, 0x00, 0x00], 6)
    if addr == RT_DZ_MAX:
        return frame_packet([0x07, 0x08, 0x06, 0x00, 0x00], 6)
    if addr in (LT_HAIR, RT_HAIR, LT_HAIR + 1, LT_HAIR + 2, RT_HAIR + 1, RT_HAIR + 2):
        return frame_packet([0x21, 0x00, 0x00, 0x00], 5)
    if addr == ST_TRAJ:
        return frame_packet([0x23, 0x10, 0x06, 0x00, 0x00], 6)
    if addr == RS_TRAJ:
        return frame_packet([0x23, 0x11, 0x06, 0x00, 0x00], 6)
    stick_id, _off = _stick_id_for_addr(addr)
    if stick_id in (1, 2):
        return frame_packet([0xF0, 0x00, 0x11, stick_id] + [0x00] * 12, 17)
    if addr in _ADDR_TO_HW_KEY:
        hw_key = _ADDR_TO_HW_KEY[addr]
        return frame_packet([0xF1, 0x00, 0x09, hw_key, 0x00, 0x00, 0x00, 0x00], 9)
    return None


def _pts_255_to_100(pts_255):
    return [max(0, min(100, round(v * 100 / 255))) for v in pts_255]


def _pts_100_to_255(pts_100):
    return [max(0, min(255, round(v * 255 / 100))) for v in pts_100]


def _decode_stick_curve(stick_id: int, raw12: list) -> list:
    """Convert T4N2 12-byte stick payload into Deadband's 10-byte curve block
    `[type, intensity, 0, 0, x0, y0, x1, y1, x2, y2]` in 0..255 coordinates."""
    ctype = raw12[10]
    inten = raw12[11]
    hw_pts_100 = list(raw12[2:8])
    cached = _curve_ui_cache.get(stick_id)
    if cached is not None and len(cached) == 10:
        if cached[0] == ctype and cached[1] == inten and _pts_255_to_100(cached[4:10]) == hw_pts_100:
            return list(cached)
    if ctype == 0 and inten == 100 and hw_pts_100 == [25, 25, 50, 50, 75, 75]:
        return list(_cy.CURVE_BLOCKS[0][1])
    if 0 <= ctype < len(_cy.CURVE_BLOCKS):
        name = _cy.CURVE_BLOCKS[ctype][0]
        preset = _cy.preset_curve_block(name, inten)
        if preset is not None and _pts_255_to_100(preset[4:10]) == hw_pts_100:
            return list(preset)
    pts_255 = _pts_100_to_255(hw_pts_100)
    return [ctype, inten, 0x00, 0x00, *pts_255]


def match_read_reply(data, bank: int, addr: int, length: int):
    """If `data` is the read reply for `(bank, addr, length)`, return `list[int]`
    of length `length`; otherwise return None. Ignores write ACKs."""
    if not data or len(data) < 6:
        return None

    # 0x25: GetVibrateLevel reply (data[3] == 0x00 for read, 0x01 for write ACK)
    if addr in (VIB_L, VIB_R):
        if data[0] != 0x25 or data[1] != 0x01 or data[3] != 0x00 or len(data) < 13:
            return None
        _vib_state[0] = data[4]
        _vib_state[1] = data[8]
        val = data[4] if addr == VIB_L else data[8]
        return [val][:length]

    # 0x23: GetCrossKeyOption / GetStickTrajectoryMode (data[3] == 0x00 for read)
    if addr in (DPAD_SWAP, DPAD_LOCK, ST_TRAJ, RS_TRAJ):
        sub = {DPAD_LOCK: 0x01, DPAD_SWAP: 0x04, ST_TRAJ: 0x10, RS_TRAJ: 0x11}[addr]
        if data[0] != 0x23 or data[1] != sub or data[3] != 0x00:
            return None
        return [data[4]][:length]

    # 0x07: GetTriggerDeadZone (data[3] == 0x00 for read)
    if addr in (LT_DZ_MIN, LT_DZ_MAX, RT_DZ_MIN, RT_DZ_MAX):
        sub = {LT_DZ_MIN: 0x05, RT_DZ_MIN: 0x06, LT_DZ_MAX: 0x07, RT_DZ_MAX: 0x08}[addr]
        if data[0] != 0x07 or data[1] != sub or data[3] != 0x00:
            return None
        return [data[4]][:length]

    # 0x21: GetQuickTrigger (data[1] == 0x00 for read, 0x01 for write ACK)
    if addr in (LT_HAIR, RT_HAIR):
        if data[0] != 0x21 or data[1] != 0x00:
            return None
        _hair_hw_state[0] = data[2]
        _hair_hw_state[1] = data[3]
        hw_val = data[2] if addr == LT_HAIR else data[3]
        cached = list(_hair_ui_cache.get(addr, [0x00, 0x0A, 0x5A]))
        if hw_val == 1:    # On
            if cached[0] not in (0x81, 0x82):
                cached = [0x81, 0x0A, 0x5A]
        else:              # Off (2)
            cached = [0x00, 0x0A, 0x5A]
        _hair_ui_cache[addr] = cached
        return cached[:length]

    # 0xF0: GetStickDeadZoneAndCurve (data[1] == 0x00 for read, 0x01 for write ACK)
    stick_id, off = _stick_id_for_addr(addr)
    if stick_id in (1, 2):
        if data[0] != 0xF0 or data[1] != 0x00 or data[3] != stick_id or len(data) < 17:
            return None
        raw12 = list(data[4:16])
        _stick_state[stick_id] = raw12
        base = ST_TRAJ if stick_id == 1 else RS_TRAJ
        if addr == base + 2:    # DZ_MIN
            return [raw12[0]][:length]
        if addr == base + 3:    # DZ_MAX
            return [raw12[8]][:length]
        if addr == base + 4:    # ADZ_MIN
            return [raw12[1]][:length]
        if addr == base + 5:    # ADZ_MAX
            return [raw12[9]][:length]
        if addr == base + 7:    # CURVE (10B)
            return _decode_stick_curve(stick_id, raw12)[:length]
        return None

    # 0xF1: GetGamepadKeyMapping (data[1] == 0x00 for read)
    if addr in _ADDR_TO_HW_KEY:
        hw_key = _ADDR_TO_HW_KEY[addr]
        if data[0] != 0xF1 or data[1] != 0x00 or data[3] != hw_key or len(data) < 9:
            return None
        count = data[4]
        target_hw = data[5]
        if count == 0 or target_hw == 0 or target_hw == hw_key:
            return [0x00, 0x00][:length]
        if target_hw == _HW_KEY_DISABLED:
            return [0x01, 0xFF][:length]
        code = _HW_TO_TARGET_CODE.get(target_hw, 0)
        if code:
            return [0x01, code][:length]
        return [0x00, 0x00][:length]

    return None


def write_packets(bank: int, addr: int, data) -> list:
    """Return a list of 65-byte T4N2 command packets to write `data` at `(bank, addr)`."""
    data = list(data)
    if not data:
        return []

    if addr in (VIB_L, VIB_R):
        if addr == VIB_L:
            _vib_state[0] = max(0, min(100, int(data[0])))
            if len(data) > 1:
                _vib_state[1] = max(0, min(100, int(data[1])))
        else:
            _vib_state[1] = max(0, min(100, int(data[0])))
        return [frame_packet(
            [0x25, 0x01, 0x0D, 0x01, _vib_state[0], 0x03, 0x00, 0x00,
             _vib_state[1], 0x03, 0x00, 0x00], 13)]

    if addr in (DPAD_SWAP, DPAD_LOCK, ST_TRAJ, RS_TRAJ):
        sub = {DPAD_LOCK: 0x01, DPAD_SWAP: 0x04, ST_TRAJ: 0x10, RS_TRAJ: 0x11}[addr]
        val = 1 if data[0] else 0
        return [frame_packet([0x23, sub, 0x06, 0x01, val], 6)]

    if addr in (LT_DZ_MIN, LT_DZ_MAX, RT_DZ_MIN, RT_DZ_MAX):
        sub = {LT_DZ_MIN: 0x05, RT_DZ_MIN: 0x06, LT_DZ_MAX: 0x07, RT_DZ_MAX: 0x08}[addr]
        val = max(0, min(100, int(data[0])))
        return [frame_packet([0x07, sub, 0x06, 0x01, val], 6)]

    if addr in (LT_HAIR, RT_HAIR):
        mode_byte = data[0]
        hw_val = 1 if mode_byte in (0x81, 0x82, 1) else 2
        if addr == LT_HAIR:
            _hair_hw_state[0] = hw_val
        else:
            _hair_hw_state[1] = hw_val
        prev = list(_hair_ui_cache.get(addr, [0x00, 0x0A, 0x5A]))
        prev[:len(data)] = data
        _hair_ui_cache[addr] = prev
        return [frame_packet([0x21, 0x01, _hair_hw_state[0], _hair_hw_state[1]], 5)]

    stick_id, _off = _stick_id_for_addr(addr)
    if stick_id in (1, 2):
        raw12 = list(_stick_state[stick_id])
        base = ST_TRAJ if stick_id == 1 else RS_TRAJ
        if addr == base + 2:    # DZ_MIN
            raw12[0] = max(0, min(100, int(data[0])))
        elif addr == base + 3:  # DZ_MAX
            raw12[8] = max(0, min(100, int(data[0])))
        elif addr == base + 4:  # ADZ_MIN
            raw12[1] = max(0, min(100, int(data[0])))
        elif addr == base + 5:  # ADZ_MAX
            raw12[9] = max(0, min(100, int(data[0])))
        elif addr == base + 7 and len(data) >= 10:  # CURVE (10B)
            _curve_ui_cache[stick_id] = list(data[:10])
            raw12[10] = max(0, min(3, int(data[0])))
            raw12[11] = max(0, min(100, int(data[1])))
            raw12[2:8] = _pts_255_to_100(data[4:10])
        else:
            return []
        _stick_state[stick_id] = raw12
        return [frame_packet([0xF0, 0x01, 0x11, stick_id, *raw12], 17)]

    if addr in _ADDR_TO_HW_KEY:
        src_hw = _ADDR_TO_HW_KEY[addr]
        en = data[0]
        code = data[1] if len(data) > 1 else 0
        if not en or code == 0:
            # Default / Self: mode 0x02, count 0
            return [frame_packet([0xF1, 0x02, 0x09, src_hw, 0x00, 0x00, 0x00, 0x00], 9)]
        if code == 0xFF:
            # Disabled / Vacant: mode 0x01, count 1, target 0xD2
            return [frame_packet([0xF1, 0x01, 0x09, src_hw, 0x01, _HW_KEY_DISABLED, 0x00, 0x00], 9)]
        target_hw = _TARGET_CODE_TO_HW.get(code)
        if target_hw is None:
            return []
        if target_hw == src_hw:
            return [frame_packet([0xF1, 0x02, 0x09, src_hw, 0x00, 0x00, 0x00, 0x00], 9)]
        return [frame_packet([0xF1, 0x01, 0x09, src_hw, 0x01, target_hw, 0x00, 0x00], 9)]

    return []
