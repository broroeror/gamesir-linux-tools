"""Software macros for the Tarantula Pro bridge: HOME + <button> chords.

Config (~/.config/t3pro/bridge.json):

    {"home_macros": {
        "A": {"name": "Steam quick access", "steps": [
            {"keys": ["KEY_LEFTCTRL", "KEY_2"], "hold": 80}]},
        "B": {"steps": [{"pad": ["X"], "hold": 60, "delay": 120},
                        {"pad": ["Y"], "hold": 60}]}
    }}

A step presses `pad` buttons (sent through the virtual DS4, HOME included),
`keys` (evdev KEY_* names, virtual keyboard) and/or `mouse` (LEFT RIGHT
MIDDLE SIDE EXTRA WHEEL_UP WHEEL_DOWN, virtual mouse) for `hold` ms, then
waits `delay` ms (default 40) before the next step.

"button_macros" has the same shape but fires on a back button alone (no
HOME): handy to make one back button do what HOME + A does. A back button
mapped to itself sends nothing, so the GUI maps it on the pad to a signal key
(L4 -> F13 ... T3 -> F21, see protocol.SIGNAL_KEYS) and the bridge watches the
dongle's keyboard for that key (trigger_solo).

Behaviour:
* HOME + a button that has a macro runs the macro. Neither HOME nor that
  button reaches the host, so Steam's own HOME chords don't fire too.
* HOME alone is delivered as a tap when released, so a tap opens Steam and a
  double tap opens Big Picture as before. HOME held for more than HOLD_PASS
  seconds without a chord passes straight through.
"""
import json
import os
import time

PAD_BITS = {
    'B': (6, 0), 'A': (6, 1), 'Y': (6, 2), 'X': (6, 3), 'LB': (6, 4), 'LT': (6, 5),
    'L3': (6, 6), 'RB': (6, 7), 'RT': (7, 0), 'R3': (7, 1), 'VIEW': (7, 2), 'MENU': (7, 3),
    'LEFT': (7, 4), 'RIGHT': (7, 5), 'UP': (7, 6), 'DOWN': (7, 7),
    'HOME': (8, 0), 'CAMERA': (8, 1), 'M': (8, 2),
    'L4': (9, 0), 'R4': (9, 1), 'T1': (9, 2), 'T2': (9, 3), 'T3': (9, 4),
    'C1': (9, 5), 'C2': (9, 6), 'C3': (9, 7), 'C4': (10, 0),
}
ANALOG = {'LT': 4, 'RT': 5}
CHORD_KEYS = tuple(k for k in PAD_BITS if k not in ('HOME', 'M'))
HOLD_PASS = 0.4
HOME_TAP = 0.08
CONFIG = os.path.expanduser('~/.config/t3pro/bridge.json')
MOUSE_NAMES = ('LEFT', 'RIGHT', 'MIDDLE', 'SIDE', 'EXTRA', 'WHEEL_UP', 'WHEEL_DOWN')


def load_config(path=CONFIG):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg, path=CONFIG):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def validate_steps(steps):
    from evdev import ecodes
    for s in steps:
        for b in s.get('pad', []):
            if b not in PAD_BITS:
                raise ValueError(f'unknown pad button {b!r} (use {", ".join(PAD_BITS)})')
        for k in s.get('keys', []):
            if k not in ecodes.ecodes:
                raise ValueError(f'unknown key {k!r} (use evdev names like KEY_LEFTCTRL)')
        for m in s.get('mouse', []):
            if m not in MOUSE_NAMES:
                raise ValueError(f'unknown mouse output {m!r} (use {", ".join(MOUSE_NAMES)})')
        if not s.get('pad') and not s.get('keys') and not s.get('mouse'):
            raise ValueError('a step needs "pad", "keys" and/or "mouse"')


