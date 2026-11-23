"""G7 Pro sleep timer (bank 0x20 @0x01F7, #56): decode, staged write, the
Apply register-map check, backup restore, legacy backups and the page."""
import copy
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

import backup
import controller_profile as profiles
from bridge import GamesirBridge
from gs_state import state
from vendors.gamesir import control
from vendors.gamesir.models.g7pro import protocol as g7

SLEEP = 0x01F7


def dock_blob(auto=1, sleep=10, mode=1, bright=100):
    blob = bytearray(g7.DOCK_BLOB_SIZE)
    blob[0x1F6:0x1FA] = bytes((auto, sleep, mode, bright))   # read on an Amazon pad
    return bytes(blob)


class SleepTimer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.old_state = dict(state)
        profiles.set_active(profiles.G7_PRO)
        state.update(profile=1, edit_profile=1, selected='test', driving='test',
                     config_claimed=True)
        self.bridge = GamesirBridge()
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()

    def tearDown(self):
        self.bridge.deleteLater()
        state.clear()
        state.update(self.old_state)
        profiles.set_active(None)

    def test_decodes_the_dock_block(self):
        self.assertEqual(g7.decode_dock(dock_blob()),
                         {'dock_auto': True, 'dock_brightness': 100, 'sleep_minutes': 10})
        self.assertEqual(profiles.G7_PRO.extras['DOCK_SLEEP'], SLEEP)

    def test_stages_one_byte_in_bank_0x20(self):
        self.bridge.setG7Extra('sleep_minutes', 25)
        item = self.bridge._pending[('g7', 0x20, 'sleep_minutes')]
        self.assertEqual((item['bank'], item['addr'], item['data']), (0x20, SLEEP, [25]))
        self.assertEqual(item['display'], '25 min')

    def test_apply_writes_it_through_the_g7_path(self):
        # The G7 Pro saves through applyConfig's own path (not the transactional
        # one or backup._validate_writes); drive that path for real.
        self.bridge.setG7Extra('sleep_minutes', 1)
        done = threading.Event()
        writes = []

        def write_reg(bank, addr, data, write_style=None, gen=None):
            writes.append((bank, addr, list(data), write_style))
            return True
        with patch.object(control, 'write_reg', side_effect=write_reg), \
             patch.object(self.bridge, '_verify_applied', side_effect=lambda *a: done.set()):
            self.bridge.applyConfig()
            self.assertTrue(done.wait(2))
        self.assertEqual(writes, [(0x20, SLEEP, [1], 'g7')])
        self.assertIsNone(self.bridge._g7_dock)          # the dock block is re-read

    def test_untested_or_oversized_values_are_not_staged(self):
        for value in (0, 256, -1):
            self.bridge.setG7Extra('sleep_minutes', value)
        self.assertNotIn(('g7', 0x20, 'sleep_minutes'), self.bridge._pending)

    def _backup(self, **dock):
        from tests.test_motion import captured_blob
        decoded = g7.decode_profile(captured_blob())
        return {'device': profiles.G7_PRO.name,
                'profiles': {str(b): copy.deepcopy(decoded) for b in range(1, 5)},
                'device_settings': {'dock_auto': True, 'dock_brightness': 100, **dock}}

    def test_backup_restores_the_sleep_timer(self):
        writes = backup._g7_writes_from(self._backup(sleep_minutes=25))
        self.assertIn((0x20, SLEEP, [25]), writes)

    def test_backup_without_it_still_restores(self):
        writes = backup._g7_writes_from(self._backup())
        self.assertFalse(any(b == 0x20 and a == SLEEP for b, a, _d in writes))

    def test_bad_sleep_value_refuses_the_backup(self):
        with self.assertRaises(ValueError):
            backup._g7_writes_from(self._backup(sleep_minutes=300))

    def _verify(self, data, blob):
        from tests.test_motion import captured_blob
        blobs = {b: captured_blob() for b in range(1, 5)}
        blobs[0x20] = blob
        values = {}

        def requested(reqs):
            values.update({(b, a): list(blobs[b][a:a + n]) for b, a, n in reqs})
        done, result = threading.Event(), []

        def callback(*args):
            result.append(args)
            done.set()
        with patch.object(control, 'request_regs', side_effect=requested), \
             patch.object(control, 'reg_result', side_effect=lambda b, a: values.get((b, a))):
            backup._apply_g7_backup(data, [], on_done=callback)
            self.assertTrue(done.wait(1))
        return result[0]

    def test_verification_checks_the_sleep_timer_when_the_backup_has_it(self):
        ok, msg = self._verify(self._backup(sleep_minutes=25), dock_blob(sleep=10))
        self.assertFalse(ok)
        self.assertIn('dock settings', msg)
        ok, _msg = self._verify(self._backup(sleep_minutes=25), dock_blob(sleep=25))
        self.assertTrue(ok)

    def test_older_backups_verify_without_it(self):
        ok, msg = self._verify(self._backup(), dock_blob(sleep=10))
        self.assertTrue(ok, msg)

    def test_page_offers_tested_values_and_keeps_a_custom_one(self):
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('bridge', self.bridge)
        import i18n
        lang = i18n.LanguageManager(self.app, engine) if hasattr(i18n, 'LanguageManager') else None
        if lang is not None:
            engine.rootContext().setContextProperty('i18n', lang)
        engine.addImportPath(str(Path(__file__).resolve().parents[1] / 'qml'))
        engine.loadData(b'import QtQuick\nimport App\nG7DevicePage { width: 600; height: 700 }',
                        QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'qml' / 'x.qml')))
        self.assertTrue(engine.rootObjects(), 'G7DevicePage failed to load')
        page = engine.rootObjects()[0]
        self.assertEqual(page.property('sleepShown').toVariant()
                         if hasattr(page.property('sleepShown'), 'toVariant')
                         else page.property('sleepShown'), [1, 5, 10, 20])
        page.setProperty('sleepMin', 25)
        shown = page.property('sleepShown')
        shown = shown.toVariant() if hasattr(shown, 'toVariant') else shown
        self.assertEqual(shown, [1, 5, 10, 20, 25])
        engine.deleteLater()


if __name__ == '__main__':
    unittest.main()
