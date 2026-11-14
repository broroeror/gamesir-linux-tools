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
Diagnose device-access problems (headless, no GUI):  deadband --doctor
"""

import argparse
import os
import sys
import threading
from version import __version__

# Handle terminal options before importing Qt so help, version and diagnostics
# work on headless machines and when the GUI dependencies are unavailable.
def _parse_cli():
    parser = argparse.ArgumentParser(
        prog='deadband',
        description='Configure supported GameSir controllers and Logitech mice.',
        epilog=('Run without options to open the graphical app. Shell completions '
                'are available for Bash, Zsh, and Fish.'),
    )
    parser.add_argument('--doctor', action='store_true',
                        help='print device-access diagnostics and exit')
    parser.add_argument('--probe', action='store_true',
                        help='with --doctor: also ask connected devices a few '
                             'read-only questions (close Deadband first)')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {__version__}')
    options, passthrough = parser.parse_known_args()
    if options.doctor:
        from doctor import run_cli
        raise SystemExit(run_cli())
    # Leave any Qt command-line arguments for QGuiApplication.
    sys.argv[:] = [sys.argv[0], *passthrough]


_parse_cli()

from PySide6.QtCore import QUrl, QSettings
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from reader import read_controller, press_select_loop, release_controller
from bridge import GamesirBridge
from mouse_bridge import MouseBridge
from i18n import LanguageManager
import kwin
import mousegrab

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
    if sys.platform.startswith('linux'):
        # Press-to-select: switch the driven controller by pressing a button on
        # it. Watches evdev, which only Linux has; elsewhere the header picker.
        threading.Thread(target=press_select_loop, daemon=True).start()
        if not kwin.available():
            mousegrab.start()   # EVIOCGRAB fallback (non-KDE); KDE uses the KWin plugin

    app = QGuiApplication(sys.argv)
    app.aboutToQuit.connect(release_controller)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setDesktopFileName(ORG_NAME)
    
    _migrate_settings()                 # must follow the names above
    # the 1024px art where it exists: macOS shows the window icon in the Dock,
    # at Retina size
    icon_path = os.path.join(ASSETS_DIR, 'icon-1024.png')
    if not os.path.exists(icon_path):
        icon_path = os.path.join(ASSETS_DIR, 'icon.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)                 # makes `import App` resolve
    language = LanguageManager(app, engine)
    engine.rootContext().setContextProperty('i18n', language)
    bridge = GamesirBridge()
    engine.rootContext().setContextProperty('bridge', bridge)
    mouse = MouseBridge()
    engine.rootContext().setContextProperty('mouse', mouse)
    engine.rootContext().setContextProperty('appVersion', __version__)
    engine.rootContext().setContextProperty(
        'assetsDir', QUrl.fromLocalFile(ASSETS_DIR + os.sep).toString())

    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, 'Main.qml')))
    if not engine.rootObjects():
        sys.exit('Failed to load QML.')

    code = app.exec()
    # Tear the QML down while `bridge` and `mouse` still exist. Left to Python's
    # exit, they could go first and every binding on them would log "Cannot
    # read property ... of null" -- hundreds of lines burying a bug report's
    # real errors (#28).
    del engine
    sys.exit(code)


if __name__ == '__main__':
    main()
