"""
GameSir Tarantula Pro (original, "T3Pro") -- SAPJoy vendor HID protocol
=======================================================================
Decoded on Linux from GameSir Connect 1.14.5 / 1.17.5 running under Proton,
with strace on the dongle's hidraw node (research/tarantula_pro/). Command
semantics follow the SDK header the app ships (gs_pc3.h) and the struct
definitions in its main.js; the wire framing was read off the captures.

Transport
---------
* 3537:103e  "GameSir-Dongle" (2.4 GHz receiver, controller in XInput mode).
  iface 0 = XInput (xpad), iface 1 = HID keyboard/mouse/consumer + a vendor
  collection on usage page 0xFFA0: report 0x07 OUT (31 bytes), report 0x06 IN
  (63 bytes).
* 3537:1050  wired config identity named by the app (not seen here yet).

Framing
-------
OUT: 07 LEN GRP OP payload...   LEN = 3 + len(payload), padded to 32 bytes.
IN : 06 LEN GRP OP payload...   replies echo GRP/OP.
OP 01 = set, 02 = get, 03 = set (indexed), 04 = get (indexed). GRP 08 OP 03
writes the active profile to flash ("SaveConfigPage").

Safety
------
Only (GRP, OP) pairs the official app was seen sending are allowed; anything
else raises. Firmware/ISP commands are deliberately absent.
"""

import os
import time

VID = 0x3537
PID_DONGLE = 0x103E
PID_WIRED_CONFIG = 0x1050
CONFIG_PIDS = (PID_DONGLE, PID_WIRED_CONFIG)

REPORT_OUT = 0x07
REPORT_IN = 0x06
OUT_LEN = 32

# Key ids (SAPJoyUniKey).
KEYS = {
    'B': 0, 'A': 1, 'Y': 2, 'X': 3, 'LB': 4, 'LT': 5, 'L3': 6, 'RB': 7, 'RT': 8,
    'R3': 9, 'VIEW': 10, 'MENU': 11, 'LEFT': 12, 'RIGHT': 13, 'UP': 14, 'DOWN': 15,
    'LS_LEFT': 16, 'LS_RIGHT': 17, 'LS_UP': 18, 'LS_DOWN': 19,
    'RS_LEFT': 20, 'RS_RIGHT': 21, 'RS_UP': 22, 'RS_DOWN': 23,
    'OLS_LEFT': 24, 'OLS_RIGHT': 25, 'OLS_UP': 26, 'OLS_DOWN': 27,
    'ORS_LEFT': 28, 'ORS_RIGHT': 29, 'ORS_UP': 30, 'ORS_DOWN': 31,
    'GYRO_LEFT': 32, 'GYRO_RIGHT': 33, 'GYRO_UP': 34, 'GYRO_DOWN': 35,
    'L4': 36, 'R4': 37, 'T1': 38, 'T2': 39, 'T3': 40,
    'C1': 41, 'C2': 42, 'C3': 43, 'C4': 44, 'CAMERA': 45,
}
KEY_NAMES = {v: k for k, v in KEYS.items()}
# Keys the app reads/writes a mapping for, in its order (main.js `zu`).
APP_KEYS = ('B', 'A', 'Y', 'X', 'LB', 'LT', 'L3', 'RB', 'RT', 'R3', 'VIEW', 'MENU',
            'LEFT', 'RIGHT', 'UP', 'DOWN', 'L4', 'R4', 'T1', 'T3', 'T2',
            'C1', 'C2', 'C3', 'C4', 'CAMERA')
MACRO_KEYS = ('L4', 'R4', 'T1', 'T3', 'T2', 'C1', 'C2', 'C3', 'C4')
MACRO_MAX_STEPS = 12

# Light modes (SAPJoyUniLightMode).
LIGHT_MODES = {'off': 0, 'solid': 1, 'breathing': 2, 'phantom': 3,
               'streamer': 4, 'radar': 5}
# Light zone ids as seen on the wire (00, 04, 05 = 4-segment, 06 = 4-segment).
LIGHT_ZONES = (0x00, 0x04, 0x05, 0x06)

