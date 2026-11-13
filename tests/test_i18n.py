"""Language selection, live QML bindings and the shipped translation catalogs."""
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QLocale, QSettings, QTranslator, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from i18n import CATALOGS, LANGUAGES, LanguageManager, system_language


class TranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_system_locale_selects_script_and_available_language(self):
        for locale, expected in [('zh_HK', 'zh_TW'), ('zh_SG', 'zh_CN'),
                                 ('pt_PT', 'pt_BR'), ('fr_CA', 'fr'), ('ko_KR', 'en')]:
            self.assertEqual(system_language(QLocale(locale)), expected)

    def test_live_switch_persistence_and_english_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch('i18n.system_language', return_value='en'):
            settings = QSettings(directory + '/settings.ini', QSettings.IniFormat)
            engine = QQmlApplicationEngine()
            manager = LanguageManager(self.app, engine, settings)
            component = QQmlComponent(engine)
            component.setData(b'import QtQml; QtObject { property string label: qsTranslate("UI", "Settings") }', QUrl())
            item = component.create()
            try:
                for code, _ in LANGUAGES:
                    manager.setLanguage(code)
                    self.assertEqual(manager.language, code)
                    if code not in ('', 'en'):
                        self.assertNotEqual(item.property('label'), 'Settings', code)
                manager.setLanguage('ru')
                self.assertEqual(item.property('label'), 'Настройки')
                settings.sync()
                self.assertEqual(QSettings(settings.fileName(), QSettings.IniFormat).value('language'), 'ru')
                manager.setLanguage('unsupported')
                self.assertEqual(manager.language, '')
                self.assertEqual(item.property('label'), 'Settings')
            finally:
                manager.setLanguage('en')
                item.deleteLater()

    def test_catalogs_are_complete_and_compiled_with_matching_placeholders(self):
        sources = None
        for code, _ in LANGUAGES[2:]:
            root = ET.parse(CATALOGS / f'deadband_{code}.ts').getroot()
            translator = QTranslator()
            self.assertTrue(translator.load(str(CATALOGS / f'deadband_{code}.qm')))
            messages = {(c.findtext('name'), m.findtext('source')): m.find('translation')
                        for c in root.findall('context') for m in c.findall('message')}
            if sources is None:
                sources = set(messages)
            self.assertEqual(set(messages), sources)
            for (context, source), translation in messages.items():
                self.assertNotEqual(translation.get('type'), 'unfinished', (code, source))
                self.assertTrue(translation.text, (code, source))
                self.assertEqual(Counter(re.findall(r'%\d+', source)),
                                 Counter(re.findall(r'%\d+', translation.text)), (code, source))
                self.assertEqual(translator.translate(context, source), translation.text, (code, source))
