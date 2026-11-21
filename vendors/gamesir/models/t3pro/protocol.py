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

    def set_light_param(self, brightness, speed, mode):
        self.request(0x07, 0x01, bytes([brightness, speed, mode]))

    def set_light_color(self, zone, leds):
        """leds: list of (h, s, v) as the wire carries them (h 0-255, s/v 0-100)."""
        payload = bytes([zone]) + b''.join(bytes(l) for l in leds)
        self.request(0x07, 0x03, payload)

    @staticmethod
    def mapping_body(key, mapping_type, codes, turbo_times=1):
        """16-byte key-mapping body as on the wire:
        page, trigger, colour[4], key, toggle, turboMode, turboTimes,
        mappingType, count, codes[4]."""
        codes = tuple(codes)[:4]
        return bytes([0, 0, 0, 0, 0, 0, key, 0, 0, turbo_times if codes else 0,
                      mapping_type, len(codes)]) + bytes(codes) + bytes(4 - len(codes))

    def clear_macro(self, key):
        """Drop the macro and map the key back to itself (its default)."""
        k = KEYS[key]
        self.request(0x01, 0x01, bytes([k, 0xFF]) + bytes(14))
        self.set_key_mapping_raw(self.mapping_body(k, MAP_JOYSTICK, (k,)))

    def set_key_mapping_raw(self, raw):
        """raw = the 16-byte body exactly as GetKeyMapping returns it."""
        self.request(0x05, 0x01, raw)

    def set_macro(self, key, steps, hold_to_trigger=False, loop=False, loop_time_ms=0):
        """steps: list of (button, start_ms, end_ms). Mirrors the app: first a
        Clear step, then each step with absolute start/end. Despite the SDK's
        "In10MS" field names the T3Pro takes MILLISECONDS (the app passes no
        timeScale for it; hardware-verified: 0-300 / 900-1200 played as A 300 ms,
        600 ms gap, B 300 ms)."""
        k = KEYS[key]
        if key not in MACRO_KEYS:
            raise ProtocolError(f'{key} cannot hold a macro (allowed: {", ".join(MACRO_KEYS)})')
        if len(steps) > MACRO_MAX_STEPS:
            raise ProtocolError(f'at most {MACRO_MAX_STEPS} steps')
        # A key runs its macro only when its mapping is Vacant (main.js Ie()).
        self.set_key_mapping_raw(self.mapping_body(k, MAP_VACANT, ()))
        self.request(0x01, 0x01, bytes([k, 0xFF]) + bytes(14))
        lt = loop_time_ms
        trig = TRIGGER['hold'] if hold_to_trigger else TRIGGER['oneshot']
        for i, (btn, start, end) in enumerate(steps):
            s, e = start, end
            body = bytes([k, i, trig, 1 if loop else 0, lt >> 8, lt & 0xFF,
                          MAP_JOYSTICK, 1, KEYS[btn], 0, 0, 0,
                          s >> 8, s & 0xFF, e >> 8, e & 0xFF])
            self.request(0x01, 0x01, body)

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
