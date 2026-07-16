"""
GameSir Cyclone 2 - Qt/QML bridge
=================================
The single QObject that QML talks to. It owns NO protocol logic: it polls the
shared `state` dict (filled by the reader thread) on a QTimer and republishes it
as Qt properties/signals, and forwards user actions to the existing command
layer (`gamesir_control`). Everything reverse-engineered stays in its own module
and is reused verbatim.

Two cadences:
  * input  (~60 Hz) - sticks/triggers/buttons, for a fluid live controller view.
  * status (~4  Hz) - connection, battery, profile, firmware, mode warning.
"""

import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

from gs_state import state, EXTRA_BTNS
import gamesir_control as control
import gamesir_led as led
import gamesir_led8k as led8k
import gamesir_motion as motion
import gamesir_macro as macro
import gamesir_config as cfg
import controller_profile as profiles
import gamesir_kf_cache as kf_cache
import gamesir_kwin as kwin
import gamesir_factory as factory
import gamesir_backup as backup
import gamesir_flash as flash
from gamesir_led import LIGHTS

from PySide6.QtCore import QUrl


def _keyframe_lighting():
    """True only when the connected controller uses the Cyclone keyframe/palette
    RGB that the `gamesir_led` module speaks. Every led.* write goes through the
    two helpers below, so this is the single choke point that stops Cyclone LED
    commands from ever reaching a model with a different lighting layout (e.g. the
    8K's bank-0x20 mode/brightness/home-ring) and corrupting it."""
    return (profiles.is_recognized()
            and profiles.active().lighting_style == 'cyclone_keyframe')


def _led_async(fn, *args):
    """Every led.* write is fire-and-forget; run it off the Qt thread."""
    if not _keyframe_lighting():
        return
    threading.Thread(target=lambda: fn(*args), daemon=True).start()


def _led_retry(fn, *args):
    """Like _led_async, but send twice (spaced) for one-shot single-byte settings
    the controller is prone to dropping when a command arrives back-to-back with
    its heartbeat/queries (audio-reactive, pick-up-to-wake, sleep timeout)."""
    if not _keyframe_lighting():
        return
    def run():
        fn(*args); time.sleep(0.06); fn(*args)
    threading.Thread(target=run, daemon=True).start()


# Friendly key -> (ControllerProfile address-attribute, review-label) for the
# scalar config fields the Sticks/Triggers/Vibration pages edit. Labels are the
# same across models; the actual register ADDRESS is resolved per active profile
# in GamesirBridge._apply_profile (so a G7 uses G7 addresses, Cyclone uses its).
_SCALAR_FIELDS = {
    'st_dz_min':  ('ST_DZ_MIN',  'Left stick deadzone min'),
    'st_dz_max':  ('ST_DZ_MAX',  'Left stick deadzone max'),
    'st_adz_min': ('ST_ADZ_MIN', 'Left stick anti-deadzone min'),
    'st_adz_max': ('ST_ADZ_MAX', 'Left stick anti-deadzone max'),
    'rs_dz_min':  ('RS_DZ_MIN',  'Right stick deadzone min'),
    'rs_dz_max':  ('RS_DZ_MAX',  'Right stick deadzone max'),
    'rs_adz_min': ('RS_ADZ_MIN', 'Right stick anti-deadzone min'),
    'rs_adz_max': ('RS_ADZ_MAX', 'Right stick anti-deadzone max'),
    'lt_dz_min':  ('LT_DZ_MIN',  'LT deadzone min'),
    'lt_dz_max':  ('LT_DZ_MAX',  'LT deadzone max'),
    'lt_adz_min': ('LT_ADZ_MIN', 'LT anti-deadzone min'),
    'lt_adz_max': ('LT_ADZ_MAX', 'LT anti-deadzone max'),
    'rt_dz_min':  ('RT_DZ_MIN',  'RT deadzone min'),
    'rt_dz_max':  ('RT_DZ_MAX',  'RT deadzone max'),
    'rt_adz_min': ('RT_ADZ_MIN', 'RT anti-deadzone min'),
    'rt_adz_max': ('RT_ADZ_MAX', 'RT anti-deadzone max'),
    'vib_l':      ('VIB_L',      'Vibration L'),
    'vib_r':      ('VIB_R',      'Vibration R'),
}
# The deadzone / anti-deadzone scalar keys (everything except vibration). On a
# dz_wide model (8K) these encode as 16-bit big-endian percent×10 instead of a
# plain byte; vibration/poll stay single-byte on every model.
_WIDE_SCALAR_KEYS = {k for k in _SCALAR_FIELDS if k not in ('vib_l', 'vib_r')}
_CURVE_FIELDS = {'st': 'ST_CURVE', 'rs': 'RS_CURVE', 'lt': 'LT_CURVE', 'rt': 'RT_CURVE'}
_TRAJ_FIELDS = {'st': 'ST_TRAJ', 'rs': 'RS_TRAJ'}
_HAIR_FIELDS = {'lt': 'LT_HAIR', 'rt': 'RT_HAIR'}


def _hex(rgb):
    return '#%02X%02X%02X' % (rgb[0] & 0xFF, rgb[1] & 0xFF, rgb[2] & 0xFF)


def _rgb(hexstr):
    h = hexstr.lstrip('#')
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def _resample_points(pts, n):
    """Resample a list of (x,y) curve control points to exactly n points, linearly
    interpolating y at n evenly-spaced x positions across the input range. Lets the
    3-point custom-curve editor drive a 5-point (8K stick) block without corrupting
    its length."""
    pts = sorted(((int(x), int(y)) for x, y in pts), key=lambda p: p[0])
    if len(pts) < 2:
        pts = [(0, 0), (255, 255)]
    x0, xN = pts[0][0], max(pts[-1][0], pts[0][0] + 1)
    out = []
    for i in range(n):
        x = round(x0 + (xN - x0) * i / (n - 1))
        y = pts[-1][1]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if ax <= x <= bx:
                y = ay if bx == ax else ay + (by - ay) * (x - ax) / (bx - ax)
                break
        out.append((max(0, min(255, x)), max(0, min(255, round(y)))))
    return out


