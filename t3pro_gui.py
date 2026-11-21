"""QML bridge for the original GameSir Tarantula Pro (dongle 3537:103e).

The pad speaks GameSir's SAPJoy command protocol (vendors/gamesir/models/t3pro),
not the register map the main GamesirBridge drives, so it gets its own small
device bridge beside it, the same way MouseBridge does for the G502 X.

Every change is written straight to the pad, saved, and read back. Device I/O
runs on one worker thread, so the UI never blocks on the dongle. The software
side (HOME + button macros, rumble gain) lives in ~/.config/t3pro/bridge.json,
which the t3pro-bridge service reloads by itself.
"""
import os
import queue
import sys
import threading
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from vendors.gamesir.models.t3pro import protocol as p

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import t3pro_macros as hm  # noqa: E402

MODE_NAMES = ['off', 'solid', 'breathing', 'phantom', 'streamer', 'radar']
ZONES = [  # (wire id, label, led count)
    (0x05, 'A / B / X / Y', 4),
    (0x00, 'Home', 1),
    (0x04, 'Bar', 1),
    (0x06, 'Swapped layout (BAYX)', 4),
]
STEP_BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'L3', 'R3', 'VIEW', 'MENU',
                'UP', 'DOWN', 'LEFT', 'RIGHT']


def _hex(h, s, v):
    from colorsys import hsv_to_rgb
    r, g, b = hsv_to_rgb(h / 255.0, s / 100.0, v / 100.0)
    return '#%02x%02x%02x' % (round(r * 255), round(g * 255), round(b * 255))


