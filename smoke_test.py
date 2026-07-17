#!/usr/bin/env python3
"""Startup smoke test — catch the class of regression that hides at launch.

The app starts a couple of daemon threads (the reader + press-to-select) and then
loads the QML. A bad import inside a thread (like the research/ reorg breaking
press_select_loop) kills that thread with only a traceback on stderr — the app
still opens, so nothing looks wrong until a feature silently doesn't work. QML that
fails to load is similarly quiet. This test reproduces that startup and fails if
either happens.

    python3 smoke_test.py        # exit 0 = OK, 1 = a thread crashed / QML failed

No controller is required: with no hardware the threads just idle. Run it with the
GUI app CLOSED so the reader doesn't briefly double-drive a connected controller.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')   # headless Qt

import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# Record any exception that escapes a background thread's run() (Python 3.8+).
_crashes = []


def _excepthook(args):
    _crashes.append(args)
    threading.__excepthook__(args)          # still print the traceback


threading.excepthook = _excepthook


def main():
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from reader import read_controller, press_select_loop
    from bridge import GamesirBridge

    # 1) Start the same daemon threads deadband.main() starts. A bad import
    #    (top-level or lazy) crashes them within milliseconds of the thread start.
    threads = {
        'read_controller': threading.Thread(target=read_controller, daemon=True),
        'press_select_loop': threading.Thread(target=press_select_loop, daemon=True),
    }
    for t in threads.values():
        t.start()

    # 2) Load the QML headless — catches syntax / missing-import / bad-component
    #    errors (an empty rootObjects means Main.qml did not load).
    app = QGuiApplication(sys.argv)
    qml_dir = os.path.join(HERE, 'qml')
    engine = QQmlApplicationEngine()
    engine.addImportPath(qml_dir)
    bridge = GamesirBridge()
    engine.rootContext().setContextProperty('bridge', bridge)
    engine.rootContext().setContextProperty('appVersion', 'smoke')
    engine.rootContext().setContextProperty(
        'assetsDir', QUrl.fromLocalFile(os.path.join(HERE, 'assets') + os.sep).toString())
    engine.load(QUrl.fromLocalFile(os.path.join(qml_dir, 'Main.qml')))
    qml_ok = bool(engine.rootObjects())

    # 3) Let the threads run their startup and Qt settle for a moment.
    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)

    # --- report ---------------------------------------------------------------
    ok = qml_ok
    print("=== startup smoke test ===")
    print(f"  QML (Main.qml) loaded : {'OK' if qml_ok else 'FAIL — did not load'}")
    for name, t in threads.items():
        alive = t.is_alive()
        ok = ok and alive
        print(f"  thread {name:18}: {'alive' if alive else 'DEAD — crashed on startup'}")
    if _crashes:
        ok = False
        print(f"\n  {len(_crashes)} background thread(s) raised on startup:")
        for c in _crashes:
            print(f"    {c.exc_type.__name__}: {c.exc_value}")

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