class GamesirBridge(QObject):
    # --- change signals (one per property group QML binds to) ---------------
    inputChanged = Signal()
    statusChanged = Signal()
    lightsChanged = Signal()
    lightingLoaded = Signal()       # fired when a slot's lighting is read back
    light8kLoaded = Signal()        # 8K simple lighting read back (bank 0x20)
    motionLoaded = Signal()         # 8K motion (Aim/Tilt) read back (profile bank)
    macroLoaded = Signal()          # per-paddle macros read back (profile bank)
    mouseModeChanged = Signal()
    configLoaded = Signal()         # fired when a profile's config is read back
    pendingChanged = Signal()       # number of queued (unsaved) config edits
    applyStatusChanged = Signal()   # read-back verification of the last Apply
    controllerChanged = Signal()    # detected controller model (Cyclone/G7) changed
    controllersChanged = Signal()   # the set of connected controllers changed
    demoModeChanged = Signal()      # demo mode toggled on/off
    backupBusyChanged = Signal()
    backupProgress = Signal(int, int)   # done, total
    backupStatus = Signal(bool, str)    # ok, message
    fwBusyChanged = Signal()
    fwProgress = Signal(str)            # phase text (Entering loader / Writing / …)
    fwStatus = Signal(bool, str)        # ok, message
    fwVersionsChanged = Signal()        # library changed (e.g. after a backup)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Cached snapshots so we only emit when something actually changes
        # (avoids waking every QML binding 60x/s for nothing).
        self._input_sig = None
        self._status_sig = None
        self._controllers_sig = None

        # Per-zone display colors for the controller render. Driven by the Lights
        # page; seeded from each zone's factory default so the render looks lit.
        self._light_colors = [_hex(default) for _, default in LIGHTS]
        self._brightness = 100      # 0..100 (device byte range is 0..0x64 == 100)
        self._speed = 10            # 1..20 UI (higher = faster)

        # Lighting read-back: pull the active slot's real state off the device so
        # the Lights page opens reflecting reality (mirrors the Dear PyGui app's
        # auto-load: load once per active-slot change, gathered across polls).
        self._loaded_led_slot = None
        self._led_loading = None        # slot awaiting replies, or None
        self._audio_reactive = False
        self._pickup_wake = False
        self._sleep_label = '10 min'
        self._loaded_frames = []        # list of frames, each = 4 hex strings

        # Per-profile config read-back + staged edits (Sticks/Triggers/Vibration).
        self._loaded_profile = None
        self._config_loading = None     # bank awaiting replies, or None
        self._config = {}               # friendly key -> loaded value
        self._pending = {}              # addr -> {'data','label','display'}
        self._apply_status = ''         # transient Apply read-back result (UI hint)
        self._backup_busy = False
        self._fw_busy = False

        # 8K simple lighting (bank 0x20). Loaded once per connection; writes apply
        # immediately (like the Cyclone LED), so we don't re-read/clobber after.
        self._l8 = {}
        self._l8_loaded = False
        self._l8_loading = False

        # 8K motion (gyro Aim/Tilt), per-profile bank. Loaded once per profile;
        # writes apply immediately, so we re-read only on a profile/controller change.
        self._m = {}
        self._m_profile = None          # profile the loaded motion state belongs to
        self._m_loading = False

        # per-paddle macros, per-profile bank. Loaded once per profile.
        self._macros = {}               # paddle name -> {enable, events}
        self._macro_profile = None
        self._macro_loading = False

        # Which controller's register map we address. Follows the connected
        # controller (Cyclone/G7); the address maps below are rebuilt on change.
        # `_driving` tracks the exact physical unit whose vendor session is OPEN
        # (state['driving']), so a switch between two identical-model controllers
        # still drops the prior unit's staged/loaded config -- and does so only
        # once the reader has actually rebound, not when the picker changes.
        self._controller = None
        self._driving = None
        self._apply_profile(profiles.active())

        self._input_timer = QTimer(self)
        self._input_timer.setInterval(16)        # ~60 Hz
        self._input_timer.timeout.connect(self._poll_input)
        self._input_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(250)      # 4 Hz
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start()

        self._light_timer = QTimer(self)
        self._light_timer.setInterval(120)       # gather record/config read chunks
        self._light_timer.timeout.connect(self._poll_lighting)
        self._light_timer.timeout.connect(self._poll_lighting_8k)
        self._light_timer.timeout.connect(self._poll_motion)
        self._light_timer.timeout.connect(self._poll_macro)
        self._light_timer.timeout.connect(self._poll_config)
        self._light_timer.start()

    def _apply_profile(self, prof):
        """Bind the register-address maps to `prof` (the active controller). Only
        fields the model actually has are included (None addresses are dropped),
        so a controller lacking a field simply can't edit it."""
        self._prof = prof
        g = lambda a: getattr(prof, a)
        self._scalars = {k: (g(a), lbl) for k, (a, lbl) in _SCALAR_FIELDS.items()
                         if g(a) is not None}
        self._curve_addr = {k: g(a) for k, a in _CURVE_FIELDS.items() if g(a) is not None}
        self._traj_addr = {k: g(a) for k, a in _TRAJ_FIELDS.items() if g(a) is not None}
        self._hair_addr = {k: g(a) for k, a in _HAIR_FIELDS.items() if g(a) is not None}
        self._addr_to_scalar = {addr: key for key, (addr, _l) in self._scalars.items()}
        self._addr_to_curve = {addr: side for side, addr in self._curve_addr.items()}
        self._addr_to_traj = {addr: side for side, addr in self._traj_addr.items()}
        self._addr_to_hair = {addr: side for side, addr in self._hair_addr.items()}
        self._addr_to_remap = {addr: name for name, addr in prof.REMAP_SLOTS}
        self._remap_addr = {name: addr for name, addr in prof.REMAP_SLOTS}

    # ------------------------------------------------------------------ polls
    def _poll_input(self):
        sig = (state['lx'], state['ly'], state['rx'], state['ry'],
               state['lt'], state['rt'], state['dpad'],
               state['a'], state['b'], state['x'], state['y'],
               state['lb'], state['rb'], state['ls'], state['rs'],
               state['view'], state['menu'],
               state['l4'], state['r4'], state['m'], state['home'], state['share'])
        if sig != self._input_sig:
            self._input_sig = sig
            self.inputChanged.emit()

    def _poll_status(self):
        # Model changed (Cyclone <-> G7 <-> none): rebuild the register-address
        # map and refresh the model-level properties bound to controllerChanged
        # (fwSupported, poll rates, remap sources).
        if state['controller'] != self._controller:
            self._controller = state['controller']
            self._apply_profile(profiles.active())
            self.controllerChanged.emit()

        # Driving session changed: a different physical unit's vendor channel is
        # now open (or none). Drop every per-unit cache so nothing from one unit
        # is shown or written against another; the pollers re-read for the newly
        # bound unit. We key on `driving` (the OPEN session, published by the
        # reader) rather than `selected` (the DESIRED unit) so the reset lands
        # when the reader actually rebinds -- keying on `selected` reset ~1s too
        # early, racing the still-open previous unit's session.
        if state['driving'] != self._driving:
            self._driving = state['driving']
            self._reset_device_caches()

        sig = (state['connected'], state['mode_ok'], state['battery'],
               state['charging'], state['profile'], state['led_slot'],
               state['firmware'], state['controller'], state['wired'])
        if sig != self._status_sig:
            self._status_sig = sig
            self.statusChanged.emit()

        csig = (tuple((c['id'], c['name']) for c in state['controllers']),
                state['selected'])
        if csig != self._controllers_sig:
            self._controllers_sig = csig
            self.controllersChanged.emit()

    def _reset_device_caches(self):
        """Forget the previously-driven unit's config + lighting so nothing from
        one controller is shown or written against another after a switch. The
        pollers re-read for the newly-bound unit; the load signals fire so the
        editor/lighting pages clear to a neutral state immediately instead of
        lingering on the old unit's values until the re-read lands (which, for a
        unit whose registers we can't read -- G7/unrecognised/absent -- is never).
        Lighting resets to the same defaults __init__ seeds, so the render never
        shows one unit's colors/effect on another."""
        # config editor
        self._loaded_profile = None
        self._config_loading = None
        self._config = {}
        if self._pending:
            self._pending = {}
            self.pendingChanged.emit()
        self.configLoaded.emit()
        # 8K simple lighting: force a reload for the newly-bound unit
        self._l8 = {}
        self._l8_loaded = False
        self._l8_loading = False
        self.light8kLoaded.emit()
        # 8K motion: force a reload for the newly-bound unit / profile
        self._m = {}
        self._m_profile = None
        self._m_loading = False
        self.motionLoaded.emit()
        # macros: force a reload for the newly-bound unit / profile
        self._macros = {}
        self._macro_profile = None
        self._macro_loading = False
        self.macroLoaded.emit()
        # lighting
        self._loaded_led_slot = None
        self._led_loading = None
        self._loaded_frames = []
        self._light_colors = [_hex(default) for _, default in LIGHTS]
        self._brightness = 100
        self._speed = 10
        self._audio_reactive = False
        self._pickup_wake = False
        self._sleep_label = '10 min'
        self.lightsChanged.emit()
        self.lightingLoaded.emit()

    def _poll_lighting(self):
        """Read the active lighting slot's real state once, whenever the active
        slot first appears or changes. Reads queue on the reader thread and land
        over several polls; we publish once every chunk + power byte is in."""
        if not _keyframe_lighting():
            return          # unrecognised/absent, or a model whose lighting isn't
                            # the Cyclone keyframe layout (led.* would misread it)
        if state['driving'] != state['selected']:
            return          # selected unit's vendor session not bound yet (or an
                            # evdev model with no vendor channel): don't read
        slot = state['led_slot']
        if (slot is not None and 0 <= slot <= 3
                and slot != self._loaded_led_slot and self._led_loading is None):
            self._loaded_led_slot = slot
            control.request_regs(led.record_read_fields(slot) + [
                (led.LED_BANK, led.AUDIO_REACTIVE, 1),
                (led.LED_BANK, led.PICKUP_WAKE, 1),
                (led.LED_BANK, led.SLEEP_TIMEOUT, 1),
            ])
            self._led_loading = slot

        slot = self._led_loading
        if slot is None:
            return
        recvals = {addr: control.reg_result(bank, addr)
                   for bank, addr, _ln in led.record_read_fields(slot)}
        audio = control.reg_result(led.LED_BANK, led.AUDIO_REACTIVE)
        pickup = control.reg_result(led.LED_BANK, led.PICKUP_WAKE)
        sleep = control.reg_result(led.LED_BANK, led.SLEEP_TIMEOUT)
        if (any(v is None for v in recvals.values())
                or audio is None or pickup is None or sleep is None):
            return                              # still waiting on replies

        self._led_loading = None
        record = led.stitch_record(slot, recvals)
        if record is None:
            return
        decoded = led.decode_record(record)

        self._audio_reactive = bool(audio[0])
        self._pickup_wake = bool(pickup[0])
        self._sleep_label = led.sleep_label(sleep[0])
        self._speed = decoded['speed']
        self._brightness = decoded['brightness']
        count = max(1, decoded['count'])
        self._loaded_frames = [[_hex(c) for c in fr] for fr in decoded['frames'][:count]]
        if self._loaded_frames:
            self._light_colors = list(self._loaded_frames[0])
        self.lightsChanged.emit()
        self.lightingLoaded.emit()

    def _is_8k_lighting(self):
        return (profiles.is_recognized()
                and profiles.active().lighting_style == 'simple_8k')

    def _poll_lighting_8k(self):
        """Load the 8K's bank-0x20 lighting/device settings once per connection.
        Writes apply immediately, so we don't re-read afterwards (avoids clobbering
        an edit with an in-flight read)."""
        if not self._is_8k_lighting() or state['driving'] != state['selected']:
            return
        if not self._l8_loaded and not self._l8_loading:
            control.request_regs(led8k.read_fields())
            self._l8_loading = True
        if not self._l8_loading:
            return
        vals = {a: control.reg_result(b, a) for b, a, _ln in led8k.read_fields()}
        if any(v is None for v in vals.values()):
            return                                  # still waiting on replies
        self._l8_loading = False
        self._l8_loaded = True
        self._l8 = {
            'mode':        led8k.mode_index(vals[led8k.MODE][0]),
            'bright':      vals[led8k.BRIGHT][0],
            'quads':       [list(vals[a]) for a in led8k.HOME_Q],  # [hue, byte1] per quadrant
            'auto':        bool(vals[led8k.AUTO_ONOFF][0]),
            'sleep':       led8k.sleep_index(vals[led8k.SLEEP_TIMER][0]),
            'dock_mode':   min(vals[led8k.DOCK_MODE][0], 1),
            'dock_bright': vals[led8k.DOCK_BRIGHT][0],
        }
        self.light8kLoaded.emit()

    def _write8k(self, addr, data):
        """Immediate bank-0x20 write for an 8K lighting/device setting (threaded,
        pinned to the current write-style + session so a switch can't misroute)."""
        if not self._is_8k_lighting():
            return
        style = self._prof.write_style
        gen = control.generation()
        threading.Thread(
            target=lambda: control.write_reg(led8k.BANK, addr, list(data),
                                             write_style=style, gen=gen),
            daemon=True).start()

    def _has_motion(self):
        return profiles.is_recognized() and self._prof.has_motion

    def _poll_motion(self):
        """Load the active profile's motion (Aim/Tilt) block once per profile.
        Lives in the profile bank alongside the analog config, but writes apply
        immediately (like lighting), so we re-read only when the profile changes."""
        if not self._has_motion() or state['driving'] != state['selected']:
            return
        prof = state['profile']
        bank = self._prof.profile_bank(prof)
        mp = self._mp()
        if bank is None or not mp:
            return
        if prof != self._m_profile and not self._m_loading:
            control.request_regs([(bank, a, ln) for a, ln in motion.read_addrs(mp)])
            self._m_loading = True
            self._m_profile = prof
        if not self._m_loading:
            return
        vals = {a: control.reg_result(bank, a) for a, _ln in motion.read_addrs(mp)}
        if any(v is None for v in vals.values()):
            return                                  # still waiting on replies
        self._m_loading = False
        self._m = {name: motion.decode_section(mp, vals, off)
                   for name, off in motion.sections(mp)}
        self.motionLoaded.emit()

    def _write_motion(self, addr, data):
        """Immediate profile-bank write for a motion field (threaded, pinned to
        the current write-style + session so a controller switch can't misroute)."""
        if not self._has_motion():
            return
        bank = self._prof.profile_bank(state['profile'])
        if bank is None:
            return
        style = self._prof.write_style
        gen = control.generation()
        threading.Thread(
            target=lambda: control.write_reg(bank, addr, list(data),
                                             write_style=style, gen=gen),
            daemon=True).start()

    def _has_macros(self):
        return profiles.is_recognized() and self._prof.has_macros

    def _poll_macro(self):
        """Load every paddle's macro for the active profile, once per profile."""
        if not self._has_macros() or state['driving'] != state['selected']:
            return
        prof = state['profile']
        bank = self._prof.profile_bank(prof)
        if bank is None:
            return
        mx = self._prof.macro_max
        reads = [(bank, a, ln) for _n, base in self._prof.MACRO_SLOTS
                 for a, ln in macro.read_addrs(base, mx)]
        if prof != self._macro_profile and not self._macro_loading:
            control.request_regs(reads)
            self._macro_loading = True
            self._macro_profile = prof
        if not self._macro_loading:
            return
        vals = {a: control.reg_result(b, a) for b, a, _ln in reads}
        if any(v is None for v in vals.values()):
            return
        self._macro_loading = False
        self._macros = {name: macro.decode(vals, base, mx)
                        for name, base in self._prof.MACRO_SLOTS}
        self.macroLoaded.emit()

    def _write_macro(self, base, data):
        """Immediate profile-bank macro write (auto-chunked by write_reg)."""
        if not self._has_macros():
            return
        bank = self._prof.profile_bank(state['profile'])
        if bank is None:
            return
        style = self._prof.write_style
        gen = control.generation()
        threading.Thread(
            target=lambda: control.write_reg(bank, base, list(data),
                                             write_style=style, gen=gen),
            daemon=True).start()

    def _poll_config(self):
        """Read the selected profile's config once whenever the profile changes.
        Switching profiles discards any unsaved edits (mirrors the DPG app)."""
        if not profiles.is_recognized():
            return          # unrecognised/absent controller: don't read its regs
        if state['driving'] != state['selected']:
            return          # reader hasn't bound the selected unit's vendor
                            # session yet (or an evdev model, e.g. G7, that has no
                            # vendor read channel): don't read/attribute its regs
        prof = state['profile']
        bank = self._prof.profile_bank(prof)
        if (bank is not None and prof != self._loaded_profile
                and self._config_loading is None):
            self._loaded_profile = prof
            if self._pending:
                self._pending = {}
                self.pendingChanged.emit()
            reqs = [(bank, addr, ln) for addr, ln in self._prof.read_fields()]
            reqs += [(bank, addr, 2) for _n, addr in self._prof.REMAP_SLOTS]
            control.request_regs(reqs)
            self._config_loading = bank

        bank = self._config_loading
        if bank is None:
            return
        vals = {addr: control.reg_result(bank, addr)
                for addr, _ln in self._prof.read_fields()}
        vals.update({addr: control.reg_result(bank, addr)
                     for _n, addr in self._prof.REMAP_SLOTS})
        if any(v is None for v in vals.values()):
            return
        self._config_loading = None
        cand = self._build_config(vals)
        # Guard against a transient/garbage read overwriting a good config (the
        # "triggers 0–0 after a page switch" bug): a deadzone MAX of 0 fully
        # deadzones the axis, which no real profile does — so it signals the
        # firmware answering mid profile-reload (e.g. right after the reload nudge).
        # Drop it and force a fresh re-read next tick, keeping the last good config.
        if self._analog_collapsed(cand):
            self._loaded_profile = None
            return
        self._config = cand
        self.configLoaded.emit()

    @staticmethod
    def _analog_collapsed(c):
        """True if a freshly-read config has an implausible deadzone-max of 0 for
        any axis it has — the signature of a transient read to reject."""
        return any(c.get(k) == 0 for k in
                   ('st_dz_max', 'rs_dz_max', 'lt_dz_max', 'rt_dz_max'))

    def _build_config(self, vals):
        # Only emit fields the model actually has. A field the profile lacks has
        # a None address (so it's absent from `vals` / read_fields), and a model
        # with NO config fields at all (e.g. G7 Pro) would otherwise index
        # vals[None] and raise. Omitted keys read back as undefined in QML, which
        # the editor pages already guard for, exactly like a missing scalar.
        p = self._prof
        g = lambda a: vals[a][0]
        def curve(key, addr):
            blk = vals[addr]
            npts = p.curve_npts(key)
            if p.curve_padded(key):          # [type,int,0,0, pts] (3-point)
                pts = cfg.curve_points(blk)
            else:                            # [type,int, pts] (5-point, no padding)
                pts = ([(blk[2 + 2 * i], blk[3 + 2 * i]) for i in range(npts)]
                       if len(blk) >= 2 + 2 * npts else cfg.curve_points(blk))
            return {'type': cfg.curve_index(blk[0]),
                    'intensity': blk[1] if len(blk) > 1 else 100,
                    'points': [list(pt) for pt in pts]}
        out = {}
        if p.ST_TRAJ is not None:  out['st_traj'] = cfg.enum_index(g(p.ST_TRAJ), cfg.TRAJ)
        if p.RS_TRAJ is not None:  out['rs_traj'] = cfg.enum_index(g(p.RS_TRAJ), cfg.TRAJ)
        def hair(side, addr):
            b = vals[addr]           # [mode, min, max]
            out[side + '_hair'] = cfg.enum_index(b[0], cfg.HAIR_MODES)
            out[side + '_hair_min'] = b[1] if len(b) > 1 else 10
            out[side + '_hair_max'] = b[2] if len(b) > 2 else 90
        if p.LT_HAIR is not None:  hair('lt', p.LT_HAIR)
        if p.RT_HAIR is not None:  hair('rt', p.RT_HAIR)
        if p.ST_CURVE is not None: out['st_curve'] = curve('st', p.ST_CURVE)
        if p.RS_CURVE is not None: out['rs_curve'] = curve('rs', p.RS_CURVE)
        if p.LT_CURVE is not None: out['lt_curve'] = curve('lt', p.LT_CURVE)
        if p.RT_CURVE is not None: out['rt_curve'] = curve('rt', p.RT_CURVE)
        if p.POLL_RATE is not None: out['poll'] = min(g(p.POLL_RATE), len(p.POLL_RATES) - 1)
        for key, (addr, _lbl) in self._scalars.items():
            b = vals[addr]
            if p.dz_wide and key in _WIDE_SCALAR_KEYS and len(b) >= 2:
                out[key] = round(((b[0] << 8) | b[1]) / 10.0, 1)   # 16-bit ×10 -> % (0.1)
            else:
                out[key] = b[0]
        remap = {}
        for name, addr in p.REMAP_SLOTS:
            rec = vals[addr]
            # store the raw target CODE (or -1 = unmapped) so keyboard/mouse
            # rebinds share one path; the UI resolves the label via targetLabel().
            remap[name] = (rec[1] if len(rec) > 1 else 0) if rec[0] else -1
        out['remap'] = remap
        return out

    # --------------------------------------------------------- input readouts
    # Sticks reported 0..255 with 128 at rest; expose as -1.0..+1.0 for QML.
    def _axis(self, key):
        return (state[key] - 128) / 127.0

    @Property(float, notify=inputChanged)
    def leftStickX(self):
        return self._axis('lx')

    @Property(float, notify=inputChanged)
    def leftStickY(self):
        return self._axis('ly')

    @Property(float, notify=inputChanged)
    def rightStickX(self):
        return self._axis('rx')

    @Property(float, notify=inputChanged)
    def rightStickY(self):
        return self._axis('ry')

    @Property(float, notify=inputChanged)
    def leftTrigger(self):
        return state['lt'] / 255.0

    @Property(float, notify=inputChanged)
    def rightTrigger(self):
        return state['rt'] / 255.0

    @Property(str, notify=inputChanged)
    def dpad(self):
        return state['dpad']

    @Property('QVariantMap', notify=inputChanged)
    def buttons(self):
        """Map of buttonName -> bool, for QML to bind highlights against."""
        keys = ('a', 'b', 'x', 'y', 'lb', 'rb', 'ls', 'rs',
                'view', 'menu') + EXTRA_BTNS
        return {k: bool(state[k]) for k in keys}

    # --------------------------------------------------------- status readouts
    @Property(bool, notify=statusChanged)
    def connected(self):
        return bool(state['connected'])

    @Property(bool, notify=statusChanged)
    def modeOk(self):
        # Demo mode has no real device, so it's always "in mode" — never show the
        # wrong-mode warning for a synthetic controller.
        return bool(state['demo']) or bool(state['mode_ok'])

    @Property(int, notify=statusChanged)
    def battery(self):
        return int(state['battery'] or 0)

    @Property(bool, notify=statusChanged)
    def charging(self):
        return bool(state['charging'])

    @Property(int, notify=statusChanged)
    def profile(self):
        return int(state['profile']) if state['profile'] else 0

    @Property(int, notify=statusChanged)
    def ledSlot(self):
        return int(state['led_slot']) if state['led_slot'] is not None else -1

    @Property(str, notify=statusChanged)
    def firmware(self):
        return state['firmware'] or ''

    @Property(str, notify=statusChanged)
    def connectionKind(self):
        """'Wired' / 'Wireless' hint for the current controller ('' if unknown/demo).
        Derived from the USB identity we're talking to (8K wired PID, Cyclone fw
        namespace) — a display hint, NOT a flash gate. The authoritative dongle guard
        is the in-loader flash-header identity (GS_C2_Dongle) used by gamesir_flash."""
        if state.get('demo'):
            return ''
        w = state.get('wired')
        return '' if w is None else ('Wired' if w else 'Wireless')

    @Property(bool, notify=statusChanged)
    def onDongle(self):
        """True when we're connected through the wireless dongle (for UI warnings —
        e.g. the firmware panel: flashing over the dongle writes to the dongle)."""
        return state.get('wired') is False

    @Property(str, notify=statusChanged)
    def controllerName(self):
        """Detected controller model ('Cyclone 2' / 'G7'), or '' if unknown."""
        return state['controller'] or ''

    @Property(str, notify=controllerChanged)
    def lightingStyle(self):
        """'cyclone_keyframe' / 'simple_8k' / 'none' for the active controller, so
        the UI shows the right lighting page (or hides it) instead of driving the
        Cyclone keyframe controls against a model that doesn't have them."""
        return profiles.active().lighting_style if profiles.is_recognized() else 'none'

    @Property(bool, notify=controllerChanged)
    def hasMotion(self):
        return profiles.is_recognized() and profiles.active().has_motion

    @Property(bool, notify=controllerChanged)
    def hasMacros(self):
        return profiles.is_recognized() and profiles.active().has_macros

    @Property('QVariantList', notify=controllersChanged)
    def controllers(self):
        """All connected controllers for the picker: [{id, name, port, label}].
        Identical models (serials are empty) get a compact '#n' suffix to keep the
        top bar tight; the exact USB port stays in `port` for a tooltip / detail."""
        clist = state['controllers']
        names = [c['name'] for c in clist]
        out = []
        for i, c in enumerate(clist):
            dup = names.count(c['name']) > 1
            n = sum(1 for j in range(i + 1) if clist[j]['name'] == c['name'])
            label = f"{c['name']} #{n}" if dup else c['name']
            out.append({'id': c['id'], 'name': c['name'],
                        'port': c['port'], 'label': label})
        return out

    @Property(str, notify=controllersChanged)
    def selectedController(self):
        """id (USB port) of the controller currently being driven."""
        return state['selected'] or ''

    @Slot(str)
    def selectController(self, cid):
        """Switch which connected controller the app drives. The reader picks
        this up on its next scan and reconnects to it. In demo mode there's no
        reader to rebind, so switch the synthetic controller here."""
        if state['demo']:
            if cid and cid != state['selected'] and cid.startswith('demo:'):
                prof = next((p for p in self._DEMO_MODELS
                             if self._demo_id(p) == cid), None)
                if prof is not None:
                    self._bind_demo(prof)
            return
        if cid and cid != state['selected']:
            state['selected'] = cid

    # ------------------------------------------------------------------ demo mode
    # One synthetic controller per supported model, so users can browse the whole
    # UI (per-controller pages, capability gating, controller render) with no
    # hardware plugged in. Ordered fully-supported first.
    # Only the models this app FULLY supports (Cyclone 2 + G7 Pro 8K). The plain
    # G7 / G7 Pro (evdev-only, no working vendor write channel) are excluded — demo
    # would imply a config surface the app can't actually drive for them.
    _DEMO_MODELS = (profiles.CYCLONE, profiles.G7_8K)

    @staticmethod
    def _demo_id(prof):
        return 'demo:' + prof.short

    @staticmethod
    def _default_scalar_bytes(prof, attr, val):
        """Default value as device bytes: 16-bit big-endian ×10 for a deadzone /
        anti-deadzone on a dz_wide model (8K), else a plain byte."""
        if prof.dz_wide and any(attr.endswith(s) for s in
                                ('DZ_MIN', 'DZ_MAX', 'ADZ_MIN', 'ADZ_MAX')):
            w = max(0, min(1000, int(val) * 10))
            return [(w >> 8) & 0xFF, w & 0xFF]
        return [int(val) & 0xFF]

    @staticmethod
    def _default_curve_bytes(prof, key):
        """A default (Linear) curve block in the side's format: 3-point padded
        (Cyclone / 8K triggers) or 5-point (8K sticks)."""
        if prof.curve_npts(key) == 3:
            return cfg.curve_block('Linear')
        return motion.curve_block(prof.curve_npts(key), 0, 100, None)

    def _demo_reg_map(self, prof):
        """(bank, addr) -> default bytes for a profile, so demo config pages show
        sane values (deadzones, linear curves, vibration) instead of zeros. Seeded
        for every profile bank; remaps/motion/macros/lighting fall back to the
        generic demo default (unmapped / off / empty)."""
        regs = {}
        for bank in (prof.profile_banks or (1,)):
            for attr, val in self._DEFAULT_SCALARS.items():
                a = getattr(prof, attr, None)
                if a is not None:
                    regs[(bank, a)] = self._default_scalar_bytes(prof, attr, val)
            for key, attr in (('st', 'ST_CURVE'), ('rs', 'RS_CURVE'),
                              ('lt', 'LT_CURVE'), ('rt', 'RT_CURVE')):
                a = getattr(prof, attr, None)
                if a is not None:
                    regs[(bank, a)] = self._default_curve_bytes(prof, key)
            # hair-trigger is read as a 3-byte [mode, min, max] block, so give the
            # demo a real block (Off, default 10/90 thresholds) instead of one byte.
            for attr in ('LT_HAIR', 'RT_HAIR'):
                a = getattr(prof, attr, None)
                if a is not None:
                    regs[(bank, a)] = [0, 10, 90]
        return regs

    def _bind_demo(self, prof):
        """Point demo state at `prof`: activate its profile, seed its default
        registers, and update `state`. The bridge's own _poll_status then rebinds
        the address map + resets caches, so the pollers reload from the demo regs
        exactly as they would from a real device."""
        profiles.set_active(prof)
        control.set_demo_regs(self._demo_reg_map(prof))
        state['selected'] = self._demo_id(prof)
        state['driving'] = self._demo_id(prof)
        state['controller'] = prof.short
        state['profile'] = 1
        state['firmware'] = 'demo'

    @Property(bool, notify=demoModeChanged)
    def demoMode(self):
        return bool(state['demo'])

    @Slot(bool)
    def setDemoMode(self, on):
        """Enter/leave demo mode. Session-only (not persisted): a restart always
        comes up on real hardware so a plugged-in controller is never ignored."""
        on = bool(on)
        if on == bool(state['demo']):
            return
        if on:
            state['demo'] = True            # idle the reader FIRST so it can't
            state['connected'] = True        # blank the state we're about to set
            state['mode_ok'] = True
            state['battery'] = 87
            state['charging'] = False
            state['led_slot'] = 0
            state['controllers'] = [
                {'id': self._demo_id(p), 'name': p.name, 'port': 'demo',
                 'pid': p.usb_products[0]} for p in self._DEMO_MODELS]
            self._bind_demo(self._DEMO_MODELS[0])
        else:
            state['demo'] = False
            control.set_demo_regs({})
            # Hand control back to the reader: clear the synthetic controller and
            # let it re-enumerate real hardware (it will re-set the active profile).
            state['controllers'] = []
            state['selected'] = None
            state['driving'] = None
            state['controller'] = None
            state['connected'] = None
            state['mode_ok'] = False
            state['profile'] = None
            state['firmware'] = None
            state['led_slot'] = None
            profiles.set_active(None)
        self.demoModeChanged.emit()

    # ------------------------------------------------------------- lighting view
    @Property('QVariantList', constant=True)
    def lightNames(self):
        """Zone names in LIGHTS order, for labels/callouts."""
        return [name for name, _ in LIGHTS]

    @Property('QVariantList', notify=lightsChanged)
    def lightColors(self):
        """Per-zone display colors the controller render binds to."""
        return list(self._light_colors)

    @Slot(int, str)
    def setLight(self, i, color):
        """Set one zone's display color (the Lights page calls this as the user
        edits). Does NOT write to the controller; pushing is a separate action."""
        if 0 <= i < len(self._light_colors):
            self._light_colors[i] = color
            self.lightsChanged.emit()

    @Property('QVariantList', constant=True)
    def presetNames(self):
        return list(led.PATTERN_NAMES)

    @Property('QVariantList', constant=True)
    def sleepOptions(self):
        return [lbl for lbl, _ in led.SLEEP_OPTIONS]

    @Property(int, notify=lightsChanged)
    def brightness(self):
        return self._brightness

    @Property(int, notify=lightsChanged)
    def speed(self):
        return self._speed

    # Read-back state (populated by _poll_lighting; QML refreshes on lightingLoaded)
    @Property(bool, notify=lightingLoaded)
    def audioReactive(self):
        return self._audio_reactive

    @Property(bool, notify=lightingLoaded)
    def pickupWake(self):
        return self._pickup_wake

    @Property(str, notify=lightingLoaded)
    def sleepLabel(self):
        return self._sleep_label

    @Property('QVariantList', notify=lightingLoaded)
    def loadedFrames(self):
        return [list(f) for f in self._loaded_frames]

    # --- lighting writes (all fire-and-forget to the active slot) -----------
    def _zone_rgb(self):
        return [_rgb(c) for c in self._light_colors]

    @Slot()
    def applyColors(self):
        """Push the current per-zone colors as a solid palette at brightness."""
        _led_async(led.set_lights, self._zone_rgb(), self._brightness)

    @Slot()
    def lightsOff(self):
        _led_async(led.set_lights, self._zone_rgb(), 0)

    @Slot(str)
    def applyPreset(self, name):
        """Apply a named effect (Flow/Rainbow/...) and reflect its own speed."""
        rec = led.PATTERNS.get(name)
        if rec is not None:
            self._speed = led.speed_ui(rec[led.REC_SPEED_OFF])
            self.lightsChanged.emit()
        _led_async(led.set_pattern, name, self._brightness)

    @Slot(int)
    def setBrightness(self, v):
        self._brightness = max(0, min(100, int(v)))
        self.lightsChanged.emit()
        _led_async(led.set_brightness, self._brightness)

    @Slot(int)
    def setSpeed(self, v):
        self._speed = max(led.SPEED_MIN, min(led.SPEED_MAX, int(v)))
        self.lightsChanged.emit()
        _led_async(led.set_speed, self._speed)

    @Slot(bool)
    def setAudioReactive(self, on):
        _led_retry(led.set_audio_reactive, bool(on))

    @Slot(bool)
    def setPickupWake(self, on):
        _led_retry(led.set_pickup_wake, bool(on))

    @Slot(str)
    def setSleepTimeout(self, label):
        _led_retry(led.set_sleep_timeout, led.sleep_raw(label))

    # ---------------------------------------------------- 8K simple lighting view
    @Property('QVariantList', constant=True)
    def light8kModes(self):
        return [n for n, _ in led8k.MODES]

    @Property('QVariantList', constant=True)
    def light8kSleepOptions(self):
        return [n for n, _ in led8k.SLEEP_OPTIONS]

    @Property('QVariantList', constant=True)
    def light8kDockModes(self):
        return [n for n, _ in led8k.DOCK_MODES]

    @Property(int, notify=light8kLoaded)
    def light8kMode(self):
        return self._l8.get('mode', 0)

    @Property(int, notify=light8kLoaded)
    def light8kBrightness(self):
        return self._l8.get('bright', 100)

    @Property('QVariantList', notify=light8kLoaded)
    def light8kQuads(self):
        """Per-quadrant [hue byte 0..255, byte1 0..100]. byte1 is treated as
        saturation (0 = white). QML renders each as Qt.hsva(hue/360, byte1/100, 1)."""
        return [list(q) for q in self._l8.get('quads', [[60, 100]] * 4)]

    @Property(bool, notify=light8kLoaded)
    def light8kAuto(self):
        return self._l8.get('auto', False)

    @Property(int, notify=light8kLoaded)
    def light8kSleep(self):
        return self._l8.get('sleep', 0)

    @Property(int, notify=light8kLoaded)
    def light8kDockMode(self):
        return self._l8.get('dock_mode', 0)

    @Property(int, notify=light8kLoaded)
    def light8kDockBright(self):
        return self._l8.get('dock_bright', 100)

    @Slot(int)
    def setLight8kMode(self, idx):
        if 0 <= idx < len(led8k.MODES):
            self._l8['mode'] = idx
            self._write8k(led8k.MODE, [led8k.MODES[idx][1]])

    @Slot(int)
    def setLight8kBrightness(self, v):
        v = max(0, min(100, int(v)))
        self._l8['bright'] = v
        self._write8k(led8k.BRIGHT, [v])

    @Slot(int, int, int)
    def setLight8kQuadColor(self, i, hue, byte1):
        """Set quadrant i to [hue 0..255, byte1 0..100] (byte1 = saturation)."""
        self.setLight8kQuads([i], hue, byte1)

    @Slot('QVariantList', int, int)
    def setLight8kQuads(self, indices, hue, byte1):
        """Set several quadrants to the same [hue, byte1] in ONE paced write — these
        controllers drop back-to-back vendor commands, so writing each quadrant on
        its own thread (or with no gap) would silently lose some. Used by the 8K
        home-ring multi-select."""
        if not self._is_8k_lighting():
            return
        hue = max(0, min(255, int(hue)))
        byte1 = max(0, min(100, int(byte1)))
        idxs = [int(i) for i in indices if 0 <= int(i) < 4]
        if not idxs:
            return
        q = [list(x) for x in self._l8.get('quads', [[60, 100]] * 4)]
        for i in idxs:
            q[i] = [hue, byte1]
        self._l8['quads'] = q
        style = self._prof.write_style
        gen = control.generation()
        def run():
            for i in idxs:
                control.write_reg(led8k.BANK, led8k.HOME_Q[i], [hue, byte1],
                                  write_style=style, gen=gen)
                time.sleep(0.03)      # pace: dropped back-to-back writes otherwise
        threading.Thread(target=run, daemon=True).start()

    @Slot(bool)
    def setLight8kAuto(self, on):
        self._l8['auto'] = bool(on)
        self._write8k(led8k.AUTO_ONOFF, [1 if on else 0])

    @Slot(int)
    def setLight8kSleep(self, idx):
        if 0 <= idx < len(led8k.SLEEP_OPTIONS):
            self._l8['sleep'] = idx
            self._write8k(led8k.SLEEP_TIMER, [led8k.SLEEP_OPTIONS[idx][1]])

    @Slot(int)
    def setLight8kDockMode(self, idx):
        if 0 <= idx < len(led8k.DOCK_MODES):
            self._l8['dock_mode'] = idx
            self._write8k(led8k.DOCK_MODE, [led8k.DOCK_MODES[idx][1]])

    @Slot(int)
    def setLight8kDockBright(self, v):
        v = max(0, min(100, int(v)))
        self._l8['dock_bright'] = v
        self._write8k(led8k.DOCK_BRIGHT, [v])

    # -------------------------------------------------------- 8K motion (Aim/Tilt)
    # Field routing tables: name -> (Aim-block addr, option list) for enums, or a
    # bare addr for scalar/bool fields. The Tilt equivalents add motion.TILT_OFFSET.
    _MOTION_ENUM_TABLE = {'act_method': motion.ACT_METHODS,
                          'xaxis':      motion.XAXIS_MODES,
                          'output':     motion.OUTPUTS}

    def _mp(self):
        return self._prof.motion or {}

    @Property('QVariantList', constant=True)
    def motionActMethods(self):
        return [n for n, _ in motion.ACT_METHODS]

    @Property('QVariantList', constant=True)
    def motionOutputs(self):
        return [n for n, _ in motion.OUTPUTS]

    @Property('QVariantList', constant=True)
    def motionXAxisModes(self):
        return [n for n, _ in motion.XAXIS_MODES]

    @Property('QVariantList', constant=True)
    def motionCurveTypes(self):
        return [n for n, _ in motion.CURVE_TYPES]

    @Property('QVariantList', constant=True)
    def motionButtons(self):
        """Buttons pickable for the activation combo, as {name, code}."""
        return [{'name': n, 'code': c} for n, c in motion.ACT_BUTTONS]

    # --- capability descriptors so the UI adapts to each controller's block ---
    @Property(int, notify=controllerChanged)
    def motionButtonMax(self):
        return len(self._mp().get('act_buttons', ()))     # 8K 3 / Cyclone 1

    @Property('QVariantList', notify=controllerChanged)
    def motionInvertLabels(self):
        return [lbl for lbl, _a in self._mp().get('inverts', ())]

    @Property(bool, notify=controllerChanged)
    def motionHasSens(self):
        return self._mp().get('sens') is not None

    @Property(bool, notify=controllerChanged)
    def motionHasTilt(self):
        return self._mp().get('tilt_offset') is not None

    @Property(bool, notify=controllerChanged)
    def motionHasDirMacros(self):
        return bool(self._mp().get('dir_macros'))

    @Property(bool, notify=controllerChanged)
    def motionXAxisGatesInverts(self):
        return bool(self._mp().get('xaxis_gates_inverts'))

    @Property('QVariantMap', notify=motionLoaded)
    def motionAim(self):
        return self._m.get('Aim', {})

    @Property('QVariantMap', notify=motionLoaded)
    def motionTilt(self):
        return self._m.get('Tilt', {})

    def _motion_off(self, section):
        for name, off in motion.sections(self._mp()):
            if name == section:
                return off
        return None

    @Slot(str, str, int)
    def setMotionEnum(self, section, field, idx):
        """Set an enum field (act_method/xaxis/output) by option index."""
        off = self._motion_off(section); mp = self._mp()
        table = self._MOTION_ENUM_TABLE.get(field)
        if off is None or table is None or field not in mp or not (0 <= idx < len(table)):
            return
        self._m.get(section, {})[field] = idx
        self._write_motion(mp[field] + off, [table[idx][1]])

    @Slot(str, str, int)
    def setMotionValue(self, section, field, value):
        """Set a 0..100 scalar field (xy_scale/sens)."""
        off = self._motion_off(section); mp = self._mp()
        addr = mp.get(field)
        if off is None or addr is None:
            return
        value = max(0, min(100, int(value)))
        self._m.get(section, {})[field] = value
        self._write_motion(addr + off, [value])

    @Slot(str, str, int)
    def setMotionDeadzone(self, section, field, pct):
        """Set a deadzone knob (field = dz_min / dz_max / adz_min / adz_max) from a
        0..100% slider. Max is 16-bit /1000 on the 8K, plain byte /100 on the Cyclone."""
        off = self._motion_off(section); mp = self._mp()
        addr = mp.get(field)
        if off is None or addr is None:
            return
        pct = max(0, min(100, int(pct)))
        sec = self._m.get(section)
        if sec is not None:
            sec[field] = pct
        if field.endswith('_max'):
            wide = mp.get('dz_wide' if field == 'dz_max' else 'adz_wide', False)
            data = motion.dz_max_bytes(pct, wide)
        else:
            data = motion.dz_min_bytes(pct)
        self._write_motion(addr + off, data)

    def _write_curve(self, section, type_idx, intensity, custom_pts=None):
        """Write the full curve block (type + intensity + recomputed LUT) — the
        firmware shapes from the LUT, so type/intensity bytes alone do nothing."""
        off = self._motion_off(section); mp = self._mp()
        if off is None or 'curve' not in mp:
            return
        npts = mp['curve_npts']
        sec = self._m.get(section, {})
        sec['curve_type'] = type_idx
        sec['curve_int'] = intensity
        if type_idx == 3:                      # custom: set type only, keep points
            self._write_motion(mp['curve'] + off, [motion.CURVE_TYPES[3][1]])
        else:
            blk = motion.curve_block(npts, type_idx, intensity)
            sec['curve_points'] = [[blk[2 + 2 * i], blk[3 + 2 * i]] for i in range(npts)]
            self._write_motion(mp['curve'] + off, blk)

    @Slot(str, int)
    def setMotionCurveType(self, section, idx):
        if 0 <= idx < len(motion.CURVE_TYPES):
            self._write_curve(section, idx, self._m.get(section, {}).get('curve_int', 100))

    @Slot(str, int)
    def setMotionCurveStrength(self, section, v):
        sec = self._m.get(section, {})
        self._write_curve(section, sec.get('curve_type', 0), max(0, min(100, int(v))))

    @Slot(str, int, int, int)
    def setMotionCurvePoint(self, section, idx, x, y):
        """Set custom curve control point `idx` to (x, y) — direct 2-byte write."""
        off = self._motion_off(section); mp = self._mp()
        if off is None or 'curve' not in mp or not (0 <= idx < mp['curve_npts']):
            return
        x = max(0, min(255, int(x))); y = max(0, min(255, int(y)))
        sec = self._m.get(section)
        if sec is not None:
            pts = [list(p) for p in sec.get('curve_points', [])]
            if idx < len(pts):
                pts[idx] = [x, y]; sec['curve_points'] = pts
        self._write_motion(mp['curve'] + 2 + 2 * idx + off, [x, y])

    @Slot(str, int, bool)
    def setMotionButton(self, section, code, on):
        """Toggle a button (target code) in/out of the activation combo (writes the
        one changed slot; 0xff = empty; no compaction — holes are fine)."""
        off = self._motion_off(section); mp = self._mp()
        slots_addr = mp.get('act_buttons', ())
        sec = self._m.get(section)
        if off is None or sec is None or not slots_addr:
            return
        slots = list(sec.get('act_slots', [motion.ACT_BTN_EMPTY] * len(slots_addr)))
        if on:
            if code in slots or motion.ACT_BTN_EMPTY not in slots:
                return                            # already set, or all slots full
            i = slots.index(motion.ACT_BTN_EMPTY)
            slots[i] = code
        else:
            if code not in slots:
                return
            i = slots.index(code)
            slots[i] = motion.ACT_BTN_EMPTY
        sec['act_slots'] = slots
        self._write_motion(slots_addr[i] + off, [slots[i]])

    @Slot(str, int, bool)
    def setMotionInvert(self, section, idx, on):
        """Toggle invert `idx` (index into the profile's inverts list)."""
        off = self._motion_off(section); inv = self._mp().get('inverts', ())
        if off is None or not (0 <= idx < len(inv)):
            return
        self._m.get(section, {})['invert_%d' % idx] = bool(on)
        self._write_motion(inv[idx][1] + off, [1 if on else 0])

    @Slot(str, int, int)
    def setMotionDir(self, section, idx, code):
        """Assign Directional-Macros slot `idx` (0=up 1=down 2=left 3=right) to a
        target CODE (gamepad/keyboard/mouse); code < 0 clears it (0x00)."""
        off = self._motion_off(section); dirs = self._mp().get('dir_macros', ())
        if off is None or not (0 <= idx < len(dirs)):
            return
        code = 0 if code < 0 else (code & 0xff)
        sec = self._m.get(section)
        if sec is not None:
            d = list(sec.get('dir_macros', [0] * len(dirs)))
            if idx < len(d):
                d[idx] = code; sec['dir_macros'] = d
        self._write_motion(dirs[idx] + off, [code])

    # ------------------------------------------------------------ macros (paddles)
    @Property('QVariantList', notify=controllerChanged)
    def macroSlots(self):
        return [n for n, _ in self._prof.MACRO_SLOTS]

    @Property('QVariantList', constant=True)
    def macroTargets(self):
        """Buttons pickable as a macro event target, as {name, code}."""
        return [{'name': n, 'code': c} for n, c in macro.TARGETS]

    @Property('QVariantList', constant=True)
    def targetCategories(self):
        """Categorized targets for the macro/remap picker: [{name, targets:[{name,code}]}].
        Buttons (gamepad) + Keyboard + Mouse — the controller emits all three."""
        return [{'name': cat, 'targets': [{'name': n, 'code': c} for n, c in items]}
                for cat, items in cfg.TARGET_CATEGORIES]

    @Slot(int, result=str)
    def targetLabel(self, code):
        return cfg.target_label(code)

    @Property('QVariantList', constant=True)
    def keyboardRows(self):
        """Rows of {name, code, w} for a keyboard-shaped picker."""
        return cfg.keyboard_rows()

    @Property('QVariantList', constant=True)
    def numpadRows(self):
        """Rows of {name, code, w} for the numpad/media/nav picker."""
        return cfg.numpad_rows()

    @Property('QVariantList', constant=True)
    def mouseTargets(self):
        return [{'name': n, 'code': c} for n, c in cfg.MOUSE_TARGETS]

    @Property('QVariantList', constant=True)
    def buttonTargets(self):
        return [{'name': n, 'code': c} for n, c in cfg.REMAP_TARGETS if c != 0xff]

    @Property(int, notify=controllerChanged)
    def macroMax(self):
        return self._prof.macro_max

    @Property('QVariantMap', notify=macroLoaded)
    def macros(self):
        """Paddle name -> {enable: bool, events: [{target, hold, delay}]}."""
        return self._macros

    def _macro_base(self, paddle):
        for name, base in self._prof.MACRO_SLOTS:
            if name == paddle:
                return base
        return None

    @Slot(str, bool)
    def setMacroEnable(self, paddle, on):
        base = self._macro_base(paddle)
        if base is None:
            return
        self._macros.setdefault(paddle, {'enable': False, 'events': []})['enable'] = bool(on)
        self._write_macro(base + macro.ENABLE_OFF, [1 if on else 0])

    @Slot(str, 'QVariantList')
    def setMacroEvents(self, paddle, events):
        """Replace a paddle's whole event list (count + events written as one block)."""
        base = self._macro_base(paddle)
        if base is None:
            return
        mx = self._prof.macro_max
        evs = [{'target': int(e['target']), 'hold': int(e['hold']), 'delay': int(e['delay'])}
               for e in events][:mx]
        self._macros.setdefault(paddle, {'enable': False, 'events': []})['events'] = evs
        self._write_macro(base + macro.COUNT_OFF, macro.block_bytes(evs, mx))

    @Slot('QVariantList')
    def applyKeyframes(self, frames):
        """`frames` is a list of frames; each frame is a list of 4 [r,g,b] ints in
        LIGHTS order. Writes them as a custom animation at the current speed/bri."""
        norm = [[[int(c[0]), int(c[1]), int(c[2])] for c in fr] for fr in frames]
        if not norm:
            return
        slot = led._resolve_slot(None)
        kf_cache.save(slot, norm, len(norm))
        _led_async(led.set_keyframes, norm, self._speed, self._brightness, slot)

    @Slot(bool, int)
    def setPlayback(self, playing, frame):
        _led_async(led.set_playback, playing, frame)

    @Slot(int)
    def selectSlot(self, n):
        """Make lighting slot n active (the lighting profiles are independent of
        the hardware button profiles, so this is its own selector). Forces a
        re-read so the page reflects that slot."""
        state['led_slot'] = n                  # optimistic; the poll confirms it
        self._loaded_led_slot = None           # force _poll_lighting to reload
        _led_async(led.select_slot, n)

    @Slot()
    def restoreLighting(self):
        _led_async(led.restore_factory)

    # ------------------------------------------------------------- mouse mode
    @Property(bool, constant=True)
    def mouseModeAvailable(self):
        return kwin.available()

    @Property(bool, notify=mouseModeChanged)
    def mouseModeOn(self):
        v = kwin.is_enabled()
        return bool(v) if v is not None else False

    @Slot(bool)
    def setMouseMode(self, on):
        kwin.set_enabled(on)
        self.mouseModeChanged.emit()

    # ------------------------------------------------------------- backup/restore
    @Property(bool, notify=backupBusyChanged)
    def backupBusy(self):
        return self._backup_busy

    @staticmethod
    def _to_path(url_or_path):
        u = QUrl(url_or_path)
        return u.toLocalFile() if u.isLocalFile() else url_or_path

    @Property(str, constant=True)
    def defaultBackupName(self):
        return 'gamesir_backup_' + datetime.now().strftime('%Y%m%d') + '.json'

    def _backup_done(self, ok, msg):
        self._backup_busy = False
        self.backupBusyChanged.emit()
        self.backupStatus.emit(ok, msg)
        # A restore changes the device underneath us — re-read everything.
        self._loaded_profile = None
        self._loaded_led_slot = None

    @Slot(str)
    def exportBackup(self, url):
        if self._backup_busy:
            return
        self._backup_busy = True
        self.backupBusyChanged.emit()
        backup.export_async(self._to_path(url),
                            on_progress=lambda d, t: self.backupProgress.emit(d, t),
                            on_done=self._backup_done)

    @Slot(str)
    def importBackup(self, url):
        if self._backup_busy:
            return
        try:
            data = backup.load(self._to_path(url))
        except (OSError, ValueError) as e:
            self.backupStatus.emit(False, str(e))
            return
        self._backup_busy = True
        self.backupBusyChanged.emit()
        # apply_backup validates + flattens the restore plan SYNCHRONOUSLY (and
        # raises on a malformed-but-schema-valid file, or one whose writes escape
        # the register map) before it spawns its worker thread. If that throws,
        # on_done never fires, so clear busy and report it here — otherwise import
        # is wedged "busy" until restart and the Qt slot raises uncaught.
        try:
            backup.apply_backup(data,
                                on_progress=lambda d, t: self.backupProgress.emit(d, t),
                                on_done=self._backup_done)
        except Exception as e:
            self._backup_busy = False
            self.backupBusyChanged.emit()
            self.backupStatus.emit(False, f'Backup is not restorable: {e}')

    # ------------------------------------------------------------- firmware flash
    # Mirrors the backup pattern: a worker thread drives gamesir_flash (enter
    # loader -> jl-uboot-tool write/read -> reset), reporting phase text. Loader
    # entry reuses the app's own command channel (control.send_cmd) so we don't
    # open a second hidraw handle alongside the reader thread.
    @Property(bool, notify=fwBusyChanged)
    def fwBusy(self):
        return self._fw_busy

    @Property(bool, notify=controllerChanged)
    def fwSupported(self):
        """Whether to offer firmware flashing. True unless we've POSITIVELY
        identified a connected controller that can't be flashed (a recognized
        G7/G7 Pro -- the Linux flasher is Cyclone/BR23-only). It deliberately
        stays True when nothing is recognized, which covers two cases the old
        `is_recognized() and can_flash` form wrongly hid:
          * mid-flash -- the controller is in the BR23 loader (a /dev/sg device,
            not a GameSir HID), so it reads as 'nothing connected'; the panel must
            stay up to show progress and the 'don't unplug' warning.
          * recovery -- a controller left stuck in the loader by an interrupted
            flash must still be flashable from the GUI (enter_loader finds the
            existing loader).
        Sending the Cyclone loader command to an unrecognized device is prevented
        independently by the recognized-model guard in control.send_cmd, so
        widening visibility here doesn't widen what can actually be written."""
        return not profiles.is_recognized() or self._prof.can_flash

    @Property(bool, notify=controllerChanged)
    def factoryResetSupported(self):
        """True only for a recognized model with a captured factory-default image
        (Cyclone). The Buttons page binds the 'Default profile' reset card to this
        so a G7/G7 Pro isn't offered a reset that would write Cyclone bytes."""
        return profiles.is_recognized() and self._prof.factory_reset

    @Property(bool, notify=controllerChanged)
    def profileResetSupported(self):
        """Any recognized, vendor-writable model can reset its profile: the ones
        with a captured factory image (Cyclone) restore the exact out-of-box bytes;
        the rest (8K) get a field-by-field write of documented default values."""
        return profiles.is_recognized() and self._prof.input_style == 'cyclone_0x12'

    @Property(int, notify=controllerChanged)
    def profileCount(self):
        """Number of editable profiles on the active controller (4 on both)."""
        return len(self._prof.profile_banks)

    @Property('QVariantList', notify=fwVersionsChanged)
    def fwVersions(self):
        return [f['version'] for f in flash.list_firmware()
                if f['kind'] == 'fw' and f['product'] == flash.PRODUCT]

    @Property(bool, constant=True)
    def firmwareToolingAvailable(self):
        """Whether jl-uboot-tool (an external, user-installed dependency) is
        present. Firmware backup/restore needs it; the panel shows an install
        note instead of the actions when it's missing."""
        return flash.tooling_available()

    def _fw_done(self, ok, msg):
        self._fw_busy = False
        self.fwBusyChanged.emit()
        self.fwStatus.emit(ok, msg)
        self.fwVersionsChanged.emit()      # a backup may have added a version
        self._loaded_profile = None        # device changed underneath us
        self._loaded_led_slot = None

    def _fw_run(self, work, done_msg):
        if self._fw_busy:
            return
        self._fw_busy = True
        self.fwBusyChanged.emit()

        def run():
            try:
                work()
                ok, msg = True, done_msg()
            except Exception as e:
                ok, msg = False, str(e)
            self._fw_done(ok, msg)
        threading.Thread(target=run, daemon=True).start()

    def _enter_loader_cmd(self, gen=None):
        """Send the BR23 enter-loader command over the app's own control channel.
        `gen` pins it to the device session captured when the flash/backup began,
        so a controller switch between the click and the send refuses the command
        instead of delivering it to a different (possibly dongle-attached) unit."""
        control.send_cmd(0x0F, 0x17, 0x55, 0x88, gen=gen)

    def _selected_node(self):
        """A /dev/hidraw node of the currently-selected controller — the device
        `_enter_loader_cmd` (via control) actually sends the loader command to.
        Passing it to the flasher lets the dongle guard validate that exact unit
        instead of whichever vendor interface happens to be streaming live."""
        from gs_common import find_controllers
        sel = state['selected']
        for c in find_controllers():
            if c['id'] == sel and c['nodes']:
                return c['nodes'][0]
        return None

    def _fw_precheck(self, verb):
        """Shared gate for firmware backup/restore: model must be flashable AND the
        external jl-uboot-tool present. Emits the reason and returns False if not."""
        if not self.fwSupported:
            self.fwStatus.emit(False, "Firmware backup/restore is only supported on "
                                      "the Cyclone 2.")
            return False
        if not flash.tooling_available():
            self.fwStatus.emit(False, "Firmware %s needs jl-uboot-tool installed "
                                      "(see FIRMWARE.md)." % verb)
            return False
        return True

    @Slot(str)
    def restoreFirmware(self, version):
        """Write a firmware image FROM YOUR LIBRARY back to the controller — a
        restore, not a flasher. The in-loader identity guard refuses anything but
        the matching wired controller."""
        if not self._fw_precheck("restore"):
            return
        prog = lambda p: self.fwProgress.emit(p)
        gen = control.generation()          # capture before resolving the node so
        node = self._selected_node()        # a rebind in between fails the send, not
        send = lambda: self._enter_loader_cmd(gen)   # a send to an unvalidated unit
        self._fw_run(
            lambda: flash.flash_version(version=version, on_progress=prog,
                                        send=send, guard_node=node),
            lambda: f"Restored firmware {version}.")

    @Slot(str)
    def backupFirmware(self, label):
        if not self._fw_precheck("backup"):
            return
        prog = lambda p: self.fwProgress.emit(p)
        gen = control.generation()
        node = self._selected_node()
        send = lambda: self._enter_loader_cmd(gen)
        out = {}
        def work():
            path, ver = flash.backup_current(label=label or None, on_progress=prog,
                                             send=send, guard_node=node)
            out['ver'] = ver
        self._fw_run(work, lambda: f"Backed up firmware {out.get('ver', '')}.")

    # ------------------------------------------------------------- config editor
    @Property('QVariantMap', notify=configLoaded)
    def config(self):
        """The selected profile's read-back config (friendly key -> value). QML
        seeds its controls from this on configLoaded."""
        return dict(self._config)

    @Property(float, notify=controllerChanged)
    def deadzoneStep(self):
        """Deadzone/anti-deadzone slider snap increment: 0.1 on models that store
        them at 16-bit resolution (8K exposes 0.1% steps), else 1 (whole %)."""
        return 0.1 if self._prof.dz_wide else 1.0

    @Property('QVariantList', notify=controllerChanged)
    def pollRates(self):
        return list(self._prof.POLL_RATES)

    @Property('QVariantList', constant=True)
    def curveNames(self):
        return list(cfg.CURVE_NAMES)        # presets; QML adds "Custom"

    @Property('QVariantMap', constant=True)
    def curvePresets(self):
        """Preset name -> its three [x,y] control points, for the curve editor."""
        return {name: [list(p) for p in cfg.curve_points(blk)]
                for name, blk in cfg.CURVE_BLOCKS}

    @Property('QVariantList', constant=True)
    def hairModes(self):
        return [name for name, _ in cfg.HAIR_MODES]

    @Property(int, notify=pendingChanged)
    def pendingCount(self):
        return len(self._pending)

    @Property('QVariantList', notify=pendingChanged)
    def pendingList(self):
        return [self._pending[a]['label'] + ': ' + self._pending[a]['display']
                for a in sorted(self._pending)]

    def _queue(self, addr, data, label, display):
        if not profiles.is_recognized():
            return          # unrecognised/absent controller: never write registers
        if self._prof.profile_bank(state['profile']) is None:
            return
        self._pending[addr] = {'data': list(data), 'label': label, 'display': str(display)}
        self.pendingChanged.emit()

    # The write-side slots below no-op when the active profile lacks the field
    # (its address map omits it), mirroring the read side (_build_config): without
    # them a partially-mapped model would KeyError in the Qt slot, and setPoll
    # would stage a None address that crashes the Apply worker at `addr + i`.
    @Slot(str, float)
    def setScalar(self, key, value):
        if key not in self._scalars:
            return
        addr, label = self._scalars[key]
        if self._prof.dz_wide and key in _WIDE_SCALAR_KEYS:
            w = max(0, min(1000, int(round(value * 10))))   # percent (0.1 steps) -> 16-bit ×10
            data = [(w >> 8) & 0xFF, w & 0xFF]
            disp = '%.1f' % (w / 10.0)
        else:
            data = [max(0, min(255, int(round(value))))]
            disp = str(data[0])
        self._queue(addr, data, label, disp)

    @Slot(str, int)
    def setTraj(self, side, index):
        if side not in self._traj_addr:
            return
        name, code = cfg.TRAJ[index]
        self._queue(self._traj_addr[side], [code],
                    ('Left' if side == 'st' else 'Right') + ' stick trajectory', name)

    @Slot(str, int)
    def setHair(self, side, index):
        if side not in self._hair_addr:
            return
        name, data = cfg.HAIR_MODES[index]
        self._queue(self._hair_addr[side], list(data), side.upper() + ' hair-trigger', name)

    @Slot(str, int)
    def setHairMin(self, side, value):
        """Hair-trigger min threshold (byte at the hair block +1)."""
        if side not in self._hair_addr:
            return
        v = max(0, min(100, int(value)))
        self._queue(self._hair_addr[side] + 1, [v], side.upper() + ' hair min', v)

    @Slot(str, int)
    def setHairMax(self, side, value):
        """Hair-trigger max threshold (byte at the hair block +2)."""
        if side not in self._hair_addr:
            return
        v = max(0, min(100, int(value)))
        self._queue(self._hair_addr[side] + 2, [v], side.upper() + ' hair max', v)

    @Property('QVariantList', constant=True)
    def hairModePresets(self):
        """Per-mode [min, max] the mode preset writes, or null if the mode keeps the
        current thresholds (Fixed). Lets the editor snap the min/max sliders when a
        mode is picked, matching what the device just stored."""
        out = []
        for _name, block in cfg.HAIR_MODES:
            out.append([block[1], block[2]] if len(block) >= 3 else None)
        return out

    @Slot(str, int)
    def setPoll(self, index):
        if self._prof.POLL_RATE is None:
            return
        self._queue(self._prof.POLL_RATE, [index], 'Poll rate', self._prof.POLL_RATES[index])

    @Property('QVariantList', notify=controllerChanged)
    def remapSources(self):
        return [name for name, _ in self._prof.REMAP_SLOTS]

    @Property('QVariantList', constant=True)
    def remapTargets(self):
        return list(cfg.REMAP_ITEMS)

    @Slot(str, str)
    def setRemap(self, source, target):
        addr = self._remap_addr.get(source)
        if addr is not None:
            self._queue(addr, cfg.remap_write_bytes(target), 'Remap ' + source, target)

    @Slot(str, int)
    def setRemapCode(self, source, code):
        """Rebind a source to any target CODE — gamepad, keyboard or mouse (they
        all write [type=0x01, code]); code < 0 clears it to Default ([00 00])."""
        addr = self._remap_addr.get(source)
        if addr is None:
            return
        data = [0x00, 0x00] if code < 0 else [0x01, code & 0xff]
        label = cfg.REMAP_NONE if code < 0 else cfg.target_label(code)
        self._queue(addr, data, 'Rebind ' + source, label)

    def _curve_block(self, key, name, intensity=100, points=None):
        """Build the curve block for `key` in the ACTIVE profile's format: a
        3-point padded block ([type,int,0,0,pts], Cyclone + 8K triggers) or a
        5-point block ([type,int,pts], 8K sticks). Custom points from the (3-point)
        editor are resampled to the block's point-count so the block is always the
        right length."""
        npts = self._prof.curve_npts(key)
        if npts == 3:
            if name == 'Custom':
                pts = [(int(p[0]), int(p[1])) for p in (points or [])]
                return cfg.custom_curve_block(pts)
            blk = cfg.preset_curve_block(name, intensity)
            return blk if blk is not None else cfg.curve_block(name)
        # 5-point (8K sticks): motion-style block, resample custom points to npts.
        type_idx = 3 if name == 'Custom' else cfg.CURVE_NAMES.index(name)
        cpts = _resample_points([(int(p[0]), int(p[1])) for p in points], npts) \
            if (name == 'Custom' and points) else None
        return motion.curve_block(npts, type_idx, intensity, cpts)

    @Slot(str, str, 'QVariantList')
    def setCurve(self, key, name, points):
        if key not in self._curve_addr:
            return
        self._queue(self._curve_addr[key], self._curve_block(key, name, 100, points),
                    key.upper() + ' curve', name)

    @Slot(str, str, int)
    def setCurveIntensity(self, key, name, intensity):
        """Write a preset curve warped to `intensity` (0..100): 100 = standard
        preset, 0 = inverse, 50 = linear. Matches the official app, which stores
        the strength in the block's byte +1 and in the (re-warped) control points."""
        if key not in self._curve_addr:
            return
        self._queue(self._curve_addr[key], self._curve_block(key, name, intensity),
                    key.upper() + ' curve', '%s %d%%' % (name, intensity))

    def _fold(self, addr, data):
        """Mirror a written value back into the cached config snapshot so the
        editor doesn't re-seed a stale value after Save (the 'second edit reverts
        the first' bug: the device was correct, but our cache wasn't)."""
        if addr in self._addr_to_scalar:
            self._config[self._addr_to_scalar[addr]] = data[0]
        elif addr in self._addr_to_curve:
            self._config[self._addr_to_curve[addr] + '_curve'] = {
                'type': cfg.curve_index(data[0]),
                'points': [list(p) for p in cfg.curve_points(data)]}
        elif addr in self._addr_to_traj:
            self._config[self._addr_to_traj[addr] + '_traj'] = cfg.enum_index(data[0], cfg.TRAJ)
        elif addr in self._addr_to_hair:
            side = self._addr_to_hair[addr]
            self._config[side + '_hair'] = cfg.enum_index(data[0], cfg.HAIR_MODES)
            if len(data) >= 3:                       # full [mode,min,max] block write
                self._config[side + '_hair_min'] = data[1]
                self._config[side + '_hair_max'] = data[2]
        elif (addr - 1) in self._addr_to_hair:       # individual min-threshold byte
            self._config[self._addr_to_hair[addr - 1] + '_hair_min'] = data[0]
        elif (addr - 2) in self._addr_to_hair:       # individual max-threshold byte
            self._config[self._addr_to_hair[addr - 2] + '_hair_max'] = data[0]
        elif addr == self._prof.POLL_RATE:
            self._config['poll'] = data[0]
        elif addr in self._addr_to_remap:
            rec = self._config.setdefault('remap', {})
            rec[self._addr_to_remap[addr]] = (data[1] if len(data) > 1 else 0) if data[0] else -1

    @Slot()
    def applyConfig(self):
        bank = self._prof.profile_bank(state['profile'])
        if bank is None:
            return
        changes = [(a, r['data']) for a, r in self._pending.items()]
        for addr, data in changes:
            self._fold(addr, data)

        style = self._prof.write_style     # capture: don't reframe if we switch
        gen = control.generation()         # pin to the live device session
        self._set_apply_status('Applying…')
        def run():
            written = []
            for addr, data in changes:
                # write_reg refuses once the handle is rebound, so a controller
                # switch mid-Apply drops the remaining edits rather than writing
                # them to the newly-selected unit.
                if not control.write_reg(bank, addr, list(data), write_style=style, gen=gen):
                    break
                written.append((addr, list(data)))
                time.sleep(0.03)   # these controllers DROP back-to-back vendor
                                   # commands (a multi-byte curve block right after
                                   # another edit is the classic casualty); pace
                                   # each write like the reset path already does
            self._verify_applied(bank, written, gen)
        threading.Thread(target=run, daemon=True).start()
        self._pending = {}
        self.pendingChanged.emit()

    def _set_apply_status(self, msg):
        self._apply_status = msg
        self.applyStatusChanged.emit()

    def _verify_applied(self, bank, written, gen):
        """Read every just-written register straight back and compare to what we
        sent — the only way to KNOW an edit landed on the hardware (a write that's
        silently dropped, e.g. the pad not in Xbox mode or a dongle that doesn't
        forward vendor writes, looks identical to a successful one otherwise).
        Surfaces a pass/mismatch summary to the UI and the console."""
        import sys
        if not written or gen != control.generation():
            self._set_apply_status('')
            return
        # queue fresh reads (clears any stale cached value for these addrs)
        control.request_regs([(bank, addr, len(data)) for addr, data in written])
        pending = {addr for addr, _ in written}
        got = {}
        deadline = time.time() + 2.5
        while pending and time.time() < deadline and gen == control.generation():
            for addr, data in written:
                if addr in pending:
                    r = control.reg_result(bank, addr)
                    if r is not None:
                        got[addr] = list(r)
                        pending.discard(addr)
            time.sleep(0.04)

        ok, bad, unknown = 0, [], 0
        for addr, data in written:
            r = got.get(addr)
            if r is None:
                unknown += 1
            elif r[:len(data)] == data:
                ok += 1
            else:
                bad.append((addr, data, r[:len(data)]))

        total = len(written)
        for addr, data, r in bad:
            print('[apply] MISMATCH @%s bank%d: wrote %s, read %s'
                  % (self._addr_name(addr), bank,
                     ' '.join('%02x' % b for b in data),
                     ' '.join('%02x' % b for b in r)), file=sys.stderr)
        if unknown:
            print('[apply] %d/%d writes could not be read back (no reply)'
                  % (unknown, total), file=sys.stderr)
        print('[apply] verified %d/%d writes confirmed on device' % (ok, total),
              file=sys.stderr)

        if ok == total:
            self._set_apply_status('Applied ✓  %d/%d confirmed' % (ok, total))
        elif ok == 0 and unknown == total:
            self._set_apply_status('⚠ Could not confirm — no read-back '
                                   '(is the controller in Xbox mode?)')
        else:
            self._set_apply_status('⚠ %d/%d confirmed, %d not applied'
                                   % (ok, total, total - ok))

    def _addr_name(self, addr):
        if addr in self._addr_to_scalar:
            return self._addr_to_scalar[addr]
        if addr in self._addr_to_curve:
            return self._addr_to_curve[addr] + '_curve'
        if addr in self._addr_to_traj:
            return self._addr_to_traj[addr] + '_traj'
        if addr in self._addr_to_hair:
            return self._addr_to_hair[addr] + '_hair'
        return '0x%04x' % addr

    @Property(str, notify=applyStatusChanged)
    def applyStatus(self):
        return self._apply_status

    @Slot()
    def clearApplyStatus(self):
        self._set_apply_status('')

    @Slot()
    def discardConfig(self):
        self._pending = {}
        self.pendingChanged.emit()
        self.configLoaded.emit()        # snap controls back to last-loaded values

    # Documented default analog config (shared across the vendor family). Used to
    # reset a profile on models WITHOUT a captured factory image (e.g. the 8K).
    # Remaps are intentionally NOT auto-cleared here: the correct "default record"
    # differs per slot (face buttons keep a self/default record, paddles are blank)
    # and a wrong write could disable a button -- clearing remaps is a separate,
    # per-slot action. Stick DZ min uses the RE'd Cyclone default (10); revisit if
    # an 8K factory capture shows otherwise.
    _DEFAULT_SCALARS = {
        'VIB_L': 75, 'VIB_R': 75, 'POLL_RATE': 2,
        'ST_DZ_MIN': 5, 'ST_DZ_MAX': 100, 'ST_ADZ_MIN': 0, 'ST_ADZ_MAX': 100,
        'RS_DZ_MIN': 5, 'RS_DZ_MAX': 100, 'RS_ADZ_MIN': 0, 'RS_ADZ_MAX': 100,
        'LT_DZ_MIN': 5, 'LT_DZ_MAX': 95, 'LT_ADZ_MIN': 0, 'LT_ADZ_MAX': 100,
        'RT_DZ_MIN': 5, 'RT_DZ_MAX': 95, 'RT_ADZ_MIN': 0, 'RT_ADZ_MAX': 100,
        'ST_TRAJ': 0, 'RS_TRAJ': 0, 'LT_HAIR': 0, 'RT_HAIR': 0,
    }

    def _write_generic_defaults(self, bank, style, gen):
        # These controllers DROP back-to-back vendor commands, so pace each write
        # (else a field like LT adz-max silently doesn't land and stays at 0).
        p = self._prof
        def w(addr, data):
            if addr is not None:
                control.write_reg(bank, addr, data, write_style=style, gen=gen)
                time.sleep(0.03)
        for attr, val in self._DEFAULT_SCALARS.items():
            w(getattr(p, attr, None), self._default_scalar_bytes(p, attr, val))
        for key, attr in (('st', 'ST_CURVE'), ('rs', 'RS_CURVE'),
                          ('lt', 'LT_CURVE'), ('rt', 'RT_CURVE')):
            w(getattr(p, attr, None), self._default_curve_bytes(p, key))

    @Slot()
    def resetProfileToDefault(self):
        """Reset the active profile to defaults, then re-read so every page
        reflects it. Models with a captured factory image (Cyclone) restore the
        exact out-of-box bytes; others (8K) get a field-by-field default write."""
        if not self.profileResetSupported:
            return
        bank = self._prof.profile_bank(state['profile'])
        if bank is None:
            return
        self._pending = {}
        self.pendingChanged.emit()

        prof = self._prof
        style = prof.write_style            # capture: pin framing + session, so a
        gen = control.generation()          # mid-reset switch can't misroute writes
        def run():
            if prof.factory_reset:
                factory.restore_default_profile(bank, write_style=style, gen=gen)
            else:
                self._write_generic_defaults(bank, style, gen)
            self._loaded_profile = None     # force config re-read after writes land
            self._loaded_led_slot = None    # and lighting re-read
        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def resetAllProfiles(self):
        """Reset ALL profile banks to defaults. A bank is only writable while its
        profile is active, so switch to each profile, reset its bank, then restore
        whichever profile was active. Reports through the backup status channel (it
        lives in the same Backup & Restore panel)."""
        if not self.profileResetSupported or self._backup_busy:
            return
        prof = self._prof
        banks = prof.profile_banks
        if not banks:
            return
        self._pending = {}
        self.pendingChanged.emit()
        self._backup_busy = True
        self.backupBusyChanged.emit()
        style = prof.write_style
        gen = control.generation()
        original = state.get('profile') or banks[0]
        def run():
            try:
                for i, n in enumerate(banks):
                    control.set_profile(n)
                    time.sleep(0.2)
                    if prof.factory_reset:
                        factory.restore_default_profile(n, write_style=style, gen=gen)
                    else:
                        self._write_generic_defaults(n, style, gen)
                    self.backupProgress.emit(i + 1, len(banks))
                control.set_profile(original)
                time.sleep(0.2)
                self._loaded_profile = None
                self._loaded_led_slot = None
                self._backup_done(True, 'Reset all %d profiles to defaults.' % len(banks))
            except Exception as e:
                self._backup_done(False, 'Reset all profiles failed: %s' % e)
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------- user actions
    @Slot(int)
    def setProfile(self, n):
        control.set_profile(n)

    @Slot()
    def rumbleTest(self):
        control.rumble_test()
