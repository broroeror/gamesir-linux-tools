"""
GameSir Cyclone 2 - read / connection loop
==========================================
The background side: keep the controller open, maintain the heartbeat, poll the
profile + lighting slot, and parse the 0x12 enhanced stream into shared `state`.

Survives unplugging the cable (it keeps working over the 2.4GHz dongle), mode
switches, and hidraw node renumbering on re-enumeration.
"""

import errno
import fcntl
import math
import os
import select
import struct
import threading
import time
import hid

from gs_common import (find_controllers, pick_live_node, firmware_version,
                       device_bcd, evdev_port, has_live_pad)
from vendors.gamesir.enhanced import parse_enhanced
from gs_state import state
import vendors.gamesir.control as control
import controller_profile as profiles
from vendors.gamesir.models.g7pro import protocol as g7pro


_active_g7_handle = None
_g7_transition_last = {}
_G7_TRANSITION_INTERVAL = 5.0
_G7_TRANSITION_TIMEOUT = 10.0


def release_controller():
    """Best-effort synchronous release used by the GUI shutdown hook."""
    global _active_g7_handle
    state['config_wanted'] = False
    handle = _active_g7_handle
    if handle is not None:
        try:
            handle.close()
        except Exception:
            pass
        _active_g7_handle = None


def _is_wired(prof, pid, bcd):
    """Best-effort 'is this the WIRED controller vs its wireless dongle?' in NORMAL
    mode (True wired / False dongle / None unknown). The authoritative discriminator
    is the flash-header identity (GS_C2_Dongle vs GS_C2_ADC_DEVICE) but it's only
    readable in the loader; here we tell them apart from the USB identity we already
    opened. Used only for a DISPLAY hint + a firmware-panel warning — never to gate a
    flash (the in-loader identity guard does that).
      * 8K: each edition ships its own (wired, dongle) PID pair, so the profile
        declares which ids are the wired face (an idle dongle reads 0x0575).
      * Cyclone: the controller's own firmware is the 3.x namespace, the dongle's is
        1.x — so a bcdDevice >= 2.0 is the wired controller, below it is the dongle."""
    if prof is profiles.G7_PRO:
        return g7pro.connection_kind(pid)
    if prof is not None and prof.wired_products:
        return pid in prof.wired_products
    if prof is profiles.CYCLONE and bcd:
        return bcd >= 0x0200
    return None


def maintenance_loop(alive):
    """Sustained heartbeat (keeps Xbox-mode enhanced reports + command channel
    alive) plus periodic queries so the displayed gamepad profile AND lighting
    slot track reality, including changes made via the M + right-stick gesture.

    The two queries are ALTERNATED, never sent back-to-back: the controller
    drops the second command when they arrive too close together, which silently
    starves whichever query is sent second."""
    last_query = 0.0
    toggle = 0
    # These are session-maintenance probes (heartbeat + state queries), not app
    # writes, so they pass probe=True to bypass the recognized-model guard in
    # send_cmd -- they keep the stream alive and read state without changing it.
    while alive[0]:
        control.send_cmd(0x0F, 0xF2, probe=True)
        now = time.time()
        if now - last_query > 0.45:
            if toggle == 0:
                control.send_cmd(0x0F, 0x0B, probe=True)                          # profile -> 0x10 0x0C
            else:
                control.send_cmd(0x0F, 0x04, 0x20, 0x00, 0x00, 0x01, probe=True)  # lighting slot -> 0x10 0x05
            toggle ^= 1
            last_query = now
        time.sleep(0.5)


_live_cache = {}       # device identity -> bool (see _probe_live)


def _live_key(ctrl):
    return (ctrl['port'], ctrl['pid'], ctrl.get('product') or '')


