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

import os
import sys
import threading

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

_LOGI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendors', 'logitech')
if _LOGI not in sys.path:
    sys.path.insert(0, _LOGI)
import hidpp                     # noqa: E402
import config as logi_config     # noqa: E402  (vendors/logitech/config.py)


class MouseBridge(QObject):
    presenceChanged = Signal()   # present / permission / activeProfile changed
    bindingsChanged = Signal()   # the per-button binding map changed
    statusChanged = Signal()     # last action result text changed
    busyChanged = Signal()       # a device write is in flight
    pendingChanged = Signal()    # the staged (unsaved) change set changed

    # Private carriers from the worker thread back to the GUI thread. Emitting a
    # signal from another thread to this (GUI-thread) object is delivered as a
    # queued connection, so the handlers run on the GUI thread and it's safe to
    # touch the exposed state there.
    _refreshDone = Signal(bool, str, int, int, int, bool, 'QVariantMap')  # present, perm, active, count, battery, wireless, binds
    _remapDone = Signal(bool, str, 'QVariantMap')               # ok, status, binds
    _applyDone = Signal(bool, str, 'QVariantMap')               # ok, status, binds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._present = False
        self._permission = 'unknown'    # ok | no-access | absent | unknown
        self._bindings = {}             # {str(button_index): "label"}
        self._active = 0
        self._button_count = 0
        self._battery = -1              # state-of-charge %, -1 = unknown
        self._wireless = False
        self._status = ''
        self._busy = False
        self._pending = {}              # {int button: str spec} — staged, unsaved
        self._io = threading.Lock()     # serialize device access (worker threads)

        self._refreshDone.connect(self._on_refresh)
        self._remapDone.connect(self._on_remap)
        self._applyDone.connect(self._on_apply)

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
    def _labels(dev, active, size):
        raw = logi_config.profile_bindings(dev, active, size)
        return {str(i): (b['label'] or b['kind']) for i, b in raw.items()}

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

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(int, notify=pendingChanged)
    def pendingCount(self):
        return len(self._pending)

    @Property('QVariantMap', notify=pendingChanged)
    def pending(self):
        """Staged (unsaved) targets, as {str(button): label} for the UI to preview."""
        out = {}
        for b, spec in self._pending.items():
            try:
                out[str(b)] = logi_config.friendly_binding(logi_config.binding_from_spec(spec))
            except Exception:
                out[str(b)] = spec
        return out

    # ------------------------------------------------------------- worker thread
    def _refresh_worker(self):
        with self._io:
            pid = self._node_pid()
            wireless = pid is not None and pid != 0xC098
            dev = hidpp.find_device()
            if dev is None:
                perm = 'no-access' if pid is not None else 'absent'
                self._refreshDone.emit(False, perm, 0, 0, -1, wireless, {})
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    active = dev.current_profile()
                    binds = self._labels(dev, active, info['sector_size'])
                    bat = getattr(dev, 'battery', lambda: None)()
                pct = bat['percent'] if bat else -1
                self._refreshDone.emit(True, 'ok', active, info['button_count'], pct, wireless, binds)
            except Exception as e:
                self._refreshDone.emit(False, f'read error: {e}', 0, 0, -1, wireless, {})

    def _remap_worker(self, button, spec):
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
                    active = dev.current_profile()
                    active_hdr = [h for h in headers if h[0] == active] or [(active, 1)]
                    ok, msg = logi_config.apply_binding(
                        dev, info, headers, active, button, binding,
                        backup_headers=active_hdr)          # back up only the edited profile
                    binds = self._labels(dev, active, info['sector_size']) if ok else {}
                self._remapDone.emit(ok, msg, binds)
            except Exception as e:
                self._remapDone.emit(False, f'error: {e}', {})

    # ------------------------------------------------- GUI-thread result handlers
    def _on_refresh(self, present, perm, active, count, battery, wireless, binds):
        self._permission = perm
        self._present = present
        self._active = active
        self._button_count = count
        self._battery = battery
        self._wireless = wireless
        if present:
            self._bindings = binds
        elif self._pending:
            self._pending = {}          # device gone -> staged edits are stale
            self.pendingChanged.emit()
        self.presenceChanged.emit()
        if present:
            self.bindingsChanged.emit()

    def _on_remap(self, ok, status, binds):
        self._busy = False
        self.busyChanged.emit()
        self._status = status
        self.statusChanged.emit()
        if ok and binds:
            self._bindings = binds
            self.bindingsChanged.emit()

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
        threading.Thread(target=self._remap_worker, args=(button, spec), daemon=True).start()

    # ------------------------------------------------- staged (batched) editing
    @Slot(int, str)
    def stage(self, button, spec):
        """Queue a binding change for `button` (no device I/O). Validates the spec
        now so a bad target is rejected before Apply. Call apply() to write them all
        in one profile write."""
        try:
            logi_config.binding_from_spec(spec)      # validate only
        except ValueError as e:
            self._set_status(f'unsupported target: {e}')
            return
        self._pending[int(button)] = spec
        self.pendingChanged.emit()

    @Slot(int)
    def unstage(self, button):
        """Drop a single staged change."""
        if self._pending.pop(int(button), None) is not None:
            self.pendingChanged.emit()

    @Slot()
    def discard(self):
        """Drop all staged changes."""
        if self._pending:
            self._pending = {}
            self.pendingChanged.emit()

    @Slot()
    def apply(self):
        """Write every staged change to the active profile in ONE gated,
        read-back-verified write (off-thread)."""
        if self._busy or not self._pending:
            return
        self._busy = True
        self.busyChanged.emit()
        changes_spec = dict(self._pending)           # snapshot for the worker
        threading.Thread(target=self._apply_worker, args=(changes_spec,), daemon=True).start()

    def _apply_worker(self, changes_spec):
        try:
            changes = {int(b): logi_config.binding_from_spec(s)
                       for b, s in changes_spec.items()}
        except ValueError as e:
            self._applyDone.emit(False, f'unsupported target: {e}', {})
            return
        with self._io:
            dev = hidpp.find_device()
            if dev is None:
                self._applyDone.emit(False, 'mouse not accessible — connected and permitted?', {})
                return
            try:
                with dev:
                    info = dev.onboard_info()
                    headers = dev.profile_headers()
                    active = dev.current_profile()
                    active_hdr = [h for h in headers if h[0] == active] or [(active, 1)]
                    ok, msg = logi_config.apply_bindings(
                        dev, info, headers, active, changes, backup_headers=active_hdr)
                    binds = self._labels(dev, active, info['sector_size']) if ok else {}
                self._applyDone.emit(ok, msg, binds)
            except Exception as e:
                self._applyDone.emit(False, f'error: {e}', {})

    def _on_apply(self, ok, status, binds):
        self._busy = False
        self.busyChanged.emit()
        self._status = status
        self.statusChanged.emit()
        if ok:
            self._pending = {}                       # committed -> clear the queue
            self.pendingChanged.emit()
            if binds:
                self._bindings = binds
                self.bindingsChanged.emit()
