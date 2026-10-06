"""Exercise actual controller QML with synthetic registers and hardware blocked."""
from pathlib import Path
import sys
import types
from unittest.mock import patch

def forbidden(*args, **kwargs):
    raise AssertionError('hardware access forbidden in UI checks')

hid = types.ModuleType('hid')
hid.device = hid.enumerate = forbidden
sys.modules['hid'] = hid

from PySide6.QtCore import Q_ARG, QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import delete
from bridge import GamesirBridge
from mouse_bridge import MouseBridge
import kwin
from vendors.gamesir import control


def main():
    source = Path(__file__).resolve().parent
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/deadband-controller-ui.png')
    app = QGuiApplication(sys.argv)
    app.setApplicationName('DeadbandControllerUiCheck')
    app.setOrganizationName('deadband-test')
    with patch.object(kwin, 'available', return_value=False), patch.object(MouseBridge, 'refresh'):
        pad, mouse = GamesirBridge(), MouseBridge()
    mouse._timer.stop()
    mouse._probe_macro_worker = lambda: None
    pad.setDemoMode(True)
    pump = QTimer()
    pump.setInterval(10)
    pump.timeout.connect(control.pump_demo_reads)
    pump.start()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(source / 'qml'))
    context = engine.rootContext()
    context.setContextProperty('bridge', pad)
    context.setContextProperty('mouse', mouse)
    context.setContextProperty('appVersion', 'continuous-trigger-ui-check')
    context.setContextProperty('assetsDir', QUrl.fromLocalFile(str(source / 'assets') + '/').toString())
    warnings = []
    engine.warnings.connect(lambda messages: warnings.extend(str(m) for m in messages))
    engine.load(QUrl.fromLocalFile(str(source / 'qml/Main.qml')))
    assert engine.rootObjects(), 'QML did not load'
    window = engine.rootObjects()[0]

    def settle(ms=250):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    settle(1800)
    page = window.findChild(QObject, 'controllerButtonsPage')
    switch = window.findChild(QObject, 'continuousTriggerSwitch')
    assert page is not None and switch is not None
    page.setProperty('sel', 'L4')
    settle()
    assert switch.property('enabled'), pad._config
    assert not switch.property('checked')
    assert QMetaObject.invokeMethod(page, 'assignCode', Qt.DirectConnection,
                                   Q_ARG('QVariant', 'L4'), Q_ARG('QVariant', 20))
    assert QMetaObject.invokeMethod(switch, 'toggled', Qt.DirectConnection, Q_ARG(bool, True))
    settle()
    assert switch.property('checked')
    assert pad._pending[(1, 0xb2)]['data'] == [1, 20]
    assert pad._pending[(1, 0xb6)]['data'] == [1]
    # Exercise every official remappable source through the actual QML switch,
    # including the ordinary buttons missing from the original app.
    for source_name, flag_address in pad._prof.CONTINUOUS_TRIGGER_SLOTS:
        page.setProperty('sel', source_name)
        settle(35)
        assert switch.property('enabled'), source_name
        assert QMetaObject.invokeMethod(switch, 'toggled', Qt.DirectConnection, Q_ARG(bool, True))
        assert pad._pending[(1, flag_address)]['data'] == [1], source_name
    pad.discardConfig()
    settle(1000)
    page.setProperty('sel', 'L4')
    assert QMetaObject.invokeMethod(page, 'assignCode', Qt.DirectConnection,
                                   Q_ARG('QVariant', 'L4'), Q_ARG('QVariant', 20))
    assert QMetaObject.invokeMethod(switch, 'toggled', Qt.DirectConnection, Q_ARG(bool, True))
    page.setProperty('sel', 'RT')
    settle()
    assert not switch.property('checked'), 'binding failed on source change'
    assert QMetaObject.invokeMethod(switch, 'toggled', Qt.DirectConnection, Q_ARG(bool, True))
    page.setProperty('sel', 'L4')
    settle()
    assert switch.property('checked'), 'staged paddle toggle was lost'
    frame = window.grabWindow()
    assert not frame.isNull() and frame.save(str(destination))
    for width, height in ((1120, 800), (1040, 720), (840, 620)):
        window.setWidth(width)
        window.setHeight(height)
        tabs = window.property('controllerTabs')
        tabs = tabs.toVariant() if hasattr(tabs, 'toVariant') else tabs
        for tab in range(len(tabs)):
            window.setProperty('currentTab', tab)
            settle(80)
        window.setProperty('currentTab', 0)
        settle()
    pad.discardConfig()
    settle(1000)
    assert not switch.property('checked') and not pad._pending
    pad._config['continuous_trigger']['L4'] = -1
    pad.configLoaded.emit()
    settle()
    assert not switch.property('enabled'), 'unknown flag remained editable'
    # Existing upstream controls briefly bind undefined values during startup.
    # Keep those exact locations separate from errors in the new editor.
    startup_warnings = ('qml/Main.qml:385:21: Unable to assign [undefined] to bool',
                        'qml/App/MacroPage.qml:89:71: Unable to assign [undefined] to int',
                        'qml/App/BackupPanel.qml:53:9: Unable to assign [undefined] to bool')
    errors = [message for message in warnings if any(s in message for s in
              ('ReferenceError', 'TypeError', 'Cannot assign', 'Unable to assign',
               'Binding loop', 'is not a function'))
              and not any(known in message for known in startup_warnings)]
    assert not errors, errors
    print('Controller QML: all 19 remappable sources, L4→RT staging, source binding, Discard, unknown flags and all tabs at default/minimum size passed.')
    print('Preview:', destination)
    for timer in (pad._input_timer, pad._status_timer, pad._light_timer):
        timer.stop()
    delete(engine)
    pump.stop()
    pad.setDemoMode(False)


if __name__ == '__main__':
    main()