def _probe_live(ctrl, prof=None):
    """Is a controller actually behind this device (vs an empty dongle)?

    Probing opens the node for ~1s, so results are CACHED per device identity and
    only re-probed when that identity changes. That's enough, because a pad powering
    on/off re-enumerates its dongle (Cyclone 0x0575<->0x100b, 8K 0x0575<->0x10c8),
    which changes the key on exactly the transitions that matter."""
    if state.get('driving') == ctrl['id']:
        return True                       # we're streaming it right now
    if prof is None:
        prof = profiles.detect_one(ctrl['pid'], ctrl.get('product'))
    # The G7 family speaks GIP over evdev and NEVER emits the 0x12 vendor stream,
    # so the probe can't see it and would brand a perfectly live pad an empty
    # dongle. We have no empty-vs-live signal for those — assume live.
    if prof is not None and prof.input_style == 'evdev':
        return True
    key = _live_key(ctrl)
    if key not in _live_cache:
        _live_cache[key] = has_live_pad(ctrl['nodes'])
    return _live_cache[key]


def _label(ctrl):
    """Public shape of a controller for the UI picker. Uses the product-aware
    detect_one (not PID-only) so the 8K's wireless dongle — which shares the
    Cyclone's 0x0575 PID but reports product 'Gamepad' — is labelled 'G7 Pro 8K PC',
    not a third 'Cyclone 2'.

    `live` distinguishes a real controller from a plugged-in but EMPTY dongle (which
    otherwise shows as a phantom controller); `wired` drives the connection icon."""
    prof = profiles.detect_one(ctrl['pid'], ctrl.get('product'))
    bcd = ctrl.get('bcd') or (device_bcd(ctrl['nodes'][0]) if ctrl['nodes'] else None)
    return {'id': ctrl['id'], 'name': prof.short if prof else 'Unknown',
            'port': ctrl['port'], 'pid': ctrl['pid'],
            'live': _probe_live(ctrl, prof),
            'wired': _is_wired(prof, ctrl['pid'], bcd)}


def _publish_controllers(controllers):
    if state.get('demo'):
        return                       # demo mode owns the (synthetic) controller list
    state['controllers'] = [_label(c) for c in controllers]


def _pick_selected(controllers):
    """Drive the user's selected controller if it's still connected, otherwise
    default to the first one with a real controller behind it.

    An empty dongle is still driveable on purpose: `live` is False both for a dongle
    with nothing paired AND for a pad in a non-Xbox mode (the vendor channel is
    Xbox-only), so refusing to drive it would silence the "switch to Xbox mode"
    warning. Preferring a live unit just means an idle dongle never steals focus
    from a working controller."""
    sel = state.get('selected')
    for c in controllers:
        if c['id'] == sel:
            return c
    return next((c for c in controllers if _probe_live(c)), controllers[0])





def read_session(device, driving_id):
    """Read one open controller until it errors, is unplugged, or the user
    selects a DIFFERENT controller. Returns so read_controller can reconnect.

    `driving_id` is the controller we opened; we rescan ~1 Hz to keep the picker
    list fresh and to notice an unplug / a selection change without blocking."""
    control.set_device(device)
    state['driving'] = driving_id      # this unit's vendor session is now open
    alive = [True]
    threading.Thread(target=maintenance_loop, args=(alive,), daemon=True).start()
    last_scan = 0.0
    try:
        while True:
            if state.get('demo'):      # demo mode took over: release the live
                break                   # device so read_controller can idle it
            control.pump_reads()   # keep queued register reads moving
            now = time.time()
            if now - last_scan > 1.0:
                last_scan = now
                ids = [c['id'] for c in _rescan()]
                if driving_id not in ids:           # our controller unplugged
                    break
                sel = state.get('selected')
                if sel in ids and sel != driving_id:  # user switched controllers
                    break
            data = device.read(64, timeout_ms=200)
            if state.get('demo'):          # demo flipped on during the blocking
                break                       # read — bail before stamping any state
            if not data:
                continue
            if data[0] == 0x10 and data[1] == 0x0C:     # get-profile reply
                state['profile'] = data[2]
                state['edit_profile'] = data[2]
                continue
            if data[0] == 0x10 and data[1] == 0x05:     # read-register reply
                bank = data[2]
                addr = (data[3] << 8) | data[4]
                ln = data[5]
                control.store_reg_result(bank, addr, list(data[6:6 + ln]))
                if bank == 0x20 and addr == 0x0000:     # lighting selector
                    state['led_slot'] = data[6]
                continue
            if data[0] != 0x12:
                continue
            # Outside Xbox mode the 0x12 report streams all-zeros (sticks read 0,
            # not the 128 rest value). Treat that as "wrong mode".
            if data[1] == 0 and data[2] == 0 and data[3] == 0 and data[4] == 0:
                state['mode_ok'] = False
                continue
            state['mode_ok'] = True
            state.update(parse_enhanced(data))
    except Exception:
        pass
    finally:
        alive[0] = False
        control.clear_device()
        if not state.get('demo'):      # in demo the bridge owns driving
            state['driving'] = None    # vendor session closed


