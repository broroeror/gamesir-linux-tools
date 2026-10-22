"""N2 Lite Save against the five vibration levels observed on firmware 1.82."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication

import controller_profile as profiles
from bridge import GamesirBridge
from gs_state import state
from vendors.gamesir import control
from vendors.gamesir.models.nova2lite import protocol as n2l


class FiveLevelPad:
    """Actual 0x25 framing, including the firmware's floor to a 25% step."""

    def __init__(self):
        self.levels = [75, 100]
        self.replies = []
        self.writes = []
        self.drop_writes = False

    def write(self, packet):
        payload = list(packet[1:])
        assert len(packet) == 65 and payload[:3] == [0x25, 0x01, 0x0D]
        if payload[3] == 1:
            self.writes.append((payload[4], payload[8]))
            if not self.drop_writes:
                self.levels[:] = [payload[4] // 25 * 25, payload[8] // 25 * 25]
        else:
            left, right = self.levels
            self.replies.append(list(n2l.frame_packet(
                [0x25, 1, 13, 0, left, 0, 0, 0, right, 0, 0, 0], 13)[1:]))
        return len(packet)


class Nova2LiteSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        old_profile = profiles.active()
        self.addCleanup(profiles.set_active, old_profile)
        self.state_patch = patch.dict(state, selected='n2l', driving='n2l',
                                      connected=True, profile=1, edit_profile=1)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        for name in ('_switch_sent_seq', '_switch_target'):
            switch_patch = patch.object(control, name, None)
            switch_patch.start()
            self.addCleanup(switch_patch.stop)
        profiles.set_active(profiles.NOVA_2_LITE)
        self.pad = FiveLevelPad()
        control.set_device(self.pad)
        self.addCleanup(control.clear_device)
        self.bridge = GamesirBridge()
        self.addCleanup(self.bridge.deleteLater)
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()
        self.bridge._driving = 'n2l'
        self.bridge._loaded_profile = 1
        self.bridge._config = {'vib_l': 75, 'vib_r': 100}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def save(self):
        request_regs = control.request_regs

        def request_and_pump(reqs):
            request_regs(reqs)
            while not control.reads_idle():
                control.pump_reads()
                self.assertTrue(self.pad.replies)
                self.assertTrue(control.store_t4n2_reply(self.pad.replies.pop(0)))

        with patch.dict(os.environ, XDG_DATA_HOME=self.tmp.name), \
             patch.object(control, 'request_regs', request_and_pump), \
             patch.object(control.time, 'sleep'), \
             patch.object(threading.Thread, 'start', lambda t: t.run()):
            self.bridge.applyConfig()
        return self.bridge.applyStatus

    def test_save_normalizes_both_motors_before_verified_transaction(self):
        self.bridge.setScalar('vib_l', 32)
        self.bridge.setScalar('vib_r', 64)
        self.assertEqual(self.pad.writes, [])
        self.assertIn('2/2 confirmed', self.save())
        self.assertEqual(self.pad.levels, [25, 75])
        self.assertEqual(self.bridge.config, {'vib_l': 25, 'vib_r': 75})
        self.assertEqual(self.bridge.pendingCount, 0)
        recovery, = Path(self.tmp.name).rglob('before_apply_*.json')
        before = json.loads(recovery.read_text())['profiles']['1']
        self.assertEqual(before['0x0020']['bytes'], [75])
        self.assertEqual(before['0x0021']['bytes'], [100])

    def test_one_motor_save_preserves_other_motor_and_can_save_again(self):
        for value in (0, 25, 50, 75, 100):
            self.bridge.setScalar('vib_l', value)
            self.assertIn('1/1 confirmed', self.save())
            self.assertEqual(self.pad.levels, [value, 100])
            self.assertEqual(self.bridge.pendingCount, 0)

    def test_drag_back_to_loaded_level_cancels_pending_edit(self):
        self.bridge.setScalar('vib_l', 32)
        self.assertEqual(self.bridge.pendingCount, 1)
        self.bridge.setScalar('vib_l', 64)  # nearest supported level is the loaded 75
        self.assertEqual(self.bridge.pendingCount, 0)
        self.assertEqual(self.pad.writes, [])

    def test_real_readback_mismatch_still_fails_and_keeps_pending_edits(self):
        self.bridge.setScalar('vib_l', 32)
        self.pad.drop_writes = True
        status = self.save()
        self.assertIn('read-back mismatch at 0x0020', status)
        self.assertIn('original settings restored and verified', status)
        self.assertEqual(self.pad.levels, [75, 100])
        self.assertEqual(self.bridge.pendingCount, 1)
        self.assertEqual(self.bridge.config, {'vib_l': 75, 'vib_r': 100})


if __name__ == '__main__':
    unittest.main()