TRIGGER = {'off': 0, 'oneshot': 1, 'hold': 2, 'always': 3}
MAP_KEYBOARD, MAP_MOUSE, MAP_MEDIA = 2, 3, 4

# Keyboard / mouse / media outputs, as GameSir Connect encodes them (main.js):
#  keyboard: codes = [modifier bits, usage1, usage2, usage3]  (HID usage ids)
#  mouse:    codes = [0, 0, wheel (1 up, 255 down, 128 both), button bits]
#  media:    codes = [0, 0, 0, media bits]
KB_MODS = ['LCTRL', 'LSHIFT', 'LALT', 'LWIN', 'RCTRL', 'RSHIFT', 'RALT', 'RWIN']
KB_KEYS = {
    'ESC': 41, 'F1': 58, 'F2': 59, 'F3': 60, 'F4': 61, 'F5': 62, 'F6': 63, 'F7': 64, 'F8': 65,
    'F9': 66, 'F10': 67, 'F11': 68, 'F12': 69, 'GRAVE': 53,
    '1': 30, '2': 31, '3': 32, '4': 33, '5': 34, '6': 35, '7': 36, '8': 37, '9': 38, '0': 39,
    'MINUS': 45, 'EQUAL': 46, 'BACKSPACE': 42, 'TAB': 43,
    'Q': 20, 'W': 26, 'E': 8, 'R': 21, 'T': 23, 'Y': 28, 'U': 24, 'I': 12, 'O': 18, 'P': 19,
    'LEFTBRACE': 47, 'RIGHTBRACE': 48, 'BACKSLASH': 49, 'CAPSLOCK': 57,
    'A': 4, 'S': 22, 'D': 7, 'F': 9, 'G': 10, 'H': 11, 'J': 13, 'K': 14, 'L': 15,
    'SEMICOLON': 51, 'APOSTROPHE': 52, 'ENTER': 40,
    'Z': 29, 'X': 27, 'C': 6, 'V': 25, 'B': 5, 'N': 17, 'M': 16,
    'COMMA': 54, 'DOT': 55, 'SLASH': 56, 'SPACE': 44,
    'INSERT': 73, 'HOME': 74, 'PAGEUP': 75, 'DELETE': 76, 'END': 77, 'PAGEDOWN': 78,
    'UP': 82, 'DOWN': 81, 'LEFT': 80, 'RIGHT': 79, 'PRINT': 70,
    'NUMLOCK': 83, 'KPSLASH': 84, 'KPASTERISK': 85, 'KPMINUS': 86, 'KPPLUS': 87, 'KPDOT': 99,
    'KPENTER': 88, 'KP0': 98, 'KP1': 89, 'KP2': 90, 'KP3': 91, 'KP4': 92, 'KP5': 93,
    'KP6': 94, 'KP7': 95, 'KP8': 96, 'KP9': 97,
    'F13': 104, 'F14': 105, 'F15': 106, 'F16': 107, 'F17': 108, 'F18': 109,
    'F19': 110, 'F20': 111, 'F21': 112, 'F22': 113, 'F23': 114, 'F24': 115,
}
# A back button mapped to itself produces no output at all (not even in the
# mapped state stream), so a PC-side "button alone" shortcut maps it to an
# otherwise unused key instead; the bridge watches the dongle's keyboard for
# it. Hardware-checked: R4 -> usage 0x68 arrived as KEY_F13.
SIGNAL_KEYS = {k: f'F{13 + i}' for i, k in enumerate(('L4', 'R4', 'C1', 'C2', 'C3', 'C4', 'T1', 'T2', 'T3'))}
KB_NAMES = {v: k for k, v in KB_KEYS.items()}
MOUSE_BUTTONS = ['LEFT', 'RIGHT', 'MIDDLE', 'BACK', 'FORWARD']   # bits 0-4 (app: 5 then 4)
MOUSE_WHEEL = {'WHEEL_UP': 1, 'WHEEL_DOWN': 255}
MEDIA_KEYS = ['MUTE', 'VOLDOWN', 'VOLUP', 'MICMUTE', 'PLAY', 'PREV', 'STOP', 'NEXT']