def _rescan():
    """Re-enumerate controllers and publish the list; returns the controllers.

    Empty dongles are listed (flagged `live: False`) rather than hidden, so a
    plugged-in adapter with nothing paired to it is visible AS an idle dongle
    instead of masquerading as a controller."""
    controllers = find_controllers()
    _prune_live_cache(controllers)
    _publish_controllers(controllers)
    return controllers


def _prune_live_cache(controllers):
    """Forget probe results for devices that are gone, so the cache can't grow
    without bound across replugs."""
    keys = {_live_key(c) for c in controllers}
    for k in [k for k in _live_cache if k not in keys]:
        _live_cache.pop(k, None)


def read_controller():
    """Continuously enumerate controllers, open the SELECTED one, and read it;
    reconnect on drop or when the user picks a different controller."""
    last_id = None      # id of the unit we last drove; used to blank the profile
                        # only when the driven UNIT changes (not on every reconnect)
    while True:
        # Demo mode: the bridge owns `state` (a synthetic controller) and there's
        # no hardware to read, so idle here instead of scanning/blanking it, and
        # answer the bridge's queued register reads with defaults.
        if state.get('demo'):
            control.pump_demo_reads()
            time.sleep(0.05)
            continue
        controllers = _rescan()
        if not controllers:
            if state.get('demo'):       # demo flipped on during the scan: the
                time.sleep(0.3)         # bridge owns state now — don't blank it
                continue
            state['connected'] = False
            state['mode_ok'] = False
            state['controller'] = None
            state['wired'] = None
            state['selected'] = None
            state['driving'] = None
            state['access'] = None      # nothing found ≠ found-but-blocked
            state['edit_profile'] = None
            state['config_claimed'] = False
            state['config_status'] = ''
            profiles.set_active(None)   # nothing connected: mark unrecognised
            time.sleep(1.0)
            continue

        sel = _pick_selected(controllers)
        state['selected'] = sel['id']
        if sel['id'] != last_id:
            state['profile'] = None    # different unit: don't carry the old one's
            state['edit_profile'] = None
            last_id = sel['id']        # profile number onto it (drives bank select)
        prof = profiles.detect_one(sel['pid'], sel.get('product'))
        profiles.set_active(prof)                      # rest of app follows this
        state['controller'] = prof.short if prof else None
        # Pin the version to THIS physical unit (bcdDevice on one of its nodes),
        # not the first device with this pid — matters with two identical units.
        _bcd = sel.get('bcd') or (device_bcd(sel['nodes'][0]) if sel['nodes'] else None)
        state['firmware'] = firmware_version(sel['nodes'][0]) if sel['nodes'] else (
            f'{_bcd >> 8:x}.{_bcd & 0xff:02x}' if _bcd else None)
        state['wired'] = _is_wired(prof, sel['pid'], _bcd)   # wired / dongle hint

        if prof is profiles.G7_PRO:
            state['connected'] = True
            if state.get('config_wanted', True):
                if sel['pid'] in g7pro.TRANSITION_PIDS:
                    transition_g7_identity(sel)
                else:
                    read_session_g7usb(sel)
            else:
                state['config_status'] = 'Released to games'
                read_session_evdev(sel['id'])
            if state.get('demo'):
                continue
            state['connected'] = False
            state['mode_ok'] = False
            time.sleep(0.3)
            continue

        if prof is profiles.G7_NATIVE:
            state['connected'] = True
            state['mode_ok'] = False
            state['config_status'] = 'Hold MENU (START) + SHARE to switch to XInput mode'
            read_session_evdev(sel['id'], force_wrong_mode=True)
            state['connected'] = False
            time.sleep(0.3)
            continue

        # G7-family: input arrives over evdev (standard gamepad), not a vendor
        # hidraw stream, so read that instead of the Cyclone 0x12 path.
        if prof is not None and prof.input_style == 'evdev':
            state['connected'] = True
            read_session_evdev(sel['id'])   # blocks until drop / switch
            if state.get('demo'):           # demo took over: leave its state alone
                continue
            state['connected'] = False
            state['mode_ok'] = False
            time.sleep(0.3)
            continue

        # Cyclone: vendor hidraw 0x12 stream.
        devnode = pick_live_node(sel['nodes'])
        if not devnode:
            state['connected'] = False
            time.sleep(1.0)
            continue
        try:
            device = hid.device()
            device.open_path(devnode.encode())
            device.set_nonblocking(True)
        except Exception:
            state['connected'] = False
            # Say WHY it failed: a found-but-unopenable controller looked like
            # an eternal "Searching…" (issue #1) when it was really a udev-
            # permission (or hidapi-backend) problem. The bridge shows a banner
            # with the one-time fix.
            try:
                from doctor import classify_open_failure
                state['access'] = classify_open_failure(devnode)
            except Exception:
                state['access'] = None
            time.sleep(1.0)
            continue

        state['access'] = 'ok'
        state['connected'] = True
        read_session(device, sel['id'])   # blocks until drop / switch
        try:
            device.close()
        except Exception:
            pass
        if state.get('demo'):             # demo took over mid-session: don't blank
            continue                       # the bridge-owned state on the way out
        state['connected'] = False
        state['mode_ok'] = False
        time.sleep(0.3)   # brief pause before reconnecting