class T3ProBridge(QObject):
    presenceChanged = Signal()
    stateChanged = Signal()
    busyChanged = Signal()
    message = Signal(str, bool)          # text, is_error
    _done = Signal(object)               # worker -> main thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._present = False
        self._busy = False
        self._info = {}
        self._light = {'mode': 0, 'brightness': 0, 'speed': 0}
        self._zones = {}                 # wire id -> [(h,s,v)...]
        self._macros = {}                # key -> {'steps': [...], 'hold': bool}
        self._vib = [0, 0]
        self._pending = 0                # jobs queued or running (main thread only)
        self._jobs = queue.Queue()
        self._done.connect(self._on_done)
        threading.Thread(target=self._worker, daemon=True).start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)
        QTimer.singleShot(0, self._poll)

    # ---------------------------------------------------------------- worker
    def _worker(self):
        while True:
            fn, ok_msg = self._jobs.get()
            result = {'ok_msg': ok_msg}
            try:
                with p.Tarantula(timeout=0.4) as t:
                    result.update(fn(t) or {})
            except (p.ProtocolError, OSError) as e:
                result['error'] = str(e)
            self._done.emit(result)

    def _submit(self, fn, ok_msg=''):
        self._pending += 1
        self._set_busy(True)
        self._jobs.put((fn, ok_msg))

    def _set_busy(self, b):
        if b != self._busy:
            self._busy = b
            self.busyChanged.emit()

    @Slot(object)
    def _on_done(self, r):
        self._pending = max(0, self._pending - 1)
        self._set_busy(self._pending > 0)
        if 'state' in r:
            st = r['state']
            self._info = st.get('info', self._info)
            self._light = st.get('light', self._light)
            self._zones.update(st.get('zones', {}))
            self._macros.update(st.get('macros', {}))
            self._vib = st.get('vib', self._vib)
            self.stateChanged.emit()
        if 'error' in r:
            self.message.emit(r['error'], True)
        elif r.get('mismatch'):
            self.message.emit(r['mismatch'], True)
        elif r.get('ok_msg'):
            self.message.emit(r['ok_msg'], False)

    # ---------------------------------------------------------------- reads
    @staticmethod
    def _read_macro(t, key):
        steps = []
        for i in range(p.MACRO_MAX_STEPS):
            s = t.get_macro_step(key, i)
            if len(s) < 16 or s[6] == p.MAP_VACANT:
                break
            steps.append({'button': p.KEY_NAMES.get(s[8], str(s[8])),
                          'start': s[12] << 8 | s[13], 'end': s[14] << 8 | s[15],
                          'trigger': s[2], 'loop': s[3]})
        mapping = t.get_key_mapping(key)
        vacant = len(mapping) > 10 and mapping[10] == p.MAP_VACANT
        out = []
        for i, s in enumerate(steps):
            nxt = steps[i + 1]['start'] if i + 1 < len(steps) else s['end']
            out.append({'button': s['button'], 'hold': max(10, s['end'] - s['start']),
                        'delay': max(0, nxt - s['end'])})
        return {'steps': out if vacant else [], 'hold': bool(steps) and steps[0]['trigger'] == 2,
                'active': vacant and bool(steps)}

    def _read_all(self, t):
        info = t.device_info()
        lp = t.get_light_param()
        zones = {z: t.get_light_color(z) for z, _, _ in ZONES}
        macros = {k: self._read_macro(t, k) for k in p.MACRO_KEYS}
        return {'state': {'info': info, 'light': lp, 'zones': zones, 'macros': macros,
                          'vib': list(t.get_vibrate_level())}}

    def _poll(self):
        present = p.find_hidraw() is not None
        if present != self._present:
            self._present = present
            self.presenceChanged.emit()
            if present:
                self._submit(self._read_all)
            else:
                self._info = {}
                self.stateChanged.emit()

    # ---------------------------------------------------------------- properties
    @Property(bool, notify=presenceChanged)
    def present(self):
        return self._present

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(int, notify=stateChanged)
    def battery(self):
        return int(self._info.get('battery') or -1) if self._info else -1

    @Property(str, notify=stateChanged)
    def firmware(self):
        return self._info.get('firmware', '')

    @Property(list, constant=True)
    def modeNames(self):
        return MODE_NAMES

    @Property(int, notify=stateChanged)
    def lightMode(self):
        return self._light.get('mode', 0)

    @Property(int, notify=stateChanged)
    def brightness(self):
        return self._light.get('brightness', 0)

    @Property(int, notify=stateChanged)
    def speed(self):
        return self._light.get('speed', 0)

    @Property(list, notify=stateChanged)
    def zones(self):
        out = []
        for z, label, n in ZONES:
            leds = self._zones.get(z, [(0, 0, 0)] * 4)[:n]
            out.append({'id': z, 'label': label,
                        'leds': [{'h': h, 's': s, 'v': v, 'hex': _hex(h, s, v)} for h, s, v in leds]})
        return out

    @Property(list, constant=True)
    def macroKeys(self):
        return list(p.MACRO_KEYS)

    @Property(list, constant=True)
    def stepButtons(self):
        return STEP_BUTTONS

    @Property('QVariantMap', notify=stateChanged)
    def macros(self):
        return self._macros

    @Property(int, notify=stateChanged)
    def vibLeft(self):
        return self._vib[0]

    @Property(int, notify=stateChanged)
    def vibRight(self):
        return self._vib[1]

    # software side (no pad I/O)
    @Property(float, notify=stateChanged)
    def rumbleGain(self):
        return float(hm.load_config().get('rumble_gain', 1.0))

    @Property(list, constant=True)
    def chordKeys(self):
        return list(hm.CHORD_KEYS)

    @Property(list, notify=stateChanged)
    def homeMacros(self):
        out = []
        for k, m in sorted(hm.load_config().get('home_macros', {}).items()):
            steps = m.get('steps', []) if isinstance(m, dict) else m
            out.append({'button': k, 'name': m.get('name', '') if isinstance(m, dict) else '',
                        'steps': [{'kind': 'key' if s.get('keys') else 'pad',
                                   'names': '+'.join(x.replace('KEY_', '') for x in
                                                     (s.get('keys') or s.get('pad', []))),
                                   'hold': int(s.get('hold', 60)), 'delay': int(s.get('delay', 40))}
                                  for s in steps]})
        return out

    @Property(bool, notify=stateChanged)
    def bridgeRunning(self):
        return os.system('systemctl --user -q is-active t3pro-bridge') == 0

    # ---------------------------------------------------------------- slots
    @Slot()
    def refresh(self):
        if self._present:
            self._submit(self._read_all)

    @Slot(int, int, int)
    def setLight(self, mode, brightness, speed):
        want = {'brightness': max(0, min(100, brightness)), 'speed': max(0, min(100, speed)),
                'mode': max(0, min(5, mode))}

        def job(t):
            t.set_light_param(**want)
            t.save()
            time.sleep(0.15)
            got = t.get_light_param()
            r = {'state': {'light': got}}
            if got != want:
                r['mismatch'] = f'Lights: the pad kept {got}'
            return r
        self._light = dict(want)
        self.stateChanged.emit()
        self._submit(job, 'Lights saved')

    @Slot(int, int, int, int, int)
    def setLed(self, zone, index, h, s, v):
        """index -1 = every LED of the zone."""
        n = next((c for z, _, c in ZONES if z == zone), 4)
        cur = list(self._zones.get(zone, [(0, 0, 0)] * 4))
        cur += [(0, 0, 0)] * (4 - len(cur))
        hsv = (max(0, min(255, h)), max(0, min(100, s)), max(0, min(100, v)))
        for i in (range(n) if index < 0 else [index]):
            cur[i] = hsv
        self._zones[zone] = cur
        self.stateChanged.emit()

        def job(t):
            t.set_light_color(zone, cur[:4])
            t.save()
            time.sleep(0.15)
            got = t.get_light_color(zone)
            r = {'state': {'zones': {zone: got}}}
            if not all(abs(g[0] - w[0]) <= 2 and g[1:] == w[1:] for g, w in zip(got[:n], cur[:n])):
                r['mismatch'] = 'Colour: the pad stored something else'
            return r
        self._submit(job, 'Colour saved')

    @Slot(str, list, bool)
    def setMacro(self, key, steps, hold):
        """steps: [{button, hold, delay}] as the UI edits them."""
        if key not in p.MACRO_KEYS:
            return
        seq, t0 = [], 0
        for s in steps[:p.MACRO_MAX_STEPS]:
            h = max(10, int(s.get('hold', 60)))
            seq.append((s.get('button', 'A'), t0, t0 + h))
            t0 += h + max(0, int(s.get('delay', 40)))

        def job(t):
            if seq:
                t.set_macro(key, seq, hold_to_trigger=hold)
            else:
                t.clear_macro(key)
            t.save()
            time.sleep(0.15)
            got = self._read_macro(t, key)
            r = {'state': {'macros': {key: got}}}
            if len(got['steps']) != len(seq):
                r['mismatch'] = f'Macro {key}: read back {len(got["steps"])} steps'
            return r
        self._submit(job, f'Macro on {key} saved' if seq else f'Macro on {key} cleared')

    @Slot(str)
    def clearMacro(self, key):
        self.setMacro(key, [], False)

    @Slot(int, int)
    def setVibration(self, left, right):
        want = (max(0, min(100, left)), max(0, min(100, right)))
        self._vib = list(want)
        self.stateChanged.emit()

        def job(t):
            t.set_vibrate_level(*want)
            t.save()
            time.sleep(0.15)
            got = t.get_vibrate_level()
            r = {'state': {'vib': list(got)}}
            if tuple(got) != want:
                r['mismatch'] = f'Vibration: the pad kept {got}'
            return r
        self._submit(job, 'Vibration level saved')

    @Slot()
    def testRumble(self):
        def job(t):
            t.vibrate_test(200, 200)
            time.sleep(0.6)
            t.vibrate_test(0, 0)
        self._submit(job)

    @Slot(float)
    def setRumbleGain(self, g):
        cfg = hm.load_config()
        cfg['rumble_gain'] = round(max(0.0, min(2.0, g)), 2)
        hm.save_config(cfg)
        self.stateChanged.emit()

    @Slot(str, str, list)
    def setHomeMacro(self, button, name, steps):
        """steps: [{kind: 'pad'|'key', names: 'A+B' / 'LEFTCTRL+2', hold, delay}]"""
        out = []
        for s in steps:
            names = [n.strip().upper() for n in str(s.get('names', '')).split('+') if n.strip()]
            st = {'hold': int(s.get('hold', 60)), 'delay': int(s.get('delay', 40))}
            if s.get('kind') == 'key':
                st['keys'] = [n if n.startswith('KEY_') else 'KEY_' + n for n in names]
            else:
                st['pad'] = names
            out.append(st)
        try:
            hm.validate_steps(out)
        except ValueError as e:
            self.message.emit(str(e), True)
            return
        cfg = hm.load_config()
        cfg.setdefault('home_macros', {})[button.upper()] = {'name': name, 'steps': out}
        hm.save_config(cfg)
        self.stateChanged.emit()
        self.message.emit(f'HOME+{button.upper()} saved', False)

    @Slot(str)
    def removeHomeMacro(self, button):
        cfg = hm.load_config()
        cfg.get('home_macros', {}).pop(button.upper(), None)
        hm.save_config(cfg)
        self.stateChanged.emit()
        self.message.emit(f'HOME+{button.upper()} removed', False)