def encode_output(kind, names):
    """-> (mappingType, codes) for a remap target or a macro step.
    kind: 'pad' (up to 4 pad buttons), 'kb' (modifiers + up to 3 keys),
    'mouse' (buttons and/or wheel), 'media'."""
    names = [n.upper() for n in names if n]
    if kind == 'pad':
        return MAP_JOYSTICK, [KEYS[n] for n in names][:4]
    if kind == 'kb':
        mods, keys = 0, []
        for n in names:
            if n in KB_MODS:
                mods |= 1 << KB_MODS.index(n)
            elif n in KB_KEYS and len(keys) < 3:
                keys.append(KB_KEYS[n])
            else:
                raise ProtocolError(f'unknown or extra keyboard key {n!r}')
        return MAP_KEYBOARD, [mods] + keys
    if kind == 'mouse':
        bits, up, down = 0, False, False
        for n in names:
            if n in MOUSE_BUTTONS:
                bits |= 1 << MOUSE_BUTTONS.index(n)
            elif n == 'WHEEL_UP':
                up = True
            elif n == 'WHEEL_DOWN':
                down = True
            else:
                raise ProtocolError(f'unknown mouse output {n!r}')
        wheel = 128 if up and down else 1 if up else 255 if down else 0
        return MAP_MOUSE, [0, 0, wheel, bits]
    if kind == 'media':
        bits = 0
        for n in names:
            if n not in MEDIA_KEYS:
                raise ProtocolError(f'unknown media key {n!r}')
            bits |= 1 << MEDIA_KEYS.index(n)
        return MAP_MEDIA, [0, 0, 0, bits]
    raise ProtocolError(f'unknown output kind {kind!r}')


def decode_output(mapping_type, codes):
    """Inverse of encode_output -> (kind, names)."""
    c = list(codes) + [0, 0, 0, 0]
    if mapping_type == MAP_KEYBOARD:
        names = [m for i, m in enumerate(KB_MODS) if c[0] >> i & 1]
        names += [KB_NAMES.get(k, str(k)) for k in c[1:4] if k]
        return 'kb', names
    if mapping_type == MAP_MOUSE:
        names = [b for i, b in enumerate(MOUSE_BUTTONS) if c[3] >> i & 1]
        names += {1: ['WHEEL_UP'], 255: ['WHEEL_DOWN'], 128: ['WHEEL_UP', 'WHEEL_DOWN']}.get(c[2], [])
        return 'mouse', names
    if mapping_type == MAP_MEDIA:
        return 'media', [m for i, m in enumerate(MEDIA_KEYS) if c[3] >> i & 1]
    if mapping_type == MAP_JOYSTICK:
        return 'pad', [KEY_NAMES.get(k, str(k)) for k in codes]
    return 'none', []
TURBO_OFF, TURBO_A, TURBO_B, TURBO_C = 0, 1, 2, 3
ZONE_HOME, ZONE_BAR, ZONE_ABXY, ZONE_BAYX = 0x00, 0x04, 0x05, 0x06


def deg_to_wire(h):
    """GameSir Connect works in degrees; the wire carries hue 0-255."""
    return round((h % 360) * 255 / 360)