# --- evdev input path (G7 family) -------------------------------------------
# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
# 64-bit timeval = 2*long -> 24 bytes total. (Shared with press_select_loop.)
_EV_FMT = 'llHHi'
_EV_SIZE = struct.calcsize(_EV_FMT)
_EV_KEY, _EV_ABS = 1, 3


# EVIOCGABS(code) = _IOR('E', 0x40+code, struct input_absinfo) — read an axis's
# min/max so we can normalise it to the app's 0..255 (sticks) / 0..255 (triggers).
def _eviocgabs(code):
    return (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code)


_KEY_TO_STATE = {           # Linux gamepad button codes -> state keys
    0x130: 'a', 0x131: 'b', 0x133: 'y', 0x134: 'x',
    0x136: 'lb', 0x137: 'rb', 0x13a: 'view', 0x13b: 'menu',
    0x13c: 'home', 0x13d: 'ls', 0x13e: 'rs',
    0x138: 'lt_d', 0x139: 'rt_d',
}
# ABS axis codes we care about (ignoring the HAT dpad, handled separately).
_ABS_CANDIDATES = (0, 1, 2, 3, 4, 5, 9, 10)
_HAT = {(0, 0): 'neutral', (0, -1): 'up', (1, -1): 'up-right', (1, 0): 'right',
        (1, 1): 'down-right', (0, 1): 'down', (-1, 1): 'down-left',
        (-1, 0): 'left', (-1, -1): 'up-left'}


def _axis_map(present):
    """Map a device's PRESENT ABS codes to state keys, handling both gamepad
    conventions: classic (right stick = RX/RY 3/4, triggers = Z/RZ 2/5) and
    modern (right stick = Z/RZ 2/5, triggers = GAS/BRAKE 9/10, as on the G7 Pro).
    Left stick is always X/Y."""
    m = {}
    if 0 in present:
        m[0] = 'lx'
    if 1 in present:
        m[1] = 'ly'
    if 3 in present and 4 in present:       # classic: RS on RX/RY
        m[3] = 'rx'; m[4] = 'ry'
        if 2 in present:
            m[2] = 'lt'
        if 5 in present:
            m[5] = 'rt'
    else:                                   # modern: RS on Z/RZ
        if 2 in present:
            m[2] = 'rx'
        if 5 in present:
            m[5] = 'ry'
    if 9 in present:                        # ABS_GAS = RT
        m[9] = 'rt'
    if 10 in present:                       # ABS_BRAKE = LT
        m[10] = 'lt'
    return m


