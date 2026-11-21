#!/usr/bin/env python3
"""t3pro-bridge: GameSir Tarantula Pro (dongle 3537:103e) -> virtual DualShock 4.

Reads the pad's full state (sticks, triggers, every button, accelerometer and
gyro) from the dongle's vendor channel and feeds a virtual DS4 through
/dev/uhid. The kernel's hid-playstation driver and Steam treat it as a real
DS4, so gyro works in Steam Input. DS4 rumble is forwarded to the pad.

The real XInput node ("Generic X-Box pad") is grabbed while the bridge runs so
games and Steam see only the virtual DS4.

Usage: t3pro_bridge.py [--no-grab] [--original] [--invert-yaw] [--gyro-lsb 13.4]
"""
import argparse
import fcntl
import os
import select
import signal
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from vendors.gamesir.models.t3pro import protocol as p  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t3pro_macros  # noqa: E402

# ---- UHID -----------------------------------------------------------------
UHID_START, UHID_STOP, UHID_OPEN, UHID_CLOSE, UHID_OUTPUT = 2, 3, 4, 5, 6
UHID_GET_REPORT, UHID_GET_REPORT_REPLY = 9, 10
UHID_CREATE2, UHID_INPUT2 = 11, 12
UHID_SET_REPORT, UHID_SET_REPORT_REPLY = 13, 14
UHID_DESTROY = 1
EV_SIZE = 4380
BUS_USB = 3
SONY, DS4V2 = 0x054C, 0x09CC

# Minimal DS4-compatible descriptor: report ids and sizes are what
# hid-playstation and SDL/Steam expect (input 0x01 = 64 bytes, output 0x05,
# feature 0x02 calibration, 0x12 pairing/MAC, 0xa3 firmware info).
RDESC = bytes.fromhex(
    '05010905a101'
    '8501' '0930093109320935' '150026ff00' '7508' '9504' '8102'   # sticks
    '0600ff0920' '953b' '8102'                                   # rest of report 1 (59 bytes)
    '8505' '0921' '951f' '9102'                                  # output 0x05, 31 bytes
    '8502' '0924' '9524' 'b102'                                  # feature 0x02, 36 bytes
    '8512' '0925' '950f' 'b102'                                  # feature 0x12, 15 bytes
    '85a3' '0926' '9530' 'b102'                                  # feature 0xa3, 48 bytes
    'c0')

# DS4 standard sensitivities: gyro ~16.1 LSB/deg/s, accel 8192 LSB/g.
DS4_GYRO_LSB = 8704 / 540
GYRO_RANGE, GYRO_SPEED, ACC_RANGE = 8704, 540, 8192


def calibration_report():
    b = bytearray(37)
    b[0] = 0x02
    vals = [0, 0, 0,                                   # gyro bias pitch/yaw/roll
            GYRO_RANGE, -GYRO_RANGE, GYRO_RANGE, -GYRO_RANGE, GYRO_RANGE, -GYRO_RANGE,
            GYRO_SPEED, GYRO_SPEED,
            ACC_RANGE, -ACC_RANGE, ACC_RANGE, -ACC_RANGE, ACC_RANGE, -ACC_RANGE]
    struct.pack_into('<17h', b, 1, *vals)
    return bytes(b)


def pairing_report(mac):
    b = bytearray(16)
    b[0] = 0x12
    b[1:7] = bytes(reversed(mac))        # DS4 sends the MAC little-endian
    return bytes(b)


def firmware_report():
    b = bytearray(49)
    b[0] = 0xA3
    struct.pack_into('<H', b, 35, 0xB40C)
    struct.pack_into('<H', b, 41, 0xA00A)
    return bytes(b)