# GameSir Connect's default "T3Pro 1" profile (main.js), used for the factory reset.
DEFAULT_LIGHT = {'brightness': 50, 'speed': 50, 'mode': 3}
DEFAULT_COLORS = {                    # (hue deg, sat %, val %)
    ZONE_ABXY: [(120, 100, 6), (0, 100, 6), (240, 100, 6), (59, 100, 6)],   # A B X Y, Xbox colours
    ZONE_BAYX: [(0, 0, 6)] * 4,                                              # Switch layout: white
    ZONE_HOME: [(0, 0, 100)],
    ZONE_BAR: [(240, 100, 50)],
}
DEFAULT_REMAP = {'C1': 'VIEW', 'C2': 'VIEW', 'C3': 'MENU', 'C4': 'MENU', 'T3': 'CAMERA'}
DEFAULT_VIBRATION = (75, 75)          # app "motor 3" of 0-4
DEFAULT_MOTION = {'angle': 40, 'range': 40, 'output': 0, 'kind': 0, 'axes': 0, 'key': 0,
                  'activation': 0, 'sens_x': 50, 'sens_y': 50, 'invert_x': 0, 'invert_y': 0,
                  'ratio': 50, 'deadzone': 0, 'anti_deadzone': 0, 'curve': [30, 30, 50, 50, 70, 70],
                  'end_deadzone': 100, 'end_anti_deadzone': 100, 'curve_type': 0, 'curvature': 100}
MAP_VACANT, MAP_JOYSTICK = 0, 1

# (GRP, OP) pairs observed from the official app. Nothing else is sent.
ALLOWED = {
    (0x0A, 0x01): 'GetDeviceInfo',
    (0x0A, 0x02): 'SetGamepadStateReport',
    (0x0A, 0x04): 'SetVibrateTest',
    (0x05, 0x01): 'SetKeyMapping',
    (0x05, 0x02): 'GetKeyMapping',
    (0x01, 0x01): 'SetMacroStep',
    (0x01, 0x02): 'GetMacroStep',
    (0x02, 0x02): 'GetStickCurve',
    (0x02, 0x04): 'GetStickMapping',
    (0x03, 0x02): 'GetTriggerParam',
    (0x04, 0x01): 'SetMotionSenseCurve',
    (0x04, 0x02): 'GetMotionSenseCurve',
    (0x04, 0x03): 'SetMotionSenseMapping',
    (0x04, 0x04): 'GetMotionSenseMapping',
    (0x06, 0x01): 'SetVibrateLevel',
    (0x06, 0x02): 'GetVibrateLevel',
    (0x07, 0x01): 'SetLightParam',
    (0x07, 0x02): 'GetLightParam',
    (0x07, 0x03): 'SetLightColor',
    (0x07, 0x04): 'GetLightColor',
    (0x08, 0x03): 'SaveConfigPage',
    (0x09, 0x01): 'SetDPadParam',
    (0x09, 0x02): 'GetDPadParam',
}
WRITES = {k for k, v in ALLOWED.items() if v.startswith(('Set', 'Save'))}


class ProtocolError(Exception):
    pass


def frame(grp, op, payload=b''):
    if (grp, op) not in ALLOWED:
        raise ProtocolError(f'command {grp:02x}/{op:02x} was never seen from the '
                            'official app; refusing to send it')
    body = bytes([3 + len(payload), grp, op]) + bytes(payload)
    if len(body) > OUT_LEN - 1:
        raise ProtocolError('payload too long')
    return bytes([REPORT_OUT]) + body + bytes(OUT_LEN - 1 - len(body))


def find_hidraw():
    """Path of the dongle's vendor hidraw node (usage page 0xFFA0), or None."""
    base = '/sys/class/hidraw'
    for node in sorted(os.listdir(base)):
        dev = os.path.join(base, node, 'device')
        try:
            uevent = open(os.path.join(dev, 'uevent')).read()
            desc = open(os.path.join(dev, 'report_descriptor'), 'rb').read()
        except OSError:
            continue
        hid_id = next((l.split('=')[1] for l in uevent.splitlines()
                       if l.startswith('HID_ID=')), '')
        parts = hid_id.split(':')
        if len(parts) != 3 or int(parts[1], 16) != VID or int(parts[2], 16) not in CONFIG_PIDS:
            continue
        if b'\x06\xa0\xff' in desc:
            return '/dev/' + node
    return None