class HomeChords:
    def __init__(self, path=CONFIG, log=print):
        self.path = path
        self.log = log
        self.macros = {}
        self.solo = {}               # button alone -> steps
        self._mtime = None
        self._checked = 0.0
        self.reload(force=True)
        self.phase = 'idle'          # idle | pending | pass
        self.t_home = 0.0
        self.chord_used = False
        self.prev = set()
        self.suppressed = set()
        self.forced = {}             # pad button -> refcount
        self.events = []             # (t, action, payload)
        self._kbd = None
        self._mouse = None

    # -- config ---------------------------------------------------------------
    def reload(self, force=False):
        now = time.monotonic()
        if not force and now - self._checked < 1.0:
            return
        self._checked = now
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            mtime = None
        if not force and mtime == self._mtime:
            return
        self._mtime = mtime
        macros = {}
        cfg = load_config(self.path)
        try:
            self.gain = max(0.0, min(2.0, float(cfg.get('rumble_gain', 1.0))))
        except (TypeError, ValueError):
            self.gain = 1.0
        solo = {}
        for section, dest in (('home_macros', macros), ('button_macros', solo)):
            for key, m in cfg.get(section, {}).items():
                steps = m.get('steps', []) if isinstance(m, dict) else m
                try:
                    validate_steps(steps)
                except (ValueError, ImportError) as e:
                    self.log(f'{section} {key}: ignored ({e})')
                    continue
                if key in CHORD_KEYS and steps:
                    dest[key] = steps
        self.macros, self.solo = macros, solo
        self.log(f'home macros: {", ".join(sorted(macros)) or "none"}; '
                 f'button macros: {", ".join(sorted(solo)) or "none"}')

    # -- keyboard -------------------------------------------------------------
    def kbd(self):
        if self._kbd is None:
            from evdev import UInput, ecodes
            # real key codes only: KEY_MAX / KEY_CNT are bounds, not keys (EINVAL)
            keys = sorted({v for k, v in ecodes.ecodes.items()
                           if k.startswith('KEY_') and 0 < v < ecodes.KEY_MAX and k not in ('KEY_MAX', 'KEY_CNT')})
            self._kbd = UInput({ecodes.EV_KEY: keys}, name='t3pro macro keyboard')
        return self._kbd

    def mouse(self):
        if self._mouse is None:
            from evdev import UInput, ecodes as E
            self._mouse = UInput({E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT, E.BTN_MIDDLE, E.BTN_SIDE, E.BTN_EXTRA],
                                  E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL]},
                                 name='t3pro macro mouse')
        return self._mouse

    def close(self):
        for dev in (self._kbd, self._mouse):
            if dev is not None:
                dev.close()

    # -- scheduling -----------------------------------------------------------
    def _schedule(self, steps, t):
        for s in steps:
            hold = max(10, int(s.get('hold', 60))) / 1000
            delay = max(0, int(s.get('delay', 40))) / 1000
            self.events.append((t, 'down', s))
            self.events.append((t + hold, 'up', s))
            t += hold + delay
        self.events.sort(key=lambda ev: ev[0])

    def busy(self):
        return bool(self.events)

    def tick(self, now):
        """Run due events. Returns True if the forced pad state changed."""
        changed = False
        while self.events and self.events[0][0] <= now:
            _, action, s = self.events.pop(0)
            for b in s.get('pad', []):
                if action == 'down':
                    self.forced[b] = self.forced.get(b, 0) + 1
                else:
                    self.forced[b] = self.forced.get(b, 1) - 1
                    if self.forced[b] <= 0:
                        del self.forced[b]
                changed = True
            if s.get('keys'):
                from evdev import ecodes
                kb = self.kbd()
                seq = s['keys'] if action == 'down' else list(reversed(s['keys']))
                for k in seq:
                    kb.write(ecodes.EV_KEY, ecodes.ecodes[k], 1 if action == 'down' else 0)
                kb.syn()
            if s.get('mouse'):
                from evdev import ecodes as E
                ms = self.mouse()
                for m in s['mouse']:
                    if m == 'WHEEL_UP' and action == 'down':
                        ms.write(E.EV_REL, E.REL_WHEEL, 1)
                    elif m == 'WHEEL_DOWN' and action == 'down':
                        ms.write(E.EV_REL, E.REL_WHEEL, -1)
                    elif not m.startswith('WHEEL'):
                        ms.write(E.EV_KEY, getattr(E, 'BTN_' + m), 1 if action == 'down' else 0)
                ms.syn()
        return changed

    # -- per-frame ------------------------------------------------------------
    @staticmethod
    def pressed(e):
        return {n for n, (i, b) in PAD_BITS.items() if e[i] >> b & 1}

    def feed(self, e, now):
        """Edge logic for a new pad frame."""
        self.reload()
        cur = self.pressed(e)
        home = 'HOME' in cur
        if home and self.phase == 'idle':
            self.phase, self.t_home, self.chord_used = 'pending', now, False
        if self.phase == 'pending':
            for name in (cur - self.prev):
                if name in self.macros:
                    self.chord_used = True
                    self.suppressed.add(name)
                    self.log(f'macro HOME+{name}')
                    self._schedule(self.macros[name], now)
            if home and not self.chord_used and now - self.t_home > HOLD_PASS:
                self.phase = 'pass'
            if not home:
                if not self.chord_used:
                    self._schedule([{'pad': ['HOME'], 'hold': int(HOME_TAP * 1000), 'delay': 0}], now)
                self.phase = 'idle'
        elif self.phase == 'pass' and not home:
            self.phase = 'idle'
        self.suppressed &= cur
        self.prev = cur

    def trigger_solo(self, name, now):
        """A back button's signal key arrived from the dongle keyboard."""
        self.reload()
        if name in self.solo:
            self.log(f'macro {name}')
            self._schedule(self.solo[name], now)

    def render(self, e):
        """Pad frame as the host should see it."""
        out = bytearray(e)
        hide = set(self.suppressed)
        if self.phase == 'pending':
            hide.add('HOME')
        for name in hide:
            i, b = PAD_BITS[name]
            out[i] &= ~(1 << b) & 0xFF
            if name in ANALOG:
                out[ANALOG[name]] = 0
        for name in self.forced:
            i, b = PAD_BITS[name]
            out[i] |= 1 << b
            if name in ANALOG:
                out[ANALOG[name]] = 255
        return bytes(out)
