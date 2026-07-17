"""
Deadband - Qt/QML application entry point
=========================================
Starts the background reader thread and hosts the QML UI. The reverse-engineered
protocol code is reused as-is; this file only wires the reader + the QML engine +
the bridge together.

The app is vendor-neutral (hence "Deadband", a control term rather than a brand);
the `gamesir_*` modules are the GameSir vendor namespace — each speaks that
vendor's protocol, and other manufacturers get their own modules alongside.

Run:  python3 deadband.py
"""

import os
import sys
import threading

from PySide6.QtCore import QUrl, QSettings
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from reader import read_controller, press_select_loop
from bridge import GamesirBridge
import kwin
import mousegrab

__version__ = '0.2.0-dev'

HERE = os.path.dirname(os.path.abspath(__file__))
QML_DIR = os.path.join(HERE, 'qml')
ASSETS_DIR = os.path.join(HERE, 'assets')

APP_NAME = 'Deadband'
ORG_NAME = 'deadband'
# Identity before the rename. QSettings keys its store off (org, app), so renaming
# silently moves it — losing the user's theme, background and controller names.
_OLD_ORG, _OLD_APP = 'gamesir-linux', 'GameSir Cyclone 2'


def _migrate_settings():
    """Carry pre-rename settings over to the new QSettings store, once.

    Copies every key (QML's Settings groups included, e.g. "appearance/themeJson")
    from the old (org, app) to the new one. Only runs when the new store is still
    empty, so it can never clobber newer values, and the old store is left intact
    as a fallback rather than deleted."""
    new = QSettings()                       # resolves via the names set above
    if new.allKeys():
        return                              # already migrated, or a fresh install
    old = QSettings(_OLD_ORG, _OLD_APP)
    keys = old.allKeys()
    if not keys:
        return                              # nothing to carry over
    for k in keys:
        new.setValue(k, old.value(k))
    new.sync()
    print(f'[deadband] migrated {len(keys)} setting(s) from "{_OLD_APP}"')


def main():
    # Background side: identical to the Dear PyGui app.
    threading.Thread(target=read_controller, daemon=True).start()
    # Press-to-select: switch the driven controller by pressing a button on it.
    threading.Thread(target=press_select_loop, daemon=True).start()
    if not kwin.available():
        mousegrab.start()   # EVIOCGRAB fallback (non-KDE); KDE uses the KWin plugin

    app = QGuiApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    _migrate_settings()                 # must follow the names above
    icon_path = os.path.join(ASSETS_DIR, 'icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)                 # makes `import App` resolve
    bridge = GamesirBridge()
    engine.rootContext().setContextProperty('bridge', bridge)
    engine.rootContext().setContextProperty('appVersion', __version__)
    engine.rootContext().setContextProperty(
        'assetsDir', QUrl.fromLocalFile(ASSETS_DIR + os.sep).toString())

    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, 'Main.qml')))
    if not engine.rootObjects():
        sys.exit('Failed to load QML.')

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