class Tarantula:
    def __init__(self, path=None, timeout=0.5, verbose=False):
        self.path = path or find_hidraw()
        if not self.path:
            raise ProtocolError('Tarantula Pro dongle (3537:103e) vendor node not '
                                'found: is the dongle plugged in and the pad in XInput mode?')
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        self.timeout = timeout
        self.verbose = verbose

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _drain(self):
        while True:
            try:
                os.read(self.fd, 64)
            except BlockingIOError:
                return

    def request(self, grp, op, payload=b'', match=b'', retries=2):
        """Send one command and return the reply payload (bytes after OP).
        `match` must prefix the reply payload (e.g. the key id echoed back)."""
        pkt = frame(grp, op, payload)
        for _ in range(retries + 1):
            self._drain()
            os.write(self.fd, pkt)
            if self.verbose:
                print('>>', pkt.rstrip(b'\0').hex(' '))
            end = time.time() + self.timeout
            while time.time() < end:
                try:
                    r = os.read(self.fd, 64)
                except BlockingIOError:
                    time.sleep(0.002)
                    continue
                if len(r) >= 4 and r[0] == REPORT_IN and r[2] == grp and r[3] == op:
                    body = r[4:max(4, r[1] + 1)]
                    if body[:len(match)] == match:
                        if self.verbose:
                            print('<<', r[:r[1] + 1].hex(' '))
                        return bytes(body)
        if (grp, op) in WRITES:
            return None              # most sets are fire-and-forget
        raise ProtocolError(f'no reply to {ALLOWED[(grp, op)]}')

    # ---- reads -----------------------------------------------------------
    def device_info(self):
        b = self.request(0x0A, 0x01, b'\x01'[:0])
        return {'id': b[0], 'firmware': f'{b[1]}.{b[2]:x}'.replace('.', '.0', 1) if b[2] < 0x10 else f'{b[1]}.{b[2]:x}',
                'firmware_raw': b[1:3].hex(), 'mac': b[3:9].hex(':'),
                'battery': min(b[9], 100) if len(b) > 9 else None}

    def get_key_mapping(self, key, page=0):
        k = KEYS[key] if isinstance(key, str) else key
        return self.request(0x05, 0x02, bytes([page, k]))

    def get_macro_step(self, key, index):
        k = KEYS[key] if isinstance(key, str) else key
        return self.request(0x01, 0x02, bytes([k, index]), match=bytes([k]))

    def get_light_param(self):
        b = self.request(0x07, 0x02)
        return {'brightness': b[0], 'speed': b[1], 'mode': b[2]}

    def get_light_color(self, zone):
        b = self.request(0x07, 0x04, bytes([zone]), match=bytes([zone]))
        leds = [tuple(b[1 + 3 * i:4 + 3 * i]) for i in range((len(b) - 1) // 3)]
        return leds

    def get_dpad_param(self):
        return self.request(0x09, 0x02)

    def get_motion_mapping(self):
        return self.request(0x04, 0x04)

    def get_motion_curve(self, kind=0):
        return self.request(0x04, 0x02, bytes([kind]) if kind else b'')

    def dump(self):
        """Every read the official app performs at startup, raw."""
        out = {'info': self.device_info()}
        out['keys'] = {k: self.get_key_mapping(k).hex(' ') for k in APP_KEYS}
        for k in ('LS_LEFT', 'LS_RIGHT', 'LS_UP', 'LS_DOWN', 'RS_LEFT', 'RS_RIGHT',
                  'RS_UP', 'RS_DOWN', 'GYRO_LEFT', 'GYRO_RIGHT', 'GYRO_UP', 'GYRO_DOWN'):
            out['keys'][k] = self.get_key_mapping(k).hex(' ')
        out['stick_curve'] = [self.request(0x02, 0x04, bytes([s]) if s else b'').hex(' ') for s in (0, 1)]
        out['stick_mapping'] = [self.request(0x02, 0x02, bytes([s]) if s else b'').hex(' ') for s in (0, 1)]
        out['trigger'] = [self.request(0x03, 0x02, bytes([t]) if t else b'').hex(' ') for t in (0, 1)]
        out['vibrate'] = self.request(0x06, 0x02).hex(' ')
        out['light_param'] = self.request(0x07, 0x02).hex(' ')
        out['dpad'] = self.get_dpad_param().hex(' ')
        out['light_color'] = {z: self.request(0x07, 0x04, bytes([z]) if z else b'',
                                              match=bytes([z])).hex(' ') for z in LIGHT_ZONES}
        out['motion_curve'] = self.request(0x04, 0x02).hex(' ')
        out['motion_mapping'] = self.get_motion_mapping().hex(' ')
        out['macros'] = {}
        for k in MACRO_KEYS:
            steps = []
            for i in range(MACRO_MAX_STEPS):
                s = self.get_macro_step(k, i)
                if len(s) < 8 or s[6] == MAP_VACANT:
                    break
                steps.append(s.hex(' '))
            out['macros'][k] = steps
        return out

    # ---- writes ----------------------------------------------------------
    def save(self):
        self.request(0x08, 0x03)

    def set_default_colors(self):
        for zone, leds in DEFAULT_COLORS.items():
            wire = [(deg_to_wire(h), sat, v) for h, sat, v in leds]
            wire += [(0, 0, 0)] * (4 - len(wire))
            self.set_light_color(zone, wire)

    def factory_defaults(self, log=lambda m: None):
        """Write GameSir Connect's default profile: lights, colours, Xbox layout,
        every button back to itself (plus the default C/T remaps), macros
        cleared, gyro mapping off, vibration 75 %. Sticks/triggers are not
        touched (their write commands were never captured); the pad's own
        View+Menu+M reset covers those."""
        log('lights')
        self.set_light_param(**DEFAULT_LIGHT)
        self.set_default_colors()
        self.set_layout(1)
        log('buttons')
        for k in APP_KEYS:
            if k in MACRO_KEYS:
                self.request(0x01, 0x01, bytes([KEYS[k], 0xFF]) + bytes(14))
            self.set_key_mapping(k, [DEFAULT_REMAP.get(k, k)])
            time.sleep(0.01)
        log('motion')
        cur = self.get_motion()
        self.set_motion(dict(cur, **DEFAULT_MOTION, key=KEYS['B']))
        log('vibration')
        self.set_vibrate_level(*DEFAULT_VIBRATION)
        self.save()

    def set_light_param(self, brightness, speed, mode):
        self.request(0x07, 0x01, bytes([brightness, speed, mode]))

    def set_light_color(self, zone, leds):
        """leds: list of (h, s, v) as the wire carries them (h 0-255, s/v 0-100)."""
        payload = bytes([zone]) + b''.join(bytes(l) for l in leds)
        self.request(0x07, 0x03, payload)

    @staticmethod
    def mapping_body(key, mapping_type, codes, toggle=False, turbo=0):
        """16-byte key-mapping body as on the wire:
        page, trigger, colour[3], key, toggle, turboMode, turboTimes,
        mappingType, count, codes[4].

        Turbo follows GameSir Connect (main.js key model): turbo is a rate in
        Hz; above 1 it is stored as turboTimes with turboMode A (<12), B (12-19)
        or C (>=20). The pad's FAQ names 8 / 12 / 20 Hz. Off is mode 0, times 1."""
        codes = tuple(codes)[:4]
        if turbo and turbo > 1:
            times = int(turbo)
            mode = TURBO_C if times >= 20 else TURBO_B if times >= 12 else TURBO_A
        else:
            times, mode = 1, TURBO_OFF
        return bytes([0, 0, 0, 0, 0, 0, key, 1 if toggle else 0, mode, times,
                      mapping_type, len(codes)]) + bytes(codes) + bytes(4 - len(codes))

    @staticmethod
    def parse_mapping(body):
        b = bytes(body) + bytes(16)
        n = min(b[11], 4)
        return {'key': b[6], 'toggle': bool(b[7]),
                'turbo': 0 if b[8] == TURBO_OFF else b[9],
                'type': b[10], 'codes': list(b[12:12 + n])}

    def set_key_mapping(self, key, names, toggle=False, turbo=0, kind='pad'):
        """Remap `key` to pad buttons (up to 4 together), keyboard keys, mouse
        or media output. Empty pad list = the key itself (default)."""
        k = KEYS[key] if isinstance(key, str) else key
        if kind == 'pad' and not names:
            names = [KEY_NAMES[k]]
        mtype, codes = encode_output(kind, names)
        self.set_key_mapping_raw(self.mapping_body(k, mtype, codes, toggle, turbo))

    def get_remap(self, key):
        m = self.parse_mapping(self.get_key_mapping(key))
        raw = bytes(self.get_key_mapping(key) + bytes(16))
        n = min(raw[11], 4)
        kind, names = decode_output(m['type'], list(raw[12:12 + n]) if m['type'] == MAP_JOYSTICK
                                    else list(raw[12:16]))
        return {'kind': kind, 'names': names, 'toggle': m['toggle'], 'turbo': m['turbo'],
                'vacant': m['type'] == MAP_VACANT}

    def clear_macro(self, key):
        """Drop the macro and map the key back to itself (its default)."""
        k = KEYS[key]
        self.request(0x01, 0x01, bytes([k, 0xFF]) + bytes(14))
        self.set_key_mapping_raw(self.mapping_body(k, MAP_JOYSTICK, (k,)))

    def set_key_mapping_raw(self, raw):
        """raw = the 16-byte body exactly as GetKeyMapping returns it."""
        self.request(0x05, 0x01, raw)

    def set_macro(self, key, steps, hold_to_trigger=False, loop=False, loop_time_ms=0):
        """steps: list of (buttons, start_ms, end_ms); `buttons` is one name or a
        list of up to 4 pressed together. Mirrors the app: map the key Vacant,
        send a Clear step, then each step with absolute start/end. Despite the
        SDK's "In10MS" field names the T3Pro takes MILLISECONDS (hardware-verified:
        0-300 / 900-1200 played as A 300 ms, 600 ms gap, B 300 ms).
        hold_to_trigger: plays while the key is held (else once per press);
        loop: repeats with a cycle of loop_time_ms."""
        k = KEYS[key]
        if key not in MACRO_KEYS:
            raise ProtocolError(f'{key} cannot hold a macro (allowed: {", ".join(MACRO_KEYS)})')
        if len(steps) > MACRO_MAX_STEPS:
            raise ProtocolError(f'at most {MACRO_MAX_STEPS} steps')
        # A key runs its macro only when its mapping is Vacant (main.js Ie()).
        self.set_key_mapping_raw(self.mapping_body(k, MAP_VACANT, ()))
        self.request(0x01, 0x01, bytes([k, 0xFF]) + bytes(14))
        lt = max(0, min(0xFFFF, int(loop_time_ms)))
        trig = TRIGGER['hold'] if hold_to_trigger else TRIGGER['oneshot']
        for i, step in enumerate(steps):
            if len(step) == 4:              # (kind, names, start, end)
                kind, btns, start, end = step
            else:                           # (buttons, start, end)
                btns, start, end = step
                kind = 'pad'
            if isinstance(btns, str):
                btns = [btns]
            mtype, codes = encode_output(kind, btns)
            s, e = int(start), int(end)
            body = bytes([k, i, trig, 1 if loop else 0, lt >> 8, lt & 0xFF,
                          mtype, len(codes)]) + bytes(codes) + bytes(4 - len(codes)) + \
                bytes([s >> 8, s & 0xFF, e >> 8, e & 0xFF])
            self.request(0x01, 0x01, body)

    def get_macro(self, key):
        """-> {'steps': [(kind, names, start, end)], 'hold': bool, 'loop': bool, 'loop_time': ms}"""
        steps, hold, loop, lt = [], False, False, 0
        for i in range(MACRO_MAX_STEPS):
            s = self.get_macro_step(key, i)
            if len(s) < 16 or s[6] == MAP_VACANT:
                break
            n = min(s[7], 4) or 1
            kind, names = decode_output(s[6], list(s[8:8 + n]) if s[6] == MAP_JOYSTICK
                                        else list(s[8:12]))
            steps.append((kind, names, s[12] << 8 | s[13], s[14] << 8 | s[15]))
            if i == 0:
                hold, loop, lt = s[2] == TRIGGER['hold'], bool(s[3]), s[4] << 8 | s[5]
        return {'steps': steps, 'hold': hold, 'loop': loop, 'loop_time': lt}

    # ---- motion (gyro handled on the pad) --------------------------------
    MOTION_FIELDS = ('angle', 'range', 'output', 'kind', 'axes', 'key', 'activation',
                     'sens_x', 'sens_y', 'invert_x', 'invert_y')

    def get_motion(self):
        """Mapping + curve as GameSir Connect's motion page shows them.
        output: 0 off, 1 left stick, 2 right stick, 3 keys, 4 mouse.
        kind: 0 aim, 1 tilt. axes: 0 yaw, 1 roll, 2 combined.
        activation: 0 off, 1 toggle (on/off per press), 2 while the button is held,
        3 always -- the SDK trigger enum (one-shot / hold), checked on the pad;
        GameSir Connect's own labels for 1 and 2 read the other way round."""
        m = self.get_motion_mapping() + bytes(11)
        out = dict(zip(self.MOTION_FIELDS, m[:11]))
        c = self.request(0x04, 0x02) + bytes(19)
        p = c[7:17]
        out.update({'ratio': c[6], 'deadzone': p[0], 'anti_deadzone': p[1],
                    'curve': [p[2], p[3], p[4], p[5], p[6], p[7]],
                    'end_deadzone': p[8], 'end_anti_deadzone': p[9],
                    'curve_type': c[17], 'curvature': c[18], '_curve_raw': bytes(c[:19])})
        return out

    def set_motion(self, m):
        mapping = bytes(max(0, min(255, int(m[k]))) for k in self.MOTION_FIELDS)
        raw = bytearray(m.get('_curve_raw') or bytes(19))
        raw[6] = int(m['ratio'])
        pts = [m['deadzone'], m['anti_deadzone']] + list(m['curve']) + \
            [m['end_deadzone'], m['end_anti_deadzone']]
        raw[7:17] = bytes(max(0, min(100, int(v))) for v in pts)
        raw[17], raw[18] = int(m['curve_type']), int(m['curvature'])
        # same order as the app: curve first, then mapping
        self.request(0x04, 0x01, bytes(raw))
        self.request(0x04, 0x03, mapping)

    # ---- d-pad / face-button layout ----------------------------------------
    def get_layout(self):
        """1 = Xbox (ABXY), 2 = Switch (BAYX) face-button layout."""
        return self.get_dpad_param()[2]

    def set_layout(self, layout):
        cur = bytearray(self.get_dpad_param() + bytes(6))[:6]
        cur[2] = 2 if layout == 2 else 1
        cur[5] = 0                      # never leave on-pad macro record mode on
        self.request(0x09, 0x01, bytes(cur))

    def set_gamepad_state_report(self, mode):
        """0 off, 1 original, 2 mapped: streams 06 1a 0a 03 state reports."""
        self.request(0x0A, 0x02, bytes([mode]))

    def get_vibrate_level(self):
        b = self.request(0x06, 0x02)
        return b[0], b[1]

    def set_vibrate_level(self, left, right):
        """Stored per-grip rumble intensity, 0-100 %. Sent exactly as GameSir
        Connect 1.17.5 does (06 01 L R 00 00 00 00; capture-vibration-1.17.5.txt)."""
        if not (0 <= left <= 100 and 0 <= right <= 100):
            raise ProtocolError('vibration level is 0-100')
        self.request(0x06, 0x01, bytes([left, right, 0, 0, 0, 0]))

    def vibrate_test(self, left, right):
        """Direct motor drive, 0-255 per grip (255 is clearly stronger than 100
        on the pad). The pad's stored vibrate level (GetVibrateLevel, 75 % by
        default) may still scale it."""
        self.request(0x0A, 0x04, bytes([left, right, 0, 0]))
