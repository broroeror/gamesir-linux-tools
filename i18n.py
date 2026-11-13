"""Qt translations shared by the controller and mouse GUI."""
from pathlib import Path

from PySide6.QtCore import (QObject, Property, QCoreApplication, QLocale, QSettings,
                           QTranslator, Signal, Slot, QT_TRANSLATE_NOOP)


LANGUAGES = (
    ('', 'System language'), ('en', 'English'),
    ('zh_TW', '繁體中文'), ('zh_CN', '简体中文'), ('vi', 'Tiếng Việt'),
    ('ru', 'Русский'), ('es', 'Español'), ('pt_BR', 'Português (Brasil)'),
    ('de', 'Deutsch'), ('fr', 'Français'), ('ja', '日本語'),
)
CATALOGS = Path(__file__).resolve().parent / 'translations'

# Display labels returned by the bridges. Keep their protocol-facing names intact;
# QML translates them at the point of display, using this shared context.
_BRIDGE_LABELS = (
    QT_TRANSLATE_NOOP('UI', 'Linear'),
    QT_TRANSLATE_NOOP('UI', 'Ready.'),
    QT_TRANSLATE_NOOP('UI', 'Roll'),
    QT_TRANSLATE_NOOP('UI', 'Yaw'),
    QT_TRANSLATE_NOOP('UI', 'Left grip'),
    QT_TRANSLATE_NOOP('UI', 'Right grip'),
    QT_TRANSLATE_NOOP('UI', 'Profile'),
    QT_TRANSLATE_NOOP('UI', 'Home'),
    QT_TRANSLATE_NOOP('UI', 'Flow'),
    QT_TRANSLATE_NOOP('UI', 'Pulse'),
    QT_TRANSLATE_NOOP('UI', 'Standoff'),
    QT_TRANSLATE_NOOP('UI', 'Alarm'),
    QT_TRANSLATE_NOOP('UI', 'Opening game input…'),
    QT_TRANSLATE_NOOP('UI', 'Rotate a stick continuously for 10 seconds.'),
    QT_TRANSLATE_NOOP('UI', 'Stopped. Start again for a complete 10-second test.'),
    QT_TRANSLATE_NOOP('UI', 'Complete · observed input-update rate, not physical latency.'),

    QT_TRANSLATE_NOOP('UI', 'Adaptive'),
    QT_TRANSLATE_NOOP('UI', 'Fixed'),
    QT_TRANSLATE_NOOP('UI', 'Concave'),
    QT_TRANSLATE_NOOP('UI', 'S-Curve'),
    QT_TRANSLATE_NOOP('UI', 'Curve'),
    QT_TRANSLATE_NOOP('UI', 'Press to switch'),
    QT_TRANSLATE_NOOP('UI', 'Always on'),
    QT_TRANSLATE_NOOP('UI', 'Both'),
    QT_TRANSLATE_NOOP('UI', 'Yaw + Roll'),
    QT_TRANSLATE_NOOP('UI', 'Invert Roll'),
    QT_TRANSLATE_NOOP('UI', 'Invert Yaw'),
    QT_TRANSLATE_NOOP('UI', 'Invert Pitch'),
    QT_TRANSLATE_NOOP('UI', 'Static'),
    QT_TRANSLATE_NOOP('UI', 'Colorful'),
    QT_TRANSLATE_NOOP('UI', 'Rainbow'),
    QT_TRANSLATE_NOOP('UI', 'Follow battery'),
    QT_TRANSLATE_NOOP('UI', 'Follow animation'),
    QT_TRANSLATE_NOOP('UI', '1 min'),
    QT_TRANSLATE_NOOP('UI', '5 min'),
    QT_TRANSLATE_NOOP('UI', '10 min'),
    QT_TRANSLATE_NOOP('UI', '20 min'),
)


def system_language(locale=None):
    """Use Qt's script-aware locale expansion, e.g. zh-Hant-HK → zh_TW."""
    for name in (locale or QLocale.system()).uiLanguages():
        locale = QLocale(name)
        language = locale.language()
        if language == QLocale.Language.Chinese:
            return ('zh_TW' if locale.script() == QLocale.Script.TraditionalHanScript
                    else 'zh_CN')
        if language == QLocale.Language.Portuguese:
            return 'pt_BR'
        code = locale.name().split('_')[0]
        if code in dict(LANGUAGES):
            return code
    return 'en'


class LanguageManager(QObject):
    languageChanged = Signal()

    def __init__(self, app, engine, settings=None):
        super().__init__(engine)
        self._app = app
        self._engine = engine
        self._settings = settings if settings is not None else QSettings()
        self._translator = None
        self._language = None
        self.setLanguage(self._settings.value('language', '', str))

    @Property(str, notify=languageChanged)
    def language(self):
        return self._language

    @Property('QStringList', constant=True)
    def languageCodes(self):
        return [code for code, _ in LANGUAGES]

    @Property('QStringList', notify=languageChanged)
    def languageNames(self):
        return [QCoreApplication.translate('LanguageManager', 'System language'),
                *[label for code, label in LANGUAGES if code]]

    @Slot(str)
    def setLanguage(self, language):
        if language not in dict(LANGUAGES):
            language = ''
        if language == self._language:
            return
        code = language or system_language()
        translator = None
        if code != 'en':
            translator = QTranslator(self)
            if not translator.load(str(CATALOGS / f'deadband_{code}.qm')):
                translator.deleteLater()
                if self._language is not None:
                    return  # keep the current language if a catalog is missing
                translator = None  # English fallback on first launch
        previous = self._translator
        if previous is not None:
            self._app.removeTranslator(previous)
        self._translator = translator
        if translator is not None:
            self._app.installTranslator(translator)
        self._language = language
        self._settings.setValue('language', language)
        self._engine.retranslate()
        self.languageChanged.emit()
        if previous is not None:
            previous.deleteLater()