class Uhid:
    def __init__(self, mac, name='GameSir Tarantula Pro (DS4 bridge)'):
        self.fd = os.open('/dev/uhid', os.O_RDWR | os.O_CLOEXEC)
        self.features = {0x02: calibration_report(), 0x12: pairing_report(mac),
                         0xA3: firmware_report(), 0x81: bytes([0x81]) + bytes(reversed(mac))}
        ev = bytearray(EV_SIZE)
        struct.pack_into('<I', ev, 0, UHID_CREATE2)
        off = 4
        ev[off:off + len(name)] = name.encode()
        ev[off + 128:off + 128 + 9] = b't3pro-uhid'
        uniq = ':'.join(f'{x:02x}' for x in mac).encode()
        ev[off + 192:off + 192 + len(uniq)] = uniq
        struct.pack_into('<HHIIII', ev, off + 256, len(RDESC), BUS_USB, SONY, DS4V2, 0x0100, 0)
        ev[off + 276:off + 276 + len(RDESC)] = RDESC
        os.write(self.fd, ev)

    def send(self, report):
        ev = bytearray(EV_SIZE)
        struct.pack_into('<IH', ev, 0, UHID_INPUT2, len(report))
        ev[6:6 + len(report)] = report
        os.write(self.fd, ev)

    def handle(self, on_output):
        """Process one kernel->user event (call when fd is readable)."""
        ev = os.read(self.fd, EV_SIZE)
        typ = struct.unpack_from('<I', ev, 0)[0]
        if typ == UHID_GET_REPORT:
            rid, rnum, _rtype = struct.unpack_from('<IBB', ev, 4)
            data = self.features.get(rnum)
            print(f'GET_REPORT 0x{rnum:02x} -> {"ok" if data else "unsupported"}', flush=True)
            rep = bytearray(EV_SIZE)
            if data is None:
                struct.pack_into('<IIHH', rep, 0, UHID_GET_REPORT_REPLY, rid, 5, 0)  # EIO
            else:
                struct.pack_into('<IIHH', rep, 0, UHID_GET_REPORT_REPLY, rid, 0, len(data))
                rep[12:12 + len(data)] = data
            os.write(self.fd, rep)
        elif typ == UHID_SET_REPORT:
            rid, rnum = struct.unpack_from('<IB', ev, 4)
            print(f'SET_REPORT 0x{rnum:02x}', flush=True)
            rep = bytearray(EV_SIZE)
            struct.pack_into('<IIH', rep, 0, UHID_SET_REPORT_REPLY, rid, 0)
            os.write(self.fd, rep)
        elif typ == UHID_OUTPUT:
            size = struct.unpack_from('<H', ev, 4 + 4096)[0]
            if not getattr(self, '_out_seen', False):
                self._out_seen = True
                print(f'first OUTPUT report: {bytes(ev[4:4 + min(size, 12)]).hex(" ")}', flush=True)
            on_output(bytes(ev[4:4 + size]))

    def close(self):
        ev = bytearray(EV_SIZE)
        struct.pack_into('<I', ev, 0, UHID_DESTROY)
        try:
            os.write(self.fd, ev)
        finally:
            os.close(self.fd)


# ---- state -> DS4 report ----------------------------------------------------
HAT = {(0, 0, 0, 0): 8, (1, 0, 0, 0): 0, (1, 1, 0, 0): 1, (0, 1, 0, 0): 2, (0, 1, 1, 0): 3,
       (0, 0, 1, 0): 4, (0, 0, 1, 1): 5, (0, 0, 0, 1): 6, (1, 0, 0, 1): 7}


def clamp16(v):
    return max(-32768, min(32767, int(round(v))))


class Mapper:
    def __init__(self, gyro_lsb, invert_yaw):
        self.k = DS4_GYRO_LSB / gyro_lsb
        self.yaw_sign = -1 if invert_yaw else 1
        self.t0 = time.monotonic()
        self.counter = 0

    def ds4(self, e):
        bit = lambda i, b: e[i] >> b & 1  # noqa: E731
        up, right, down, left = bit(7, 6), bit(7, 5), bit(7, 7), bit(7, 4)
        hat = HAT.get((up, right, down, left), 8)
        r = bytearray(64)
        r[0] = 0x01
        r[1:5] = e[0:4]
        r[5] = hat | bit(6, 3) << 4 | bit(6, 1) << 5 | bit(6, 0) << 6 | bit(6, 2) << 7  # X A B Y
        r[6] = (bit(6, 4) | bit(6, 7) << 1 | bit(6, 5) << 2 | bit(7, 0) << 3 |
                bit(7, 2) << 4 | bit(7, 3) << 5 | bit(6, 6) << 6 | bit(7, 1) << 7)
        self.counter = (self.counter + 1) & 0x3F
        r[7] = bit(8, 0) | bit(8, 1) << 1 | self.counter << 2          # PS, touchpad click = Camera
        r[8], r[9] = e[4], e[5]
        ts = int((time.monotonic() - self.t0) * 1e6 / 5.33) & 0xFFFF
        struct.pack_into('<H', r, 10, ts)
        ax, ay, az = struct.unpack_from('>hhh', e, 11)
        g0, g1, g2 = struct.unpack_from('>hhh', e, 17)
        # pad frame: x right, y toward the player, z up (accel); DS4: x right, y up, z toward player
        gx = -g0 * self.k                  # pitch
        gy = self.yaw_sign * g2 * self.k   # yaw
        gz = -g1 * self.k                  # roll
        struct.pack_into('<hhhhhh', r, 13, clamp16(gx), clamp16(gy), clamp16(gz),
                         clamp16(ax * 2), clamp16(az * 2), clamp16(ay * 2))
        r[30] = 0x08                       # battery full, no cable
        r[33] = 0
        r[35] = r[39] = 0x80               # no touch
        return bytes(r)


