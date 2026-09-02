#!/usr/bin/env python3
"""Regenerate ALL README art: page screenshots, the banner, and gallery.gif.

Run from anywhere:  python3 docs/screenshots/generate_shots.py

Full Main.qml + real GamesirBridge in demo mode (data-rich pages, no hardware),
a fake MouseBridge with staged content for the mouse tabs, then per shot:
apply a theme preset -> pick device/tab -> settle -> grabWindow -> save + thumb.
The DEMO badge is cosmetic (state['demo']) — flipped off after the demo data
settles so shots show the normal wordmark and a live-looking status pill.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = HERE
sys.path.insert(0, REPO)
os.chdir(REPO)

from PySide6.QtCore import (QObject, Signal, Property, Slot, QUrl, QMetaObject,  # noqa: E402
                            Qt, Q_ARG)
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

app = QGuiApplication(sys.argv)
app.setOrganizationName("deadband-shoot")      # throwaway settings scope —
app.setApplicationName("shoot")                # never touches the real store

from gs_state import state  # noqa: E402
import bridge as B  # noqa: E402


# ---------------------------------------------------------------- fake mouse
class FM(QObject):
    presenceChanged = Signal(); bindingsChanged = Signal(); sensorChanged = Signal()
    statusChanged = Signal(); busyChanged = Signal(); pendingChanged = Signal()
    applyStatusChanged = Signal(); profilesChanged = Signal()

    @Property('QVariantList', notify=profilesChanged)
    def profiles(self):
        # named + unnamed, so the shot shows both the stored name and the
        # "Profile N" fallback the bar uses when G HUB never set one
        names = ["FPS", "Work", "", "Photo", ""]
        return [{'index': i + 1, 'sector': i + 1, 'name': n,
                 'label': n or f'Profile {i + 1}', 'enabled': True}
                for i, n in enumerate(names)]

    @Property(int, notify=profilesChanged)
    def selectedProfile(self): return 2      # editing P2 while the mouse runs P1
    @Slot(int)
    def selectProfile(self, sector): pass
    @Slot(int)
    def makeActive(self, sector): pass
    @Slot(int, str)
    def renameProfile(self, sector, name): pass

    @Property(bool, notify=presenceChanged)
    def present(self): return True
    @Property(str, notify=presenceChanged)
    def permission(self): return "ok"
    @Property(bool, notify=busyChanged)
    def busy(self): return False
    @Property(str, notify=statusChanged)
    def status(self): return ""
    @Property(str, notify=applyStatusChanged)
    def applyStatus(self): return ""
    @Property(int, notify=presenceChanged)
    def activeProfile(self): return 1
    @Property(int, notify=presenceChanged)
    def buttonCount(self): return 11
    @Property(int, notify=presenceChanged)
    def battery(self): return 87
    @Property(bool, notify=presenceChanged)
    def wireless(self): return True
    @Property('QVariantMap', notify=bindingsChanged)
    def bindings(self):
        return {"0": "Left Click", "1": "Right Click", "2": "Middle Click",
                "3": "Backward", "4": "Sniper", "5": "Forward",
                "6": "Scroll L/T", "7": "Scroll R/T", "8": "Profile Cycle",
                "9": "DPI Up", "10": "Macro"}
    @Property('QVariantMap', notify=bindingsChanged)
    def gbindings(self):
        return {"0": "Ctrl+C", "1": "Ctrl+V", "9": "F13"}
    @Property('QVariantList', notify=sensorChanged)
    def dpiStages(self): return [800, 1600, 3200, 6400, 12800]
    @Property(int, notify=sensorChanged)
    def dpiDefault(self): return 1
    @Property(int, notify=sensorChanged)
    def dpiShift(self): return 0
    @Property(int, notify=sensorChanged)
    def reportRate(self): return 1000
    @Property(int, notify=sensorChanged)
    def dpiMin(self): return 100
    @Property(int, notify=sensorChanged)
    def dpiMax(self): return 25600
    @Property(int, notify=sensorChanged)
    def dpiStep(self): return 50
    @Property('QVariantList', constant=True)
    def reportRates(self): return [125, 250, 500, 1000]
    @Property(int, notify=sensorChanged)
    def macroSlotsFree(self): return 7
    @Property('QVariantList', constant=True)
    def buttonList(self):
        n = {0: 'Left Click', 1: 'Right Click', 2: 'Middle Click', 3: 'Backward',
             4: 'DPI Shift', 5: 'Forward', 6: 'Scroll L/T', 7: 'Scroll R/T',
             8: 'Profile Cycle', 9: 'DPI Up', 10: 'DPI Down'}
        return [{'index': i, 'name': n[i]} for i in [0, 1, 2, 6, 7, 9, 10, 8, 4, 5, 3]]
    @Property('QVariantList', constant=True)
    def buttonGroups(self):
        n = dict((b['index'], b['name']) for b in self.buttonList)
        return [{'group': g, 'buttons': [{'index': i, 'name': n[i]} for i in idxs]}
                for g, idxs in [('Clicks', [0, 1, 2]), ('Scroll', [6, 7]),
                                ('DPI', [9, 10, 4]), ('Thumb', [8, 5, 3])]]
    @Property('QVariantList', constant=True)
    def mediaActions(self):
        return [{'code': 0xCD, 'name': 'Play/Pause'}, {'code': 0xB5, 'name': 'Next'},
                {'code': 0xB6, 'name': 'Previous'}, {'code': 0xE9, 'name': 'Vol +'},
                {'code': 0xEA, 'name': 'Vol -'}, {'code': 0xE2, 'name': 'Mute'}]
    @Property(int, notify=pendingChanged)
    def pendingCount(self): return 1
    @Property('QVariantMap', notify=pendingChanged)
    def pending(self): return {}
    @Property('QVariantMap', notify=pendingChanged)
    def pendingSensor(self): return {}
    @Property('QVariantList', notify=pendingChanged)
    def pendingList(self):
        return [{'group': 'macro', 'key': 'macro:10',
                 'name': 'DPI Down', 'label': 'Macro: Ctrl+C · “gg” · Scroll ↑'}]
    @Slot(int, result='QVariantMap')
    def stagedMacro(self, b):
        if int(b) == 0:      # Macros tab defaults to the first button (Left Click)
            return {'steps': [
                {'t': 'key', 'combo': 'ctrl+c', 'hold': 0, 'delay': 60},
                {'t': 'text', 'text': 'gg ez', 'delay': 40},
                {'t': 'key', 'combo': 'shift+f13', 'hold': 90, 'delay': 30},
                {'t': 'click', 'button': 1, 'hold': 0, 'delay': 20},
                {'t': 'scroll', 'delta': 1, 'delay': 0}], 'repeat': True}
        return {}
    @Slot()
    def refresh(self): pass
    @Slot()
    def discard(self): pass
    @Slot()
    def apply(self): pass
    @Slot()
    def probeMacroSlots(self): pass
    @Slot()
    def reclaimSlots(self): pass
    @Slot()
    def clearApplyStatus(self): pass
    @Slot(str)
    def unstageItem(self, k): pass
    @Slot(str, int, str)
    def stage(self, l, b, s): pass
    @Slot(str, int)
    def unstage(self, l, b): pass
    @Slot(int, str)
    def stageMacro(self, b, j): pass
    @Slot(int, int)
    def stageDpi(self, i, v): pass
    @Slot(int)
    def stageDpiDefault(self, i): pass
    @Slot(int)
    def stageDpiShift(self, i): pass
    @Slot(int)
    def stageReportRate(self, hz): pass


def settle(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


os.makedirs(OUT, exist_ok=True)
b = B.GamesirBridge()
m = FM()

eng = QQmlApplicationEngine()
eng.addImportPath(os.path.join(REPO, "qml"))
eng.rootContext().setContextProperty("bridge", b)
eng.rootContext().setContextProperty("mouse", m)
eng.rootContext().setContextProperty("assetsDir",
    QUrl.fromLocalFile(os.path.join(REPO, "assets") + "/").toString())
warns = []
eng.warnings.connect(lambda ws: warns.extend(str(w.toString()) for w in ws))
eng.load(QUrl.fromLocalFile(os.path.join(REPO, "qml", "Main.qml")))
if not eng.rootObjects():
    print("LOAD FAILED"); [print(w) for w in warns[:6]]; sys.exit(2)
win = [o for o in eng.rootObjects() if isinstance(o, QQuickWindow)][0]
win.resize(1280, 800)

# demo mode fills every page with data; visit each controller tab once so lazy
# loads land, then drop the cosmetic DEMO flag for a live-looking header
b.setDemoMode(True)
settle(1.0)
for tab in range(7):
    win.setProperty("currentTab", tab)
    settle(0.4)
win.setProperty("currentTab", 0)
state['demo'] = False
state['firmware'] = '3.52'
state['wired'] = True
b.demoModeChanged.emit()
settle(0.5)

# theme presets (mirrors Theme.qml — literal values so we don't parse QML)
P = {
 'red':     None,     # default — applyPreset skipped, resetTheme instead
 'cobalt':  {"accent": "#3B82F6", "bg": "#0B0E14", "bgGlow": "#122036", "navBar": "#111521",
             "card": "#161B26", "cardBorder": "#232B3A", "button": "#1E2636", "track": "#2C3648",
             "ringSelect": "#FFFFFF", "text": "#EEF2F8", "textDim": "#94A0B4"},
 'emerald': {"accent": "#2FBF71", "bg": "#0A0F0C", "bgGlow": "#0F2A1C", "navBar": "#101613",
             "card": "#151C18", "cardBorder": "#222C27", "button": "#1D2620", "track": "#2B372F",
             "ringSelect": "#FFFFFF", "text": "#EDF5F0", "textDim": "#93A69C"},
 'violet':  {"accent": "#8B5CF6", "bg": "#0E0B14", "bgGlow": "#20143A", "navBar": "#15111F",
             "card": "#1A1626", "cardBorder": "#2A2340", "button": "#241E36", "track": "#342C4E",
             "ringSelect": "#FFFFFF", "text": "#F0ECF8", "textDim": "#A198B4"},
 'slate':   {"accent": "#E03A2F", "bg": "#E9ECF1", "bgGlow": "#F3D9D6", "navBar": "#DCE0E8",
             "card": "#FFFFFF", "cardBorder": "#CDD3DE", "button": "#E6E9EF", "track": "#C2C7D2",
             "ringSelect": "#333A47", "text": "#1A1D24", "textDim": "#5C636F"},
}


def theme(name):
    if P[name] is None:
        QMetaObject.invokeMethod(win, "resetTheme", Qt.DirectConnection)
    else:
        QMetaObject.invokeMethod(win, "applyPreset", Qt.DirectConnection,
                                 Q_ARG("QVariant", P[name]))


SHOTS = [
    # (file, device, tab, theme)
    ("controller-rebinds", "controller", 0, 'red'),
    ("controller-lights",  "controller", 5, 'violet'),
    ("controller-sticks",  "controller", 1, 'cobalt'),
    ("mouse-buttons",      "mouse",      0, 'emerald'),
    ("mouse-macros",       "mouse",      2, 'slate'),
]

for fname, device, tab, th in SHOTS:
    theme(th)
    win.setProperty("activeDevice", device)
    settle(0.2)
    win.setProperty("currentTab", tab)
    settle(0.8)
    img = win.grabWindow()
    path = os.path.join(OUT, fname + ".png")
    img.save(path)
    thumb = img.scaledToWidth(360, Qt.SmoothTransformation)
    thumb.save(os.path.join(OUT, "thumb-" + fname + ".png"))
    print(f"shot {fname} ({th}) -> {img.width()}x{img.height()}")

theme('red')       # leave the throwaway settings tidy
errs = [w for w in warns if 'rror' in w]
print("qml errors:", errs[:4] if errs else "none")
print("done ->", OUT)

# ---------------------------------------------------------------- banner + gif
from PySide6.QtQuick import QQuickView

bv = QQuickView()
bv.engine().addImportPath(os.path.join(REPO, "qml"))
bv.rootContext().setContextProperty("bannerAssets",
    QUrl.fromLocalFile(os.path.join(REPO, "assets") + "/").toString())
bv.setResizeMode(QQuickView.SizeRootObjectToView)
bv.setSource(QUrl.fromLocalFile(os.path.join(OUT, "banner.qml")))
if bv.status() != QQuickView.Error:
    bv.resize(1440, 360); bv.show(); settle(0.6)
    bv.grabWindow().save(os.path.join(OUT, "banner.png"))
    print("banner saved")

from PIL import Image, ImageDraw, ImageFont

GIF = [("controller-rebinds.png", "Rebinds — live controller view", "GameSir Red"),
       ("controller-lights.png",  "Lighting & keyframe animations", "Violet"),
       ("controller-sticks.png",  "Stick curves & deadzones",       "Cobalt"),
       ("mouse-buttons.png",      "G502 X — buttons & G-Shift",     "Emerald"),
       ("mouse-macros.png",       "G502 X — onboard macro editor",  "Slate (light)")]

def _font(size):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()

W, BAR = 960, 44
fm, fd = _font(19), _font(16)
frames = []
for i, (path, title, thname) in enumerate(GIF):
    im = Image.open(os.path.join(OUT, path)).convert("RGB")
    im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
    cv = Image.new("RGB", (W, im.height + BAR), (12, 11, 13))
    cv.paste(im, (0, 0))
    d = ImageDraw.Draw(cv)
    y = im.height + BAR // 2
    d.text((16, y), title, fill=(238, 235, 240), font=fm, anchor="lm")
    d.text((W - 16, y), f"{thname}  ·  {i + 1}/{len(GIF)}",
           fill=(150, 145, 158), font=fd, anchor="rm")
    frames.append(cv.quantize(colors=256, method=Image.MEDIANCUT,
                              dither=Image.FLOYDSTEINBERG))
frames[0].save(os.path.join(OUT, "gallery.gif"), save_all=True,
               append_images=frames[1:], duration=2800, loop=0, optimize=True)
print("gallery.gif rebuilt")