def _scale(value, lo, hi):
    """Normalise an evdev axis value in [lo,hi] to 0..255."""
    if hi <= lo:
        return 128
    return max(0, min(255, round((value - lo) * 255 / (hi - lo))))


def _absinfo(fd, code):
    """(min, max) for an axis on this fd, or None if it lacks the axis."""
    buf = bytearray(24)
    try:
        fcntl.ioctl(fd, _eviocgabs(code), buf, True)
    except OSError:
        return None
    _v, mn, mx, _f, _fl, _r = struct.unpack('6i', bytes(buf))
    return (mn, mx) if mx > mn else None


def read_session_evdev(driving_id, force_wrong_mode=False):
    """Read one G7-family controller's live input over evdev until it errors, is
    unplugged, or the user selects another controller. Maps standard gamepad
    events into the shared `state` (sticks/triggers normalised to 0..255)."""
    from gs_common import parse_devices, VENDOR_VID
    fds = {}                # fd -> path
    axmap = {}              # fd -> {abs_code: state_key} for this device
    ranges = {}             # (fd, code) -> (min, max)
    for d in parse_devices():
        if d['vendor'] != VENDOR_VID:
            continue
        for ev in d['events']:
            if evdev_port(ev) != driving_id:
                continue
            try:
                fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            fds[fd] = ev
            present = {}     # code -> (min, max) for axes this node actually has
            for code in _ABS_CANDIDATES:
                r = _absinfo(fd, code)
                if r:
                    present[code] = r
            axmap[fd] = _axis_map(set(present))
            for code, rng in present.items():
                ranges[(fd, code)] = rng
    if not fds:
        state['mode_ok'] = False    # no live evdev node: don't leave a stale True
        time.sleep(1.0)
        return

    state['mode_ok'] = not force_wrong_mode
    hat = {'x': 0, 'y': 0}
    last_scan = time.time()
    try:
        while True:
            if state.get('demo'):                       # demo mode took over
                break
            if profiles.active() is profiles.G7_PRO and state.get('config_wanted'):
                break
            now = time.time()
            if now - last_scan > 1.0:
                last_scan = now
                ids = [c['id'] for c in _rescan()]
                if driving_id not in ids:               # unplugged
                    break
                sel = state.get('selected')
                if sel in ids and sel != driving_id:    # user switched
                    break
            r, _, _ = select.select(list(fds), [], [], 0.2)
            for fd in r:
                try:
                    data = os.read(fd, _EV_SIZE * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    return                               # node vanished
                for i in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                    _, _, etype, code, value = struct.unpack(_EV_FMT, data[i:i + _EV_SIZE])
                    if etype == _EV_KEY:
                        k = _KEY_TO_STATE.get(code)
                        if k:
                            state[k] = bool(value)
                    elif etype == _EV_ABS:
                        key = axmap[fd].get(code)
                        if key:
                            rng = ranges.get((fd, code))
                            if rng:
                                state[key] = _scale(value, *rng)
                        elif code == 16:                 # ABS_HAT0X
                            hat['x'] = (value > 0) - (value < 0)
                            state['dpad'] = _HAT.get((hat['x'], hat['y']), 'neutral')
                        elif code == 17:                 # ABS_HAT0Y
                            hat['y'] = (value > 0) - (value < 0)
                            state['dpad'] = _HAT.get((hat['x'], hat['y']), 'neutral')
    except Exception:
        pass
    finally:
        for fd in list(fds):
            try:
                os.close(fd)
            except OSError:
                pass
        state['mode_ok'] = False


def _connected_age(sysfs):
    """Seconds since this USB identity enumerated, or None if unavailable."""
    try:
        with open(os.path.join(sysfs, 'power', 'connected_duration')) as stream:
            return int(stream.read().strip()) / 1000.0
    except (OSError, ValueError):
        try:
            return max(0.0, time.time() - os.stat(sysfs).st_ctime)
        except OSError:
            return None


def transition_g7_identity(ctrl):
    """Move the G7's 100a HID identity to wired 109b or dongle 109c."""
    global _active_g7_handle
    usbmeta = ctrl.get('usb') or {}
    now = time.monotonic()
    age = _connected_age(usbmeta.get('sysfs', ''))
    wait = max(0.0, _g7_transition_last.get(ctrl['id'], 0.0)
               + _G7_TRANSITION_INTERVAL - now)
    if age is not None:
        wait = max(wait, _G7_TRANSITION_INTERVAL - age)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not state.get('config_wanted', True) or state.get('demo'):
            return False
        remaining = deadline - time.monotonic()
        state['config_status'] = (
            f'Preparing configuration transition… {math.ceil(remaining)}s')
        time.sleep(min(0.1, max(0.0, remaining)))

    handle = None
    state['config_status'] = 'Switching controller to configuration identity…'
    _g7_transition_last[ctrl['id']] = time.monotonic()
    try:
        handle = g7pro.open_transition_device(
            usbmeta['bus'], usbmeta['address'], usbmeta['sysfs'])
        _active_g7_handle = handle
        state['config_claimed'] = True
        state['access'] = 'ok'
        g7pro.send_handshake(handle)
    except Exception as exc:
        state['config_status'] = 'Configuration transition failed: ' + str(exc)
        state['access'] = ('no-access' if getattr(exc, 'errno', None)
                           in (errno.EACCES, errno.EPERM) else None)
        state['config_wanted'] = False
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if _active_g7_handle is handle:
            _active_g7_handle = None
        state['config_claimed'] = False

    state['config_status'] = 'Waiting for controller to re-enumerate…'
    deadline = time.monotonic() + _G7_TRANSITION_TIMEOUT
    while time.monotonic() < deadline:
        if not state.get('config_wanted', True) or state.get('demo'):
            return False
        devices = _rescan()
        current = next((item for item in devices if item['id'] == ctrl['id']), None)
        if current is not None:
            if current['pid'] in g7pro.CONFIG_PIDS:
                state['config_status'] = 'Connecting configuration…'
                return True
            if current['pid'] == g7pro.PID_NATIVE:
                state['config_status'] = (
                    'Hold MENU (START) + SHARE to switch to XInput mode')
                state['config_wanted'] = False
                return False
            if current['pid'] not in g7pro.TRANSITION_PIDS:
                state['config_status'] = (
                    f'Controller reappeared with unsupported USB ID '
                    f'{g7pro.VID:04x}:{current["pid"]:04x}')
                state['config_wanted'] = False
                return False
        time.sleep(0.2)
    state['config_status'] = (
        'Timed out waiting for configuration identity 109b or 109c')
    state['config_wanted'] = False
    return False


def read_session_g7usb(ctrl):
    """Own a ready G7 vendor interface and multiplex config/live input."""
    global _active_g7_handle
    usbmeta = ctrl.get('usb') or {}
    try:
        handle = g7pro.open_device(usbmeta['bus'], usbmeta['address'],
                                   usbmeta['sysfs'])
    except Exception as exc:
        state['config_claimed'] = False
        state['config_status'] = str(exc)
        state['access'] = ('no-access' if getattr(exc, 'errno', None)
                           in (errno.EACCES, errno.EPERM) else None)
        state['mode_ok'] = False
        state['config_wanted'] = False
        return

    _active_g7_handle = handle
    control.set_device(handle)
    state['driving'] = ctrl['id']
    state['config_claimed'] = True
    state['config_status'] = 'Configuring · controller unavailable to games'
    state['access'] = 'ok'
    state['edit_profile'] = state.get('edit_profile') or state.get('profile') or 1
    gen = control.generation()
    last_heartbeat = last_info = last_scan = 0.0
    info_toggle = 0
    session_started = time.monotonic()
    saw_vendor = False
    standard_frames = 0
    telemetry_error = False
    session_error = False
    try:
        for _ in range(3):
            control.g7_heartbeat(gen)
            time.sleep(0.05)
        while state.get('config_wanted', True):
            if state.get('demo'):
                break
            now = time.time()
            control.pump_reads()
            if now - last_heartbeat >= 0.45:
                control.g7_heartbeat(gen)
                last_heartbeat = now
            if now - last_info >= 2.0:
                control.g7_query_info(0x0B if info_toggle == 0 else 0x09, gen)
                info_toggle ^= 1
                last_info = now
            if now - last_scan >= 1.0:
                last_scan = now
                ids = [c['id'] for c in _rescan()]
                if ctrl['id'] not in ids or state.get('selected') not in (None, ctrl['id']):
                    break
            report = handle.read(64, timeout_ms=120)
            if not report:
                continue
            if g7pro.is_standard_input(report):
                standard_frames += 1
                if (not saw_vendor and standard_frames >= 3
                        and time.monotonic() - session_started >= 1.5):
                    telemetry_error = True
                    state['config_wanted'] = False
                    state['config_status'] = (
                        f'USB identity {ctrl["pid"]:04x} returned standard XInput '
                        'reports instead of configuration telemetry')
                    break
                continue
            if len(report) >= 5 and report[0] == 0x10 \
                    and report[3] == g7pro.RESPONSE_MARKER:
                saw_vendor = True
            if g7pro.parse_input(report, state):
                continue
            if len(report) >= 9 and report[0] == 0x10 and report[3] == 0x3C:
                if report[4] == 0x05:
                    bank = report[5]
                    addr = (report[6] << 8) | report[7]
                    ln = report[8]
                    control.store_reg_result(bank, addr, list(report[9:9 + ln]))
                elif report[4] == 0x0C and len(report) > 5:
                    active = report[5]
                    if 1 <= active <= 4:
                        state['profile'] = active
                        if state.get('edit_profile') is None:
                            state['edit_profile'] = active
                elif report[4] == 0x0A:
                    fw = g7pro.firmware_from_payload(report[5:])
                    if fw:
                        state['firmware'] = fw
    except Exception as exc:
        session_error = True
        state['config_wanted'] = False
        state['config_status'] = 'USB session ended: ' + str(exc)
    finally:
        control.clear_device()
        try:
            handle.close()
        except Exception:
            pass
        if _active_g7_handle is handle:
            _active_g7_handle = None
        state['driving'] = None
        state['config_claimed'] = False
        if not state.get('config_wanted') and not telemetry_error and not session_error:
            state['config_status'] = 'Released to games'


# --- press-to-select --------------------------------------------------------
def _maybe_select(port):
    """Switch to `port` if it's a connected controller other than the current
    one. No-op with a single controller (nothing to switch between)."""
    if not port:
        return
    ids = [c['id'] for c in state['controllers']]
    if len(ids) >= 2 and port in ids and port != state.get('selected'):
        state['selected'] = port


def press_select_loop():
    """Watch every connected GameSir pad's evdev button events; a button press on
    a controller that ISN'T selected switches to it ('press to select').

    Uses evdev (the standard gamepad interface) rather than the vendor channel:
    the Cyclone's 0x12 report only streams while we heartbeat it, so a
    non-selected controller is silent there — but its buttons always reach evdev.
    Works uniformly for Cyclone and G7."""
    from gs_common import parse_devices, VENDOR_VID
    fds = {}                    # fd -> (path, port)
    open_paths = set()

    def sync():
        for d in parse_devices():
            if d['vendor'] != VENDOR_VID:
                continue
            for ev in d['events']:
                if ev in open_paths:
                    continue
                try:
                    fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    continue
                open_paths.add(ev)
                fds[fd] = (ev, evdev_port(ev))

    def drop(fd):
        path, _ = fds.pop(fd, (None, None))
        open_paths.discard(path)
        try:
            os.close(fd)
        except OSError:
            pass

    last_scan = 0.0
    while True:
        if state.get('demo'):           # demo mode: no real pads to watch
            time.sleep(0.3)
            continue
        now = time.time()
        if now - last_scan > 1.5:       # pick up (re)enumerated pads
            last_scan = now
            sync()
        if not fds:
            time.sleep(0.5)
            continue
        try:
            r, _, _ = select.select(list(fds), [], [], 0.3)
        except OSError:
            for fd in list(fds):
                drop(fd)
            continue
        for fd in r:
            try:
                data = os.read(fd, _EV_SIZE * 32)
            except BlockingIOError:
                continue
            except OSError:
                drop(fd)
                continue
            port = fds.get(fd, (None, None))[1]
            for i in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                _, _, etype, code, value = struct.unpack(_EV_FMT, data[i:i + _EV_SIZE])
                if etype == _EV_KEY and value == 1:   # a button went down
                    _maybe_select(port)
                    break