CONFIG = os.path.expanduser('~/.config/t3pro/bridge.json')


def load_config():
    try:
        import json
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def grab_xpad():
    """EVIOCGRAB the real XInput node so only the virtual DS4 is seen."""
    EVIOCGRAB = 0x40044590
    for name in sorted(os.listdir('/sys/class/input')):
        if not name.startswith('event'):
            continue
        base = f'/sys/class/input/{name}/device'
        try:
            vid = open(f'{base}/id/vendor').read().strip()
            pid = open(f'{base}/id/product').read().strip()
            dname = open(f'{base}/name').read().strip()
        except OSError:
            continue
        if vid == '3537' and pid == '103e' and 'X-Box' in dname:
            fd = os.open(f'/dev/input/{name}', os.O_RDONLY | os.O_NONBLOCK)
            fcntl.ioctl(fd, EVIOCGRAB, 1)
            return fd, name
    return None, None


SIGNAL_EVKEYS = {}       # evdev key code -> back button, filled in main()


def open_dongle_keyboard():
    """The dongle's HID keyboard interface (where pad keyboard remaps and the
    back buttons' signal keys arrive). Read without grabbing."""
    for name in sorted(os.listdir('/sys/class/input')):
        if not name.startswith('event'):
            continue
        base = f'/sys/class/input/{name}/device'
        try:
            vid = open(f'{base}/id/vendor').read().strip()
            pid = open(f'{base}/id/product').read().strip()
            dname = open(f'{base}/name').read().strip()
        except OSError:
            continue
        if vid == '3537' and pid == '103e' and dname.endswith('Keyboard'):
            try:
                return os.open(f'/dev/input/{name}', os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                return None
    return None


def run_shortcuts_only():
    """"ds4": false in the config: no virtual DS4, no grab, no state stream.
    Steam keeps the real GameSir Xbox controller; the pad does its own gyro /
    macros. Only the back-button PC shortcuts (signal keys on the dongle
    keyboard) run here. HOME + button chords are off: without the virtual pad
    HOME can't be hidden from Steam."""
    from evdev import ecodes
    chords = t3pro_macros.HomeChords(log=lambda m: print(m, flush=True))
    sig = {ecodes.ecodes['KEY_' + k]: b for b, k in p.SIGNAL_KEYS.items()}
    fmt = 'llHHi'
    sz = struct.calcsize(fmt)
    kfd = None
    for _ in range(10):                     # the keyboard node may lag the hidraw one
        kfd = open_dongle_keyboard()
        if kfd is not None:
            break
        time.sleep(0.5)
    if kfd is None:
        print('dongle keyboard not found; exiting', flush=True)
        return
    try:                                    # leave the pad's own stream off
        with p.Tarantula() as t:
            t.set_gamepad_state_report(0)
    except (p.ProtocolError, OSError):
        pass
    print('shortcuts-only mode: no virtual DS4, Steam uses the real controller', flush=True)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    try:
        while not stop:
            timeout = 0.005 if chords.busy() else 1.0
            rl, _, _ = select.select([kfd], [], [], timeout)
            now = time.monotonic()
            if rl:
                try:
                    data = os.read(kfd, sz * 64)
                except BlockingIOError:
                    data = b''
                except OSError:
                    break                   # dongle unplugged
                for off in range(0, len(data) - sz + 1, sz):
                    _, _, etype, code, value = struct.unpack_from(fmt, data, off)
                    if etype == ecodes.EV_KEY and value == 1 and code in sig:
                        chords.trigger_solo(sig[code], now)
            chords.tick(now)                # pad steps are ignored: nothing to send them to
    finally:
        chords.close()
        os.close(kfd)
        print('bridge stopped', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-grab', action='store_true', help='leave the real XInput pad visible')
    ap.add_argument('--original', action='store_true',
                    help='raw buttons (ignore on-pad remaps/macros); default is the mapped state')
    ap.add_argument('--invert-yaw', action='store_true')
    ap.add_argument('--gyro-lsb', type=float, default=13.4, help='pad gyro LSB per deg/s')
    ap.add_argument('--rumble-gain', type=float, default=None,
                    help='software rumble gain, 0.0-2.0 (default: live from the config file)')
    a = ap.parse_args()

    if not load_config().get('ds4', True):
        return run_shortcuts_only()

    pad = None
    while pad is None:                     # dongle may come up before the pad wakes
        try:
            pad = p.Tarantula()
            info = pad.device_info()
        except (p.ProtocolError, OSError) as e:
            if pad is not None:
                pad.close()
                pad = None
            if p.find_hidraw() is None:
                print('dongle not present; exiting', flush=True)
                return
            print(f'waiting for the pad ({e})', flush=True)
            time.sleep(3)
    mac = bytes.fromhex(info['mac'].replace(':', ''))
    pad.set_gamepad_state_report(1 if a.original else 2)
    uhid = Uhid(mac)
    gfd, gname = (None, None) if a.no_grab else grab_xpad()
    mapper = Mapper(a.gyro_lsb, a.invert_yaw)
    chords = t3pro_macros.HomeChords(log=lambda m: print(m, flush=True))
    last_e = None
    from evdev import ecodes
    for btn, key in p.SIGNAL_KEYS.items():
        SIGNAL_EVKEYS[ecodes.ecodes['KEY_' + key]] = btn
    kfd = open_dongle_keyboard()
    print(f'dongle keyboard: {"watching" if kfd is not None else "not found"}', flush=True)
    EV_FMT = 'llHHi'
    EV_SZ = struct.calcsize(EV_FMT)
    print(f'bridge up: pad fw {info["firmware"]}, battery {info["battery"]}%, '
          f'xpad grab: {gname or "off"}', flush=True)

    last_rumble = [0, 0]

    def on_output(rep):
        if rep and rep[0] == 0x05 and len(rep) >= 6:
            weak, strong = rep[4], rep[5]
            g = max(0.0, min(2.0, a.rumble_gain if a.rumble_gain is not None else chords.gain))
            want = [min(255, int(strong * g)), min(255, int(weak * g))]  # pad takes 0-255
            if want != last_rumble:
                print(f'rumble from host: strong={strong} weak={weak} -> pad L={want[0]} R={want[1]}', flush=True)
                last_rumble[:] = want
                try:
                    pad.vibrate_test(*want)
                except p.ProtocolError:
                    pass

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    last_rx = time.monotonic()
    last_keep = time.monotonic()
    try:
        while not stop:
            rl, _, _ = select.select([pad.fd, uhid.fd] + ([kfd] if kfd is not None else []), [], [],
                                     0.005 if (chords.busy() or chords.phase != 'idle') else 0.5)
            if uhid.fd in rl:
                uhid.handle(on_output)
            if kfd is not None and kfd in rl:
                try:
                    data = os.read(kfd, EV_SZ * 64)
                except BlockingIOError:
                    data = b''
                except OSError:
                    data, kfd = b'', None
                for off in range(0, len(data) - EV_SZ + 1, EV_SZ):
                    _, _, etype, code, value = struct.unpack_from(EV_FMT, data, off)
                    if etype == ecodes.EV_KEY and value == 1 and code in SIGNAL_EVKEYS:
                        chords.trigger_solo(SIGNAL_EVKEYS[code], time.monotonic())
            if pad.fd in rl:
                while True:
                    try:
                        r = os.read(pad.fd, 64)
                    except BlockingIOError:
                        break
                    except OSError:            # dongle unplugged
                        stop.append(1)
                        break
                    if r[:4] == bytes([6, 0x1A, 0x0A, 3]):
                        last_e = r[4:]
                        now = time.monotonic()
                        chords.feed(last_e, now)
                        chords.tick(now)
                        uhid.send(mapper.ds4(chords.render(last_e)))
                        last_rx = now
            now = time.monotonic()
            if last_e is not None and chords.tick(now):
                uhid.send(mapper.ds4(chords.render(last_e)))   # macro edge between pad frames
            if now - last_rx > 2 and now - last_keep > 2:
                # pad slept or the dongle reset: re-enable the stream
                last_keep = now
                try:
                    pad.set_gamepad_state_report(1 if a.original else 2)
                except (p.ProtocolError, OSError):
                    pass
    finally:
        try:
            pad.vibrate_test(0, 0)
            pad.set_gamepad_state_report(0)
        except (p.ProtocolError, OSError):
            pass
        chords.close()
        if kfd is not None:
            os.close(kfd)
        uhid.close()
        try:
            pad.close()
        except OSError:
            pass
        if gfd is not None:
            os.close(gfd)
        print('bridge stopped', flush=True)


if __name__ == '__main__':
    main()
