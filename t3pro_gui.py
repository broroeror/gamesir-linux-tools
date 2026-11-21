"""QML bridge for the original GameSir Tarantula Pro (dongle 3537:103e).

The pad speaks GameSir's SAPJoy command protocol (vendors/gamesir/models/t3pro),
not the register map the main GamesirBridge drives, so it gets its own small
device bridge beside it, the same way MouseBridge does for the G502 X.

Every change is written straight to the pad, saved, and read back. Device I/O
runs on one worker thread, so the UI never blocks on the dongle. The software
side (HOME + button macros, rumble gain) lives in ~/.config/t3pro/bridge.json,
which the t3pro-bridge service reloads by itself.
"""
import json
import os
import queue
import sys
import threading
import time

from PySide6.QtCore import Property, QCoreApplication, QObject, QTimer, Signal, Slot

from vendors.gamesir.models.t3pro import protocol as p

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import t3pro_macros as hm  # noqa: E402

MODE_NAMES = ['Off', 'Solid', 'Breathing', 'Phantom', 'Streamer', 'Radar']
ZONES = [  # (wire id, label, led count)
    (p.ZONE_ABXY, 'A / B / X / Y', 4),
    (p.ZONE_HOME, 'Home', 1),
    (p.ZONE_BAR, 'Bar', 1),
    (p.ZONE_BAYX, 'Switch layout (BAYX)', 4),
]
PAD_TARGETS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'L3', 'R3', 'UP', 'DOWN', 'LEFT',
               'RIGHT', 'VIEW', 'MENU', 'CAMERA', 'L4', 'R4']
REMAP_KEYS = list(p.APP_KEYS)
BACKUP_DIR = os.path.expanduser('~/.local/share/t3pro')


def tr(text):
    return QCoreApplication.translate('UI', text)


def _hex(h, s, v):
    from colorsys import hsv_to_rgb
    r, g, b = hsv_to_rgb(h / 255.0, s / 100.0, v / 100.0)
    return '#%02x%02x%02x' % (round(r * 255), round(g * 255), round(b * 255))


