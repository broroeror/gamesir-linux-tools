"""
MouseBridge — exposes the Logitech G502 X onboard config to the QML UI.
=======================================================================
The controller side has its own always-on reader + GamesirBridge; the mouse is
simpler: no live-input stream, just on-demand read/write of the onboard profile
via the (proven, gated) vendors/logitech backend. This bridge:

  * detects the G502 X and reports presence + why-not (permission / absent),
  * reads the active profile's per-button bindings for display,
  * applies a remap to a button through config.apply_binding (backed up + gated
    + read-back-verified — the device is only ever left verified or untouched).

Device I/O runs on a WORKER THREAD (a single onboard write is ~50-100 HID++
round-trips, seconds over the wireless link) so the GUI never freezes; results
are marshalled back to the GUI thread via private signals (Qt delivers a
cross-thread emit as a queued connection), where the exposed state is updated.
A `busy` flag drives an "Applying…" state and blocks overlapping operations.

Runs as the logged-in user; hidraw write access comes from the udev rule in
packaging/udev (no sudo). Until that rule is installed the device shows up but
isn't openable, which we surface as permission == "no-access".
"""

import json
import os
import sys
import threading

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

_LOGI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendors', 'logitech')
if _LOGI not in sys.path:
    sys.path.insert(0, _LOGI)
import hidpp                     # noqa: E402
import config as logi_config     # noqa: E402  (vendors/logitech/config.py)

# Canonical G502 X button names, keyed by onboard-profile slot index. Kept in sync
# with MouseView.qml's `buttons` table (the visual source of truth) so a queued-
# change chip reads the same on any tab, including the DPI tab which has no diagram.
BUTTON_NAMES = {
    0: 'Left Click', 1: 'Right Click', 2: 'Middle Click',
    3: 'Backward', 4: 'DPI Shift', 5: 'Forward', 6: 'Scroll L/T', 7: 'Scroll R/T',
    8: 'Profile Cycle', 9: 'DPI Up', 10: 'DPI Down',
}
# Grouped, ordered button picker (device index per group). Names/groups follow the
# industry convention (label by default action — G HUB/Synapse do the same).
BUTTON_GROUPS = [
    ('Clicks', [0, 1, 2]),
    ('Scroll', [6, 7]),
    ('DPI', [9, 10, 4]),
    ('Thumb', [8, 5, 3]),
]
# Flat display order (matches the grouping above).
BUTTON_ORDER = [i for _, idxs in BUTTON_GROUPS for i in idxs]

# Report rates the G502 X LIGHTSPEED supports, low→high (1000/500/250/125 Hz map to
# the 1/2/4/8 ms interval stored in the profile's byte 0).
REPORT_RATES = [125, 250, 500, 1000]
# Sensor range fallback if feature 0x2201 can't be read (the HERO 25K's documented
# range); a live dpi_range() query overrides these.
DPI_FALLBACK = {'min': 100, 'max': 25600, 'step': 50}


