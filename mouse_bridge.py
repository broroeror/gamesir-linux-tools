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

Runs as the logged-in user; hidraw write access comes from the udev rule in
packaging/udev (no sudo). Until that rule is installed the device shows up but
isn't openable, which we surface as permission == "no-access".
"""

import os
import sys

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._present = False
        self._permission = 'unknown'    # ok | no-access | absent | unknown
        self._bindings = {}             # {str(button_index): "label"}
        self._active = 0
        self._button_count = 0
        self._status = ''
        # light hotplug poll: enumerate (no open) every few seconds; a full read
        # happens only on a connect transition or an explicit refresh().
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self.refresh()

    # ------------------------------------------------------------------ probing
    def _node_present(self):
        """True if a G502 X hidraw node is enumerable (does NOT need open access)."""
        try:
            import hid
            for d in hid.enumerate():
                if d.get('vendor_id') == hidpp.LOGITECH_VID and \
                        d.get('product_id') in hidpp.G502X_PIDS:
                    return True
        except Exception:
            pass
        return False

    def _open(self):
        """Open the G502 X (returns an open Hidpp) or None, updating _permission.
        find_device returns None on BOTH absent and permission-denied (it swallows
        the open error), so we disambiguate with an enumerate probe."""
        dev = hidpp.find_device()
        if dev is None:
            self._permission = 'no-access' if self._node_present() else 'absent'
            return None
        self._permission = 'ok'
        return dev

    def _poll(self):
        node = self._node_present()
        if node and not self._present:
            self.refresh()                       # just connected -> read it
        elif not node and self._present:
            self._present = False
            self._permission = 'absent'
            self.presenceChanged.emit()

    def _labels(self, dev, size):
        raw = logi_config.profile_bindings(dev, self._active, size)
        return {str(i): (b['detail'] or b['kind']) for i, b in raw.items()}

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

    @Property('QVariantMap', notify=bindingsChanged)
    def bindings(self):
        return self._bindings

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    def _set_status(self, s):
        self._status = s
        self.statusChanged.emit()

    # -------------------------------------------------------------------- slots
    @Slot()
    def refresh(self):
        """Detect the device and read the active profile's bindings."""
        dev = self._open()
        if dev is None:
            if self._present:
                self._present = False
                self.presenceChanged.emit()
            else:
                self.presenceChanged.emit()      # permission/absent may have changed
            return
        try:
            with dev:
                info = dev.onboard_info()
                self._active = dev.current_profile()
                self._button_count = info['button_count']
                self._bindings = self._labels(dev, info['sector_size'])
            self._present = True
            self.presenceChanged.emit()
            self.bindingsChanged.emit()
        except Exception as e:
            self._set_status(f'read error: {e}')
            if self._present:
                self._present = False
                self.presenceChanged.emit()

    @Slot(int, str)
    def remap(self, button, spec):
        """Apply a binding to `button` on the active profile. spec vocabulary:
        key:<char|name> | mouse:<n> | sniper | dpi-up | dpi-down | dpi-cycle |
        disabled."""
        try:
            binding = logi_config.binding_from_spec(spec)
        except ValueError as e:
            self._set_status(f'unsupported target: {e}')
            return
        dev = self._open()
        if dev is None:
            self._set_status('mouse not accessible — is it connected and permitted?')
            return
        try:
            with dev:
                info = dev.onboard_info()
                headers = dev.profile_headers()
                active = dev.current_profile()
                ok, msg = logi_config.apply_binding(
                    dev, info, headers, active, button, binding)
                self._set_status(msg)
                if ok:
                    self._active = active
                    self._bindings = self._labels(dev, info['sector_size'])
                    self.bindingsChanged.emit()
        except Exception as e:
            self._set_status(f'error: {e}')
