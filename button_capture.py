"""Optional button-edge capture before the GUI's 60 Hz sampling."""
from collections import deque
import threading
import time

from gs_state import state, EXTRA_BTNS

_lock = threading.Lock()
_events = deque(maxlen=4096)
_enabled = False
_last = {}
_scope = None
_overflow = False


def _buttons():
    values = {k: bool(state[k]) for k in
              ('a', 'b', 'x', 'y', 'lb', 'rb', 'ls', 'rs', 'view', 'menu') + EXTRA_BTNS}
    values.update({'dpad_' + k: k in state['dpad'].split('-')
                   for k in ('up', 'down', 'left', 'right')})
    # Hysteresis avoids counting analog jitter; 0/255 hard-stop reports use
    # the same path. Press at 10%, release below 5% of the reported range.
    values.update({k: state[k] > 12 if _last.get(k, False) else state[k] >= 26
                   for k in ('lt', 'rt')})
    return values


def _identity():
    return state.get('selected'), state.get('controller'), state.get('profile')


def enable(enabled):
    global _enabled, _last, _scope, _overflow
    with _lock:
        _enabled = bool(enabled)
        _last, _scope, _overflow = _buttons(), _identity(), False
        _events.clear()


def record(source, when=None):
    """Called once per input report/event. evdev supplies its event timestamp."""
    global _last, _scope, _overflow
    if not _enabled or source != state.get('selected'):
        return
    with _lock:
        if not _enabled:
            return
        current, identity = _buttons(), _identity()
        if identity != _scope:
            _last, _scope = current, identity
            _events.clear()
            return
        when = time.monotonic() * 1000 if when is None else when
        for key, down in current.items():
            if down != _last.get(key, False):
                _overflow |= len(_events) == _events.maxlen
                _events.append((key, down, when))
        _last = current


def drain():
    global _overflow
    with _lock:
        events, overflow = list(_events), _overflow
        _events.clear()
        _overflow = False
    return events, overflow