class MouseBridge(QObject):
    presenceChanged = Signal()   # present / permission / activeProfile changed
    profilesChanged = Signal()   # the profile list / which one is selected changed
    bindingsChanged = Signal()   # the per-button binding map changed
    sensorChanged = Signal()     # DPI stages / indices / report rate / range changed
    statusChanged = Signal()     # last action result text changed
    applyStatusChanged = Signal()  # the Apply toast text ("Applying…" / ✓ / ⚠)
    busyChanged = Signal()       # a device write is in flight
    pendingChanged = Signal()    # the staged (unsaved) change set changed

    # Private carriers from the worker thread back to the GUI thread. Emitting a
    # signal from another thread to this (GUI-thread) object is delivered as a
    # queued connection, so the handlers run on the GUI thread and it's safe to
    # touch the exposed state there.
    _refreshDone = Signal(bool, str, int, int, int, bool, 'QVariantMap', 'QVariantList')  # present, perm, active, count, battery, wireless, binds, profiles
    _profileDone = Signal(bool, str, int)                      # ok, message, active-after
    _remapDone = Signal(bool, str, 'QVariantMap')               # ok, status, binds
    _applyDone = Signal(bool, str, 'QVariantMap')               # ok, status, binds
    _macroSlotsDone = Signal(int)                              # free macro sector count
    _reclaimDone = Signal(bool, str, int)                      # ok, message, free-after

    def __init__(self, parent=None):
        super().__init__(parent)
        self._present = False
        self._permission = 'unknown'    # ok | no-access | absent | unknown
        self._active = 0
        self._profiles = []             # [{index, sector, name, enabled}] from the directory
        self._selected = 0              # sector being EDITED (0 = follow the active one)
        self._button_count = 0
        self._battery = -1              # state-of-charge %, -1 = unknown
        self._wireless = False
        self._status = ''
        self._apply_status = ''         # Apply toast text ('' = hidden)
        self._busy = False
        self._bindings = {}             # primary-bank labels {str(i): label}
        self._gbindings = {}            # G-Shift (alternate) bank labels
        # sensor header (bytes 0..12 of the active profile)
        self._dpi_stages = []           # the 5 DPI resolutions
        self._dpi_default = 0           # index of the active/boot stage
        self._dpi_shift = 0             # index of the sniper (shift-DPI) stage
        self._report_rate = 0           # Hz
        self._dpi_min = DPI_FALLBACK['min']
        self._dpi_max = DPI_FALLBACK['max']
        self._dpi_step = DPI_FALLBACK['step']
        self._pending = {}              # {'<layer>:<button>': spec} — staged buttons
        self._pending_sensor = {}       # {'dpi:<i>'|'dpi_default'|'dpi_shift'|'report_rate': int}
        self._pending_macros = {}       # {button:int -> macrodef dict} — staged macros (primary bank)
        self._macro_slots_free = -1     # erased macro sectors available; -1 = not probed
        self._io = threading.Lock()     # serialize device access (worker threads)

        self._refreshDone.connect(self._on_refresh)
        self._remapDone.connect(self._on_remap)
        self._applyDone.connect(self._on_apply)
        self._macroSlotsDone.connect(self._on_macro_slots)
        self._reclaimDone.connect(self._on_reclaim)
        self._profileDone.connect(self._on_profile_switch)

        # light hotplug poll: enumerate (no open) every few seconds; a full read
        # happens only on a connect transition or an explicit refresh().
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self.refresh()

    # ---------------------------------------------- probing (GUI thread, cheap)
    def _node_pid(self):
        """USB product id of an enumerable G502 X node (no open needed), or None —
        lets us tell wired (0xC098) from the wireless/receiver ids."""
        try:
            import hid
            for d in hid.enumerate():
                if d.get('vendor_id') == hidpp.LOGITECH_VID and \
                        d.get('product_id') in (hidpp.G502X_PIDS + (0xC547,)):
                    return d.get('product_id')
        except Exception:
            pass
        return None

    def _node_present(self):
        return self._node_pid() is not None

    def _poll(self):
        if self._busy:
            return
        node = self._node_present()
        if node and not self._present:
            self.refresh()                       # just connected -> read it
        elif not node and self._present:
            self._present = False
            self._permission = 'absent'
            self.presenceChanged.emit()

    @staticmethod
    def _read_profiles(dev):
        """The onboard profile directory as [{index, sector, name, enabled}].

        Names come from `profile_name()` (three 16-byte reads each) rather than
        whole sectors, so listing all five costs ~15 transactions instead of 80.
        An unnamed profile gets a positional fallback label, since G HUB leaves
        the name blank unless someone types one."""
        # the mouse's own factory profiles, so "reset" restores what it shipped
        # with instead of a default layout invented here; [] on devices with none
        oob = [h[0] for h in getattr(dev, 'oob_headers', lambda: [])()]
        out = []
        for i, (sector, enabled) in enumerate(dev.profile_headers(), start=1):
            try:
                name = dev.profile_name(sector)
            except Exception:
                name = ''
            # Pair profile N with factory profile N where one exists. The G502 X
            # has 5 profile slots but only 2 OOB profiles, so the rest fall back
            # to the first -- which is what the untouched slots on this device
            # actually match (same 1000Hz, same PROFILE_NAME_DEFAULT name).
            if i <= len(oob):
                factory = oob[i - 1]
            elif oob:
                factory = oob[0]
            else:
                factory = 0
            out.append({'index': i, 'sector': sector, 'name': name,
                        'label': name or f'Profile {i}', 'enabled': bool(enabled),
                        'factory': factory})
        return out

    @staticmethod
    def _read_both(dev, active, size):
        """{'buttons', 'gbuttons', 'sensor'} for the UI — both button banks AND the
        sensor header (DPI stages + indices + report rate), from one sector read."""
        raw = logi_config.profile_bindings(dev, active, size)

        def mk(d):
            return {str(i): (b['label'] or b['kind']) for i, b in d.items()}
        return {'buttons': mk(raw['buttons']), 'gbuttons': mk(raw['gbuttons']),
                'sensor': raw['sensor']}

    def _set_apply(self, msg):
        """Set the Apply toast. A message ending in '…' reads as in-progress: the
        toast renders it neutral and holds it until the result replaces it."""
        self._apply_status = msg
        self.applyStatusChanged.emit()

    def _set_status(self, msg):
        self._status = msg
        self.statusChanged.emit()

    def _set_binds(self, binds):
        self._bindings = binds.get('buttons', {})
        self._gbindings = binds.get('gbuttons', {})
        self.bindingsChanged.emit()
        sensor = binds.get('sensor')
        rng = binds.get('range')
        if sensor is not None or rng is not None:
            if sensor is not None:
                self._dpi_stages = list(sensor.get('dpi', []))
                self._dpi_default = sensor.get('dpi_default', 0)
                self._dpi_shift = sensor.get('dpi_shift', 0)
                self._report_rate = sensor.get('report_rate_hz', 0)
            if rng:
                self._dpi_min = rng.get('min', self._dpi_min)
                self._dpi_max = rng.get('max', self._dpi_max)
                self._dpi_step = rng.get('step') or self._dpi_step
            self.sensorChanged.emit()

    # --------------------------------------------------------------- properties
    @Property(bool, notify=presenceChanged)
    def present(self):
        return self._present

    @Property(str, notify=presenceChanged)
    def permission(self):
        return self._permission

    @Property(int, notify=presenceChanged)
    def activeProfile(self):
        return self._active

    @Property('QVariantList', notify=profilesChanged)
    def profiles(self):
        """The onboard profiles: [{index, sector, name, label, enabled}]."""
        return list(self._profiles)

    @Property(int, notify=profilesChanged)
    def selectedProfile(self):
        """Sector of the profile being EDITED — not necessarily the active one."""
        return self._selected

    @Slot(int)
    def selectProfile(self, sector):
        """Choose which profile the pages edit. Costs no device write: it just
        re-reads that sector. Refused while edits are staged, because the queue
        was built against the profile it was staged on and silently retargeting
        it would write someone's rebinds into the wrong profile."""
        sector = int(sector)
        if sector == self._selected or sector not in [p['sector'] for p in self._profiles]:
            return
        if self._pending or self._pending_sensor or self._pending_macros:
            self._set_apply('⚠ apply or discard your staged changes first')
            return
        self._selected = sector
        self.profilesChanged.emit()
        self._set_apply('Reading profile…')   # a read, but not an instant one
        self.refresh()                        # re-read bindings for the new target

    @Slot(int)
    def makeActive(self, sector):
        """Make `sector` the profile the mouse actually uses (a device write, but
        not a flash write). Off-thread; the result lands in the Apply toast."""
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit()
        self._set_apply('Switching profile…')
        threading.Thread(target=self._profile_worker, args=(int(sector),),
                         daemon=True).start()

    def _profile_worker(self, sector):
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._profileDone.emit(False, 'mouse not accessible — connected and permitted?', 0)
                return
            try:
                with dev:
                    now = dev.set_current_profile(sector)   # returns what the device reports
                if now != sector:
                    self._profileDone.emit(
                        False, f'the mouse stayed on profile sector 0x{now:04x}', now)
                    return
                self._profileDone.emit(True, f'switched to {self._label_for(sector)}', now)
            except Exception as e:
                self._profileDone.emit(False, f'could not switch profile: {e}', 0)

    @Property(bool, notify=profilesChanged)
    def resetSupported(self):
        """True when the mouse exposes a factory profile to restore from. The
        reset action stays hidden otherwise rather than offering a button that
        cannot work."""
        return any(p.get('factory') for p in self._profiles)

    @Slot()
    def resetProfile(self):
        """Restore the SELECTED profile to the mouse's factory copy (off-thread).
        Everything in that profile goes back: buttons, G-Shift, DPI, rate, name."""
        if self._busy:
            return
        target = self._selected
        factory = 0
        for p in self._profiles:
            if p['sector'] == target:
                factory = p.get('factory') or 0
        if not factory:
            self._set_status('this mouse has no factory profile to restore from')
            return
        self._busy = True
        self.busyChanged.emit()
        self._pending = {}                 # the queue was staged against the old
        self._pending_sensor = {}          # contents; a reset makes it meaningless
        self._pending_macros = {}
        self.pendingChanged.emit()
        self._set_apply('Restoring factory settings…')
        threading.Thread(target=self._reset_worker, args=(target, factory),
                         daemon=True).start()

    def _reset_worker(self, sector, factory):
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._profileDone.emit(False, 'mouse not accessible — connected and permitted?', 0)
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    hdr = [h for h in headers if h[0] == sector] or [(sector, 1)]
                    ok, msg = logi_config.reset_profile_to_oob(
                        dev, info, headers, sector, factory, backup_headers=hdr)
                self._profileDone.emit(ok, msg, self._active)
            except Exception as e:
                self._profileDone.emit(False, f'reset failed: {e}', 0)

    @Slot(int, str)
    def renameProfile(self, sector, name):
        """Rename a profile (a flash write, so it's gated + backed up like any
        other). Off-thread; the result lands in the Apply toast."""
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit()
        self._set_apply('Renaming…')
        threading.Thread(target=self._rename_worker,
                         args=(int(sector), str(name)), daemon=True).start()

    def _rename_worker(self, sector, name):
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._profileDone.emit(False, 'mouse not accessible — connected and permitted?', 0)
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    hdr = [h for h in headers if h[0] == sector] or [(sector, 1)]
                    ok, msg = logi_config.rename_profile(
                        dev, info, headers, sector, name, backup_headers=hdr)
                self._profileDone.emit(ok, msg, self._active)
            except Exception as e:
                self._profileDone.emit(False, f'rename failed: {e}', 0)

    def _label_for(self, sector):
        for p in self._profiles:
            if p['sector'] == sector:
                return p['label']
        return f'sector 0x{sector:04x}'

    def _on_profile_switch(self, ok, message, active_now):
        self._busy = False
        self.busyChanged.emit()
        self._set_apply(('✓ ' if ok else '⚠ ') + message)
        if ok:
            self._active = active_now
            self.presenceChanged.emit()
        self.refresh()

    @Property(int, notify=presenceChanged)
    def buttonCount(self):
        return self._button_count

    @Property(int, notify=presenceChanged)
    def battery(self):
        return self._battery            # state-of-charge %, or -1 if unknown

    @Property(bool, notify=presenceChanged)
    def wireless(self):
        return self._wireless

    @Property('QVariantMap', notify=bindingsChanged)
    def bindings(self):
        return self._bindings

    @Property('QVariantMap', notify=bindingsChanged)
    def gbindings(self):
        return self._gbindings

    # ---- sensor: DPI stages, active/sniper index, report rate, range ----------
    @Property('QVariantList', notify=sensorChanged)
    def dpiStages(self):
        return list(self._dpi_stages)

    @Property(int, notify=sensorChanged)
    def dpiDefault(self):
        return self._dpi_default

    @Property(int, notify=sensorChanged)
    def dpiShift(self):
        return self._dpi_shift

    @Property(int, notify=sensorChanged)
    def reportRate(self):
        return self._report_rate

    @Property(int, notify=sensorChanged)
    def dpiMin(self):
        return self._dpi_min

    @Property(int, notify=sensorChanged)
    def dpiMax(self):
        return self._dpi_max

    @Property(int, notify=sensorChanged)
    def dpiStep(self):
        return self._dpi_step

    @Property('QVariantList', constant=True)
    def reportRates(self):
        return list(REPORT_RATES)

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=applyStatusChanged)
    def applyStatus(self):
        return self._apply_status       # '' hidden | 'Applying…' | '✓ …' | '⚠ …'

    @Slot()
    def clearApplyStatus(self):
        if self._apply_status:
            self._apply_status = ''
            self.applyStatusChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(int, notify=pendingChanged)
    def pendingCount(self):
        return len(self._pending) + len(self._pending_sensor) + len(self._pending_macros)

    @Property('QVariantMap', notify=pendingChanged)
    def pending(self):
        """Staged (unsaved) BUTTON targets, {'<layer>:<button>': label}, for the
        Buttons page to preview per-button (list + diagram). Includes staged macros
        (primary bank) so a macro'd button shows in the list too."""
        out = {}
        for b, spec in self._pending.items():
            try:
                out[str(b)] = logi_config.friendly_binding(logi_config.binding_from_spec(spec))
            except Exception:
                out[str(b)] = spec
        for btn, mdef in self._pending_macros.items():
            out[f'default:{btn}'] = 'Macro: ' + logi_config.macro_summary(mdef)
        return out

    @Property('QVariantMap', notify=pendingChanged)
    def pendingSensor(self):
        """Staged (unsaved) SENSOR edits, {key: numeric value}, for the DPI page to
        reflect a staged-but-unapplied stage/index/rate on the control itself."""
        return dict(self._pending_sensor)

    @staticmethod
    def _sensor_chip(key, value):
        """Friendly (name, label) for a staged sensor edit — the DPI-tab chips."""
        if key.startswith('dpi:'):
            return f'DPI {int(key[4:]) + 1}', f'{int(value)}'
        if key == 'dpi_default':
            return 'Active DPI', f'Stage {int(value) + 1}'
        if key == 'dpi_shift':
            return 'Sniper DPI', f'Stage {int(value) + 1}'
        if key == 'report_rate':
            return 'Report rate', f'{int(value)} Hz'
        return key, str(value)

    @Property('QVariantList', notify=pendingChanged)
    def pendingList(self):
        """Every staged change (buttons + G-Shift + sensor) as self-describing chip
        rows [{group, key, name, label}], so any tab's pending bar renders and
        removes them identically."""
        out = []
        for key, spec in self._pending.items():
            layer, _, idx = key.partition(':')
            try:
                label = logi_config.friendly_binding(logi_config.binding_from_spec(spec))
            except Exception:
                label = spec
            out.append({'group': 'gshift' if layer == 'gshift' else 'button',
                        'key': key, 'name': BUTTON_NAMES.get(int(idx), f'Button {idx}'),
                        'label': label})
        for key, value in self._pending_sensor.items():
            name, label = self._sensor_chip(key, value)
            out.append({'group': 'sensor', 'key': key, 'name': name, 'label': label})
        for btn, mdef in self._pending_macros.items():
            out.append({'group': 'macro', 'key': f'macro:{btn}',
                        'name': BUTTON_NAMES.get(btn, f'Button {btn}'),
                        'label': 'Macro: ' + logi_config.macro_summary(mdef)})
        return out

    @Property(int, notify=sensorChanged)
    def macroSlotsFree(self):
        return self._macro_slots_free       # erased macro sectors available, -1=unknown

    @Property('QVariantList', constant=True)
    def buttonList(self):
        """Ordered [{index, name}] for the button pickers (macros tab selector)."""
        return [{'index': i, 'name': BUTTON_NAMES.get(i, f'Button {i}')} for i in BUTTON_ORDER]

    @Property('QVariantList', constant=True)
    def buttonGroups(self):
        """Grouped [{group, buttons:[{index,name}]}] for the macros-tab button picker."""
        return [{'group': g, 'buttons': [{'index': i, 'name': BUTTON_NAMES.get(i, f'Button {i}')}
                                         for i in idxs]}
                for g, idxs in BUTTON_GROUPS]

    @Slot(int, result='QVariantMap')
    def stagedMacro(self, button):
        """The staged macro def for a button ({'steps':[...], 'repeat':bool,
        'speed':float}), or an empty map — lets the macros tab resume editing a
        macro already in the queue."""
        return dict(self._pending_macros.get(int(button), {}))

    @Property('QVariantList', constant=True)
    def mediaActions(self):
        """[{code, name}] consumer-control (media) actions for the Media popout."""
        return [{'code': c, 'name': n} for c, n in logi_config.macros.CONSUMER.items()]

    # ------------------------------------------------------------- worker thread
    def _refresh_worker(self):
        with self._io:
            pid = self._node_pid()
            wireless = pid is not None and pid != 0xC098
            dev = hidpp.find_device()
            if dev is None:
                perm = 'no-access' if pid is not None else 'absent'
                self._refreshDone.emit(False, perm, 0, 0, -1, wireless, {}, [])
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    active = dev.current_profile()
                    profiles = self._read_profiles(dev)
                    # show whichever profile the user picked, defaulting to the
                    # active one (and falling back to it if the pick vanished)
                    target = self._selected or active
                    if target not in [p['sector'] for p in profiles]:
                        target = active
                    binds = self._read_both(dev, target, info['sector_size'])
                    binds['range'] = getattr(dev, 'dpi_range', lambda: None)()
                    bat = getattr(dev, 'battery', lambda: None)()
                pct = bat['percent'] if bat else -1
                self._refreshDone.emit(True, 'ok', active, info['button_count'], pct,
                                       wireless, binds, profiles)
            except Exception as e:
                self._refreshDone.emit(False, f'read error: {e}', 0, 0, -1, wireless, {}, [])

    def _remap_worker(self, button, spec, target):
        try:
            binding = logi_config.binding_from_spec(spec)
        except ValueError as e:
            self._remapDone.emit(False, f'unsupported target: {e}', {})
            return
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._remapDone.emit(False, 'mouse not accessible — connected and permitted?', {})
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    # edits go to the profile the user picked, which is NOT always
                    # the one the mouse is currently running
                    active = target or dev.current_profile()
                    active_hdr = [h for h in headers if h[0] == active] or [(active, 1)]
                    ok, msg = logi_config.apply_binding(
                        dev, info, headers, active, button, binding,
                        backup_headers=active_hdr)          # back up only the edited profile
                    binds = self._read_both(dev, active, info['sector_size']) if ok else {}
                self._remapDone.emit(ok, msg, binds)
            except Exception as e:
                self._remapDone.emit(False, f'error: {e}', {})

    # ------------------------------------------------- GUI-thread result handlers
    def _on_refresh(self, present, perm, active, count, battery, wireless, binds, profiles):
        self._permission = perm
        self._present = present
        self._active = active
        sectors = [p['sector'] for p in profiles]
        if self._profiles != profiles:
            self._profiles = profiles
        if self._selected not in sectors:      # first read, or the pick disappeared
            self._selected = active if active in sectors else (sectors[0] if sectors else 0)
        self.profilesChanged.emit()
        self._button_count = count
        self._battery = battery
        self._wireless = wireless
        if present:
            self._set_binds(binds)      # updates both banks + sensor state
        elif self._pending or self._pending_sensor or self._pending_macros:
            self._pending = {}          # device gone -> staged edits are stale
            self._pending_sensor = {}
            self._pending_macros = {}
            self.pendingChanged.emit()
        if self._apply_status == 'Reading profile…':
            self._set_apply('')               # the read finished; nothing to report
        self.presenceChanged.emit()

    def _on_remap(self, ok, status, binds):
        self._busy = False
        self.busyChanged.emit()
        self._status = status
        self.statusChanged.emit()
        if ok and binds:
            self._set_binds(binds)

    def _on_macro_slots(self, free):
        self._macro_slots_free = free
        self.sensorChanged.emit()

    # -------------------------------------------------------------------- slots
    @Slot()
    def refresh(self):
        """Detect the device and read the active profile's bindings (off-thread)."""
        if self._busy:
            return
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    @Slot(int, str)
    def remap(self, button, spec):
        """Apply a single binding to `button` immediately (off-thread). spec
        vocabulary: key:<char|name> | mouse:<n> | sniper | dpi-up | dpi-down |
        dpi-cycle | disabled. Prefer stage()+apply() for multi-button edits."""
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit()
        threading.Thread(target=self._remap_worker,
                         args=(button, spec, self._selected), daemon=True).start()

    # ------------------------------------------------- staged (batched) editing
    @Slot(str, int, str)
    def stage(self, layer, button, spec):
        """Queue a change for `button` on `layer` ('default' | 'gshift') — no device
        I/O. Validates the spec so a bad target is caught before Apply."""
        try:
            logi_config.binding_from_spec(spec)      # validate only
        except ValueError as e:
            self._set_status(f'unsupported target: {e}')
            return
        self._pending[f'{layer}:{int(button)}'] = spec
        if layer == 'default':
            self._pending_macros.pop(int(button), None)   # a plain bind supersedes a staged macro
        self.pendingChanged.emit()

    @Slot(int, str)
    def stageMacro(self, button, macro_json):
        """Queue a MACRO for `button` (primary bank). `macro_json` is the editor's
        JSON: {"steps":[...], "repeat":bool, "speed":float}. Validated (built) here
        so a bad macro is caught before Apply (an out-of-range speed included).
        Supersedes any plain bind staged on this button."""
        if not (0 <= int(button) < (self._button_count or 16)):
            return                                       # ignore an out-of-range button
        try:
            mdef = json.loads(macro_json)
            body = logi_config.build_macro_body(mdef)    # validate (raises ValueError)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self._set_status(f'bad macro: {e}')
            return
        # size guard at STAGE time so the editor flags an over-limit macro while
        # it's being built, not at Apply. 255 = the G502 X's sector size (the
        # only supported mouse); apply_edits re-checks with the real value.
        limit = logi_config.max_macro_bytes(255)
        if len(body) > limit:
            self._set_status(f'macro too long ({len(body)} bytes; the mouse can '
                             f'store about {limit}) — trim some steps')
            return
        self._pending_macros[int(button)] = mdef
        self._pending.pop(f'default:{int(button)}', None)
        self.pendingChanged.emit()

    @Slot()
    def probeMacroSlots(self):
        """Count the free (erased) macro sectors off-thread; updates macroSlotsFree.
        Called when the macro editor opens so the UI can warn when slots run low."""
        if self._busy:
            return
        threading.Thread(target=self._probe_macro_worker, daemon=True).start()

    def _probe_macro_worker(self):
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    free = len(logi_config.free_macro_sectors(dev, info, headers))
                self._macroSlotsDone.emit(free)
            except Exception:
                pass

    @Slot()
    def reclaimSlots(self):
        """Blank every orphaned macro sector (nothing points at it, in any
        profile) to free slots — off-thread; result shows in the Apply toast."""
        if self._busy:
            return
        self._busy = True
        self.busyChanged.emit()
        self._apply_status = 'Applying…'
        self.applyStatusChanged.emit()
        threading.Thread(target=self._reclaim_worker, daemon=True).start()

    def _reclaim_worker(self):
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._reclaimDone.emit(False, 'mouse not accessible', -1)
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    ok, _, msg = logi_config.reclaim_orphan_macros(dev, info, headers)
                    free = len(logi_config.free_macro_sectors(dev, info, headers))
                self._reclaimDone.emit(ok, msg, free)
            except Exception as e:
                self._reclaimDone.emit(False, f'error: {e}', -1)

    def _on_reclaim(self, ok, msg, free):
        self._busy = False
        self.busyChanged.emit()
        self._apply_status = ('✓ ' if ok else '⚠ ') + msg
        self.applyStatusChanged.emit()
        if free >= 0:
            self._macro_slots_free = free
            self.sensorChanged.emit()

    @Slot(str, int)
    def unstage(self, layer, button):
        """Drop one staged BUTTON change (by layer + button)."""
        if self._pending.pop(f'{layer}:{int(button)}', None) is not None:
            self.pendingChanged.emit()

    @Slot(str)
    def unstageItem(self, key):
        """Drop one staged change by its pendingList key — button, sensor, or macro.
        Keyspaces are distinct: 'default:'/'gshift:' vs 'dpi'/'report_rate' vs
        'macro:<n>'."""
        if key.startswith('macro:'):
            if self._pending_macros.pop(int(key[6:]), None) is not None:
                self.pendingChanged.emit()
        elif self._pending.pop(key, None) is not None or \
                self._pending_sensor.pop(key, None) is not None:
            self.pendingChanged.emit()

    @Slot()
    def discard(self):
        """Drop all staged changes (buttons + sensor + macros)."""
        if self._pending or self._pending_sensor or self._pending_macros:
            self._pending = {}
            self._pending_sensor = {}
            self._pending_macros = {}
            self.pendingChanged.emit()

    # --------------------------------------------- sensor (DPI / rate) staging
    @Slot(int, int)
    def stageDpi(self, index, value):
        """Queue a DPI-stage value change (snapped/clamped to the sensor range)."""
        if not (0 <= index < 5):
            return
        step = self._dpi_step or 1
        v = max(self._dpi_min, min(self._dpi_max, int(value)))
        v = int(round((v - self._dpi_min) / step)) * step + self._dpi_min
        v = max(self._dpi_min, min(self._dpi_max, v))
        self._pending_sensor[f'dpi:{index}'] = v
        self.pendingChanged.emit()

    @Slot(int)
    def stageDpiDefault(self, index):
        """Queue which stage is the active (boot) DPI."""
        if 0 <= index < 5:
            self._pending_sensor['dpi_default'] = int(index)
            self.pendingChanged.emit()

    @Slot(int)
    def stageDpiShift(self, index):
        """Queue which stage the Sniper (shift-DPI) button uses."""
        if 0 <= index < 5:
            self._pending_sensor['dpi_shift'] = int(index)
            self.pendingChanged.emit()

    @Slot(int)
    def stageReportRate(self, hz):
        """Queue the report rate (Hz)."""
        if hz in REPORT_RATES:
            self._pending_sensor['report_rate'] = int(hz)
            self.pendingChanged.emit()

    @Slot()
    def apply(self):
        """Write every staged change (button banks + sensor header + macros) to the
        active profile in ONE gated, read-back-verified write (off-thread). Macro
        bytecode is written to a free sector first, then the profile once."""
        if self._busy or not (self._pending or self._pending_sensor or self._pending_macros):
            return
        self._busy = True
        self.busyChanged.emit()
        self._apply_status = 'Applying…'
        self.applyStatusChanged.emit()
        snapshot = dict(self._pending)               # {'<layer>:<button>': spec}
        sensor_snapshot = dict(self._pending_sensor)
        macro_snapshot = dict(self._pending_macros)  # {button:int -> macrodef}
        threading.Thread(target=self._apply_worker,
                         args=(snapshot, sensor_snapshot, macro_snapshot,
                               self._selected), daemon=True).start()

    def _apply_worker(self, snapshot, sensor_snapshot, macro_snapshot, target):
        try:
            button_changes, gshift_changes = {}, {}
            for key, spec in snapshot.items():
                layer, _, idx = key.partition(':')
                b = logi_config.binding_from_spec(spec)
                (gshift_changes if layer == 'gshift' else button_changes)[int(idx)] = b
        except ValueError as e:
            self._applyDone.emit(False, f'unsupported target: {e}', {})
            return
        sensor, dpi = {}, {}
        for k, v in sensor_snapshot.items():
            if k.startswith('dpi:'):
                dpi[int(k[4:])] = int(v)
            elif k in ('dpi_default', 'dpi_shift'):
                sensor[k] = int(v)
            elif k == 'report_rate':
                sensor['report_rate_hz'] = int(v)
        if dpi:
            sensor['dpi'] = dpi
        macro_changes = {int(b): m for b, m in macro_snapshot.items()}
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._applyDone.emit(False, 'mouse not accessible — connected and permitted?', {})
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    # edits go to the profile the user picked, which is NOT always
                    # the one the mouse is currently running
                    active = target or dev.current_profile()
                    active_hdr = [h for h in headers if h[0] == active] or [(active, 1)]
                    ok, msg = logi_config.apply_edits(
                        dev, info, headers, active,
                        button_changes=button_changes, gshift_changes=gshift_changes,
                        sensor=sensor, macro_changes=macro_changes, backup_headers=active_hdr)
                    binds = self._read_both(dev, active, info['sector_size']) if ok else {}
                    # macro slots may have changed; refresh the count for the editor
                    free = len(logi_config.free_macro_sectors(dev, info, headers)) if ok else -1
                self._applyDone.emit(ok, msg, binds)
                if ok:
                    self._macroSlotsDone.emit(free)
            except Exception as e:
                self._applyDone.emit(False, f'error: {e}', {})

    def _on_apply(self, ok, status, binds):
        self._busy = False
        self.busyChanged.emit()
        self._status = status
        self.statusChanged.emit()
        self._apply_status = ('✓ ' if ok else '⚠ ') + status
        self.applyStatusChanged.emit()
        if ok:
            self._pending = {}                       # committed -> clear the queue
            self._pending_sensor = {}
            self._pending_macros = {}
            self.pendingChanged.emit()
            if binds:
                self._set_binds(binds)
