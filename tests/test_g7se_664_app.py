"""G7 SE firmware 6.64 through the bridge: staged edits save; no USB required."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer
from bridge import GamesirBridge
import controller_profile as profiles
from gs_state import state
from vendors.gamesir import control
from vendors.gamesir.models.g7se import protocol as se

BANK1 = bytes.fromhex((Path(__file__).parent / 'fixtures' / 'g7se_664_bank1.hex')
                      .read_text().replace('\n', ''))


class Se664AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        se.select(0x0664)
        profiles.apply_g7se_layout()
        self.old = profiles.active()
        profiles.set_active(profiles.G7_SE)
        self.patch = patch.dict(state, selected='se', driving='se', connected=True,
            profile=1, edit_profile=1, demo=False, config_claimed=True, config_wanted=True,
            usb_bcd=0x0664)
        self.patch.start()
        self.bridge = GamesirBridge()
        self.bridge._apply_profile(profiles.G7_SE)
        self.memory = bytearray(BANK1)
        self.wires = []

        def write(wire):
            self.wires.append(bytes(wire))
            if wire[3:5] == b'\x3c\x03' and wire[5] == 1:
                addr = int.from_bytes(wire[6:8], 'big')
                self.memory[addr:addr + wire[8]] = wire[9:9 + wire[8]]
            return len(wire)
        control.set_device(Mock(write=write))
        self.bridge._driving = 'se'
        self.bridge._loaded_profile = 1
        self.bridge._config_loading = None
        self.bridge._config_generation = control.generation()
        self.bridge._config = {'remap': {}, 'st_dz_min': 10}

    def tearDown(self):
        control.clear_device()
        profiles.set_active(self.old)
        self.patch.stop()
        for timer in self.bridge.findChildren(QTimer):
            timer.stop()
        self.bridge.deleteLater()
        se.select(0x0630)
        profiles.apply_g7se_layout()

    def save(self):
        def read(bank, addr):
            return list(self.memory[addr:addr + 56])
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, XDG_DATA_HOME=directory), \
                patch.object(control, 'request_regs'), \
                patch.object(control, 'reg_result', side_effect=read), \
                patch('bridge.threading.Thread',
                      side_effect=lambda target, **kwargs: Mock(start=target)):
            self.bridge.applyConfig()

    def test_scalar_curve_and_extra_edits_save(self):
        self.bridge.setScalar('st_dz_min', 30)
        self.bridge.setG7Extra('st_invert_y', 1)
        self.bridge.setCurve('st', 'Concave', [])
        self.assertEqual(self.bridge.pendingCount, 3)
        self.save()
        self.assertNotIn('refused', self.bridge._apply_status)
        self.assertEqual(self.bridge.pendingCount, 0)
        self.assertEqual(self.memory[0x013f], 30)
        self.assertEqual(self.memory[0x0152], 1)
        self.assertEqual(self.memory[0x0144], 1)                # Concave
        self.assertTrue(self.wires and all(se.allowed_app_request(w) for w in self.wires))

    def test_stale_session_stages_nothing(self):
        self.bridge._config_generation = None
        self.bridge.setScalar('st_dz_min', 30)
        self.assertEqual(self.bridge.pendingCount, 0)


if __name__ == '__main__':
    unittest.main()
