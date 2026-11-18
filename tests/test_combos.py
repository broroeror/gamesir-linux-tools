"""Key combos on Cyclone-protocol pads (#30): encoding, decoding, the bridge's
staged write, Apply's register-map check, and the picker's packed code."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QMetaObject, QObject, Q_ARG, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

import backup
import controller_profile as profiles
from bridge import GamesirBridge
from gs_state import state
from vendors.gamesir import config as cfg

CTRL, SHIFT, WIN, F12, LEFT = 0x74, 0x68, 0x75, 0x3e, 0x82


class ComboEncodingTests(unittest.TestCase):
    def test_modifiers_come_first_whatever_the_stored_order(self):
        # the pad sent Ctrl+Shift+F12 for both 74 68 3e and 3e 68 74
        self.assertEqual(cfg.pack_combo([F12, SHIFT, CTRL]), cfg.pack_combo([CTRL, SHIFT, F12]))
        self.assertEqual(cfg.unpack_combo(cfg.pack_combo([F12, SHIFT, CTRL])), [CTRL, SHIFT, F12])

    def test_single_keys_stay_plain_codes(self):
        self.assertEqual(cfg.pack_combo([0x9a]), 0x9a)
        self.assertEqual(cfg.decode_remap_record([0x01, 0x9a, 0, 0, 0]), 0x9a)
        self.assertEqual(cfg.decode_remap_record([0x00, 0, 0, 0]), -1)

    def test_records_decode_and_label(self):
        value = cfg.decode_remap_record([0x01, WIN, LEFT, 0x00, 0x00])
        self.assertGreater(value, 0xff)
        self.assertEqual(cfg.combo_label(value, cfg.target_label), 'Win+Left')
        self.assertEqual(cfg.combo_label(cfg.pack_combo([CTRL, SHIFT, F12]), cfg.target_label),
                         'Ctrl+Shift+F12')


class ComboBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.old_prof = profiles.active() if profiles.is_recognized() else None
        self.old_state = dict(state)
        self.addCleanup(self.restore)

    def restore(self):
        profiles.set_active(self.old_prof)
        state.clear(); state.update(self.old_state)

    def bridge_for(self, prof):
        profiles.set_active(prof)
        state.update(connected=True, profile=1, edit_profile=1,
                     selected='pad', driving='pad', controller=prof.short)
        b = GamesirBridge()
        b._apply_profile(prof)
        return b

    def test_cyclone_rebind_writes_the_combo_and_passes_apply_check(self):
        b = self.bridge_for(profiles.CYCLONE)
        self.assertTrue(b.canCombo('L4'))
        b.setRemapCode('L4', cfg.pack_combo([CTRL, SHIFT, F12]))
        data = b._pending[(1, 0x00b2)]['data']
        self.assertEqual(data, [0x01, CTRL, SHIFT, F12])
        backup._validate_writes([(1, 0x00b2, data)])        # Apply's register-map check
        self.assertEqual(b.targetLabel(cfg.pack_combo([CTRL, SHIFT, F12])), 'Ctrl+Shift+F12')

    def test_two_key_combo_clears_the_spare_slot(self):
        b = self.bridge_for(profiles.CYCLONE)
        b.setRemapCode('A', cfg.pack_combo([WIN, LEFT]))
        self.assertEqual(b._pending[(1, 0x007a)]['data'], [0x01, WIN, LEFT, 0x00])

    def test_slots_without_spare_bytes_refuse_combos(self):
        b = self.bridge_for(profiles.TARANTULA_PRO_8K)
        self.assertFalse(b.canCombo('LT'))
        b.setRemapCode('LT', cfg.pack_combo([CTRL, F12]))
        self.assertEqual(b._pending, {})
        self.assertTrue(b.canCombo('C1'))

    def test_loaded_combo_shows_in_config(self):
        b = self.bridge_for(profiles.CYCLONE)
        vals = {addr: [0] * ln for addr, ln in profiles.CYCLONE.read_fields()}
        for _n, addr in profiles.CYCLONE.REMAP_SLOTS:
            vals[addr] = [0, 0, 0, 0]
        vals[0x00b2] = [0x01, WIN, LEFT, 0x00]
        self.assertEqual(b._build_config(vals)['remap']['L4'], cfg.pack_combo([WIN, LEFT]))


class ComboPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def picker(self, allow):
        engine = QQmlApplicationEngine()
        root = Path(__file__).resolve().parents[1]
        engine.addImportPath(str(root / 'qml'))
        bridge = GamesirBridge()
        engine.rootContext().setContextProperty('bridge', bridge)
        engine.loadData(b'import QtQuick\nimport App 1.0\nItem { id: r; width: 800; height: 600\n'
                        b'  property int last: -2\n'
                        b'  TargetPicker { objectName: "picker"; onPicked: function (c) { r.last = c } } }',
                        QUrl.fromLocalFile(str(root / 'qml' / 'probe.qml')))
        self.assertTrue(engine.rootObjects())
        win = engine.rootObjects()[0]
        tp = win.findChild(QObject, 'picker')
        tp.setProperty('allowCombos', allow)
        self.addCleanup(engine.deleteLater)
        self.keep = (engine, bridge)
        return win, tp

    @staticmethod
    def call(obj, name, value):
        QMetaObject.invokeMethod(obj, name, Q_ARG('QVariant', value))

    def test_modifiers_and_a_key_emit_one_packed_combo(self):
        win, tp = self.picker(True)
        tp.setProperty('mode', 'keyboard')
        self.call(tp, 'toggleMod', SHIFT); self.call(tp, 'toggleMod', CTRL)
        self.call(tp, 'choose', F12)
        self.assertEqual(win.property('last'), cfg.pack_combo([CTRL, SHIFT, F12]))

    def test_macros_never_get_combos(self):
        win, tp = self.picker(False)
        tp.setProperty('mode', 'keyboard')
        tp.setProperty('mods', [CTRL])
        self.call(tp, 'choose', F12)
        self.assertEqual(win.property('last'), F12)


if __name__ == '__main__':
    unittest.main()