class T3ProBridge(QObject):
    presenceChanged = Signal()
    stateChanged = Signal()
    busyChanged = Signal()
    recordingChanged = Signal()
    recorded = Signal(str, list)         # macro key, steps for the editor
    message = Signal(str, bool)          # text, is_error
    _done = Signal(object)               # worker -> main thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._present = False
        self._busy = False
        self._recording = ''
        self._rec_stop = threading.Event()
        self._info = {}
        self._light = {'mode': 0, 'brightness': 0, 'speed': 0}
        self._zones = {}                 # wire id -> [(h,s,v)...]
        self._macros = {}                # key -> {...}
        self._remaps = {}                # key -> {...}
        self._motion = {}
        self._layout = 1
        self._vib = [0, 0]
        self._pending = 0
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
        st = r.get('state')
        if st:
            self._info = st.get('info', self._info)
            self._light = st.get('light', self._light)
            self._zones.update(st.get('zones', {}))
            self._macros.update(st.get('macros', {}))
            self._remaps.update(st.get('remaps', {}))
            self._motion = st.get('motion', self._motion)
            self._layout = st.get('layout', self._layout)
            self._vib = st.get('vib', self._vib)
            self.stateChanged.emit()
        if 'recorded' in r:
            key, steps = r['recorded']
            self._recording = ''
            self.recordingChanged.emit()
            self.recorded.emit(key, steps)
        if 'error' in r:
            self.message.emit(r['error'], True)
        elif r.get('mismatch'):
            self.message.emit(r['mismatch'], True)
        elif r.get('ok_msg'):
            self.message.emit(tr(r['ok_msg']), False)

    # ---------------------------------------------------------------- reads
    @staticmethod
    def _macro_model(m, vacant):
        steps = m['steps']
        out = []
        for i, (kind, names, s, e) in enumerate(steps):
            nxt = steps[i + 1][2] if i + 1 < len(steps) else e
            out.append({'kind': kind, 'names': names, 'hold': max(10, e - s),
                        'delay': max(0, nxt - e)})
        active = vacant and bool(out)
        return {'steps': out if active else [], 'hold': m['hold'], 'loop': m['loop'],
                'loopTime': m['loop_time'], 'active': active}

    def _read_macro(self, t, key, remap=None):
        remap = remap or t.get_remap(key)
        return self._macro_model(t.get_macro(key), remap['vacant'])

    def _read_all(self, t):
        info = t.device_info()
        remaps = {k: t.get_remap(k) for k in REMAP_KEYS}
        st = {
            'info': info,
            'light': t.get_light_param(),
            'zones': {z: t.get_light_color(z) for z, _, _ in ZONES},
            'remaps': remaps,
            'macros': {k: self._read_macro(t, k, remaps[k]) for k in p.MACRO_KEYS},
            'motion': {k: v for k, v in t.get_motion().items() if k != '_curve_raw'},
            'layout': t.get_layout(),
            'vib': list(t.get_vibrate_level()),
        }
        return {'state': st}

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

    @Property(str, notify=recordingChanged)
    def recording(self):
        return self._recording

    @Property(int, notify=stateChanged)
    def battery(self):
        return int(self._info.get('battery') or -1) if self._info else -1

    @Property(str, notify=stateChanged)
    def firmware(self):
        return self._info.get('firmware', '')

    @Property(str, notify=stateChanged)
    def mac(self):
        return self._info.get('mac', '')

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

    @Property(int, notify=stateChanged)
    def layout(self):
        return self._layout

    @Property(list, notify=stateChanged)
    def zones(self):
        out = []
        for z, label, n in ZONES:
            leds = self._zones.get(z, [(0, 0, 0)] * 4)[:n]
            out.append({'id': z, 'label': label,
                        'leds': [{'h': h, 's': s, 'v': v, 'hex': _hex(h, s, v)} for h, s, v in leds]})
        return out

    @Property('QVariantMap', notify=stateChanged)
    def ledColors(self):
        """Colours for the drawing: A B X Y of the active layout, HOME, BAR."""
        def col(zone, i):
            leds = self._zones.get(zone) or []
            if i < len(leds):
                h, s, v = leds[i]
                return _hex(h, s, max(v, 35) if v else 0)   # dim LEDs still visible
            return '#000000'
        z = p.ZONE_BAYX if self._layout == 2 else p.ZONE_ABXY
        return {'A': col(z, 0), 'B': col(z, 1), 'X': col(z, 2), 'Y': col(z, 3),
                'HOME': col(p.ZONE_HOME, 0), 'BAR': col(p.ZONE_BAR, 0)}

    @Property(list, constant=True)
    def macroKeys(self):
        return list(p.MACRO_KEYS)

    @Property(list, constant=True)
    def remapKeys(self):
        return REMAP_KEYS

    @Property('QVariantMap', constant=True)
    def keyCodes(self):
        return {k: v for k, v in p.KEYS.items()}

    @Property(list, constant=True)
    def padTargets(self):
        return PAD_TARGETS

    @Property(list, constant=True)
    def kbKeys(self):
        return p.KB_MODS + list(p.KB_KEYS)

    @Property(list, constant=True)
    def mouseOutputs(self):
        return p.MOUSE_BUTTONS + list(p.MOUSE_WHEEL)

    @Property(list, constant=True)
    def mediaKeys(self):
        return p.MEDIA_KEYS

    @Property('QVariantMap', notify=stateChanged)
    def macros(self):
        return self._macros

    @Property('QVariantMap', notify=stateChanged)
    def remaps(self):
        return self._remaps

    @Property('QVariantMap', notify=stateChanged)
    def motion(self):
        return self._motion

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

    @Property(list, constant=True)
    def soloKeys(self):
        return list(p.SIGNAL_KEYS)

    @Property(list, notify=stateChanged)
    def homeMacros(self):
        """Software macros run by the bridge: mode 'chord' = HOME + button,
        mode 'button' = the button alone."""
        out = []
        cfg = hm.load_config()
        for mode, section in (('chord', 'home_macros'), ('button', 'button_macros')):
            for k, m in sorted(cfg.get(section, {}).items()):
                steps = m.get('steps', []) if isinstance(m, dict) else m
                rows = []
                for s in steps:
                    kind = 'key' if s.get('keys') else 'mouse' if s.get('mouse') else 'pad'
                    names = s.get('keys') or s.get('mouse') or s.get('pad', [])
                    rows.append({'kind': kind, 'names': '+'.join(x.replace('KEY_', '') for x in names),
                                 'hold': int(s.get('hold', 60)), 'delay': int(s.get('delay', 40))})
                out.append({'button': k, 'mode': mode,
                            'name': m.get('name', '') if isinstance(m, dict) else '', 'steps': rows})
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
                r['mismatch'] = tr('The pad kept different light settings')
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
                r['mismatch'] = tr('The pad stored a different colour')
            return r
        self._submit(job, 'Colour saved')

    @Slot(int)
    def setLayout(self, layout):
        def job(t):
            t.set_layout(layout)
            t.save()
            time.sleep(0.15)
            return {'state': {'layout': t.get_layout()}}
        self._layout = layout
        self.stateChanged.emit()
        self._submit(job, 'Button layout saved')

    @Slot()
    def restoreDefaultColors(self):
        def job(t):
            t.set_light_param(**p.DEFAULT_LIGHT)
            t.set_default_colors()
            t.save()
            time.sleep(0.15)
            return {'state': {'light': t.get_light_param(),
                              'zones': {z: t.get_light_color(z) for z, _, _ in ZONES}}}
        self._submit(job, 'Original colours restored')

    @Slot()
    def factoryReset(self):
        def job(t):
            data = t.dump()
            os.makedirs(BACKUP_DIR, exist_ok=True)
            path = os.path.join(BACKUP_DIR, f'backup-{time.strftime("%Y%m%d-%H%M%S")}-before-reset.json')
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            t.factory_defaults()
            time.sleep(0.2)
            return self._read_all(t)
        self._submit(job, 'Factory defaults restored (backup saved first)')

    @Slot(str, list, bool, bool, int)
    def setMacro(self, key, steps, hold, loop, loop_time):
        """steps: [{kind, names, hold, delay}] as the UI edits them."""
        if key not in p.MACRO_KEYS:
            return
        seq, t0 = [], 0
        for s in steps[:p.MACRO_MAX_STEPS]:
            names = [n for n in (s.get('names') or []) if n]
            if not names:
                continue
            h = max(10, int(s.get('hold', 60)))
            seq.append((s.get('kind', 'pad'), names, t0, t0 + h))
            t0 += h + max(0, int(s.get('delay', 40)))
        try:
            for kind, names, _, _ in seq:
                p.encode_output(kind, names)
        except p.ProtocolError as e:
            self.message.emit(str(e), True)
            return

        def job(t):
            if seq:
                t.set_macro(key, seq, hold_to_trigger=hold, loop=loop, loop_time_ms=loop_time)
            else:
                t.clear_macro(key)
            t.save()
            time.sleep(0.15)
            remap = t.get_remap(key)
            got = self._read_macro(t, key, remap)
            r = {'state': {'macros': {key: got}, 'remaps': {key: remap}}}
            if len(got['steps']) != len(seq):
                r['mismatch'] = tr('Macro read back with a different number of steps')
            return r
        self._submit(job, 'Macro saved' if seq else 'Macro cleared')

    @Slot(str)
    def clearMacro(self, key):
        self.setMacro(key, [], False, False, 0)

    @Slot(str, str, list, bool, int)
    def setRemap(self, key, kind, names, toggle, turbo):
        names = [n for n in names if n]
        try:
            if kind != 'pad' or names:
                p.encode_output(kind, names)
        except p.ProtocolError as e:
            self.message.emit(str(e), True)
            return

        def job(t):
            if key in p.MACRO_KEYS:
                t.request(0x01, 0x01, bytes([p.KEYS[key], 0xFF]) + bytes(14))
            t.set_key_mapping(key, names, toggle=toggle, turbo=turbo, kind=kind)
            t.save()
            time.sleep(0.15)
            got = t.get_remap(key)
            st = {'remaps': {key: got}}
            if key in p.MACRO_KEYS:
                st['macros'] = {key: self._read_macro(t, key, got)}
            return {'state': st}
        self._submit(job, 'Button saved')

    @Slot(str)
    def resetRemap(self, key):
        self.setRemap(key, 'pad', [p.DEFAULT_REMAP.get(key, key)], False, 0)

    @Slot('QVariantMap')
    def setMotion(self, m):
        want = dict(self._motion)
        want.update({k: m[k] for k in m})

        def job(t):
            cur = t.get_motion()
            cur.update({k: v for k, v in want.items() if k in cur and k != '_curve_raw'})
            t.set_motion(cur)
            t.save()
            time.sleep(0.15)
            return {'state': {'motion': {k: v for k, v in t.get_motion().items() if k != '_curve_raw'}}}
        self._motion = want
        self.stateChanged.emit()
        self._submit(job, 'Gyro settings saved')

    @Slot(int, int)
    def setVibration(self, left, right):
        # the pad stores 5 levels (0/25/50/75/100 %, GameSir Connect's "motor 0-4")
        snap = lambda v: max(0, min(100, int(round(v / 25.0)) * 25))  # noqa: E731
        want = (snap(left), snap(right))
        self._vib = list(want)
        self.stateChanged.emit()

        def job(t):
            t.set_vibrate_level(*want)
            t.save()
            time.sleep(0.15)
            got = t.get_vibrate_level()
            r = {'state': {'vib': list(got)}}
            if tuple(got) != want:
                r['mismatch'] = tr('The pad kept a different vibration level')
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

    # ---- recording a macro from the pad itself -----------------------------
    REC_BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'L3', 'R3', 'VIEW', 'MENU',
                   'UP', 'DOWN', 'LEFT', 'RIGHT']

    @Slot(str)
    def startRecord(self, key):
        if self._recording or not self._present:
            return
        self._recording = key
        self._rec_stop.clear()
        self.recordingChanged.emit()
        bits = {n: hm.PAD_BITS[n] for n in self.REC_BUTTONS}

        def job(t):
            own_stream = os.system('systemctl --user -q is-active t3pro-bridge') != 0
            if own_stream:
                t.set_gamepad_state_report(1)
            events, prev, t0 = [], set(), None
            end = time.time() + 30
            try:
                while time.time() < end and not self._rec_stop.is_set():
                    try:
                        r = os.read(t.fd, 64)
                    except BlockingIOError:
                        time.sleep(0.002)
                        continue
                    if r[:4] != bytes([6, 0x1A, 0x0A, 3]):
                        continue
                    e = r[4:]
                    if e[8] & 1:                      # HOME ends the recording
                        break
                    cur = {n for n, (i, b) in bits.items() if e[i] >> b & 1}
                    now = time.time()
                    if cur != prev:
                        if t0 is None:
                            t0 = now
                        events.append((int((now - t0) * 1000), frozenset(cur)))
                        prev = cur
            finally:
                if own_stream:
                    t.set_gamepad_state_report(0)
            # chords: each stretch with buttons down is one step
            steps, start, held = [], None, frozenset()
            for ms, cur in events + [(events[-1][0] + 1 if events else 0, frozenset())]:
                if held and cur != held:
                    steps.append({'kind': 'pad', 'names': sorted(held)[:4], 'start': start, 'end': ms})
                if cur and cur != held:
                    start = ms
                held = cur
            out = []
            for i, s in enumerate(steps[:p.MACRO_MAX_STEPS]):
                nxt = steps[i + 1]['start'] if i + 1 < len(steps) else s['end']
                out.append({'kind': 'pad', 'names': s['names'], 'hold': max(10, s['end'] - s['start']),
                            'delay': max(0, nxt - s['end'])})
            return {'recorded': (key, out)}
        self._submit(job, '')

    @Slot()
    def stopRecord(self):
        self._rec_stop.set()

    # ---- HOME + button shortcuts (bridge config) ---------------------------
    @Slot(str, str, list, str)
    def setHomeMacro(self, button, name, steps, mode):
        """steps: [{kind: 'pad'|'key'|'mouse', names: 'HOME+A' / 'LEFTCTRL+2' / 'LEFT', hold, delay}]"""
        out = []
        for s in steps:
            names = [n.strip().upper() for n in str(s.get('names', '')).split('+') if n.strip()]
            st = {'hold': int(s.get('hold', 60)), 'delay': int(s.get('delay', 40))}
            if s.get('kind') == 'key':
                st['keys'] = [n if n.startswith('KEY_') else 'KEY_' + n for n in names]
            elif s.get('kind') == 'mouse':
                st['mouse'] = names
            else:
                st['pad'] = names
            out.append(st)
        try:
            hm.validate_steps(out)
        except ValueError as e:
            self.message.emit(str(e), True)
            return
        button = button.upper()
        if mode == 'button' and button not in p.SIGNAL_KEYS:
            self.message.emit(tr('Only the back buttons (L4, R4, C1–C4, T1–T3) can fire a shortcut alone.'), True)
            return
        cfg = hm.load_config()
        section = 'button_macros' if mode == 'button' else 'home_macros'
        cfg.setdefault(section, {})[button] = {'name': name, 'steps': out}
        hm.save_config(cfg)
        self.stateChanged.emit()
        if mode != 'button':
            self.message.emit(tr('Shortcut saved'), False)
            return

        def job(t):          # the back button sends its signal key to the bridge
            t.request(0x01, 0x01, bytes([p.KEYS[button], 0xFF]) + bytes(14))
            t.set_key_mapping(button, [p.SIGNAL_KEYS[button]], kind='kb')
            t.save()
            time.sleep(0.15)
            remap = t.get_remap(button)
            return {'state': {'remaps': {button: remap},
                              'macros': {button: self._read_macro(t, button, remap)}}}
        self._submit(job, 'Shortcut saved')

    @Slot(str, str)
    def removeHomeMacro(self, button, mode):
        cfg = hm.load_config()
        cfg.get('button_macros' if mode == 'button' else 'home_macros', {}).pop(button.upper(), None)
        hm.save_config(cfg)
        self.stateChanged.emit()
        if mode == 'button' and button.upper() in p.SIGNAL_KEYS:
            self.resetRemap(button.upper())       # back to sending itself
        self.message.emit(tr('Shortcut removed'), False)
