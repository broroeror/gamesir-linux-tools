"""#51: does MacroPage show the selected paddle's macro after a switch?"""
import sys, types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent


def forbidden(*a, **k):
    raise AssertionError('hardware access forbidden')


hid = types.ModuleType('hid')
hid.device = type('D', (), {'__init__': forbidden})
hid.enumerate = forbidden
sys.modules['hid'] = hid
sys.modules['hidraw'] = None

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from bridge import GamesirBridge
from mouse_bridge import MouseBridge
import kwin
import controller_profile as profiles

app = QGuiApplication(sys.argv)
app.setOrganizationName('deadband-test')
with patch.object(kwin, 'available', return_value=False), patch.object(MouseBridge, 'refresh'):
    pad = GamesirBridge()
pad.setDemoMode(True)
pad.selectController(pad._demo_id(profiles.G7_8K))


def settle(ms=300):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


settle(800)
ev = lambda t: [{'target': t, 'hold': 100, 'delay': 0}]
pad._macros = {'L4': {'enable': False, 'events': []},
               'R4': {'enable': False, 'events': []},
               'L5': {'enable': True, 'events': ev(1)},     # Dpad Up
               'R5': {'enable': True, 'events': ev(4)}}     # Dpad Right
pad._macro_profile = 1   # keep the demo poll from replacing them
writes = []
pad.setMacroEvents = lambda p, e: writes.append(p)
pad.macroLoaded.emit()

engine = QQmlEngine()
engine.addImportPath(str(REPO / 'qml'))
engine.rootContext().setContextProperty('bridge', pad)
comp = QQmlComponent(engine, QUrl.fromLocalFile(str(REPO / 'qml/App/MacroPage.qml')))
page = comp.create()
assert page, comp.errors()
print('slots:', pad.macroSlots)
bad = 0
for idx in (3, 2, 1, 0, 2, 3):
    page.setProperty('pad', idx)
    settle(50)
    name = pad.macroSlots[idx]
    shown = page.property('events')
    shown = shown.toVariant() if hasattr(shown, 'toVariant') else shown
    want = pad._macros[name]['events']
    ok = [e['target'] for e in shown] == [e['target'] for e in want]
    bad += not ok
    print(f'{name}: shown {[e["target"] for e in shown]} enable={page.property("enable")} '
          f'-> {"ok" if ok else "WRONG"}')
print("RESULT:", "PASS" if not bad else f"FAIL ({bad})")
sys.exit(1 if bad else 0)
