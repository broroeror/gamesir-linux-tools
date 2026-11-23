"""A claimed G7 Pro dongle whose pad goes quiet says so and holds Apply (#56).

Some dongles stay on USB with their pad off, so the session used to offer
settings whose Save could only time out. The real session loop runs here
against a fake dongle that streams telemetry, goes silent, then streams again.
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication

import controller_profile as profiles
import reader
from bridge import GamesirBridge
from gs_state import state
from vendors.gamesir.models.g7pro import protocol as g7

TELEMETRY = bytes([0x10, 0x00, 0x01, g7.RESPONSE_MARKER, g7.INPUT_MARKER] + [0] * 59)


class FakeDongle:
    """Streams telemetry while `pad_on` is set; otherwise reads time out."""

    def __init__(self):
        self.pad_on = threading.Event()

    def write(self, data):
        return len(data)

    def read(self, length=64, timeout_ms=120):
        if self.pad_on.is_set():
            time.sleep(0.01)
            return TELEMETRY
        time.sleep(timeout_ms / 1000)
        return b''

    def close(self):
        pass


def wait_for(cond, secs=3.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class PadAbsent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.old_state = dict(state)
        profiles.set_active(profiles.G7_PRO)

    def tearDown(self):
        state['config_wanted'] = False
        if getattr(self, 'thread', None):
            self.thread.join(3)
        state.clear()
        state.update(self.old_state)
        profiles.set_active(None)

    def _run(self, pid, pad_on=True):
        dongle = FakeDongle()
        if pad_on:
            dongle.pad_on.set()
        ctrl = {'id': 'g7', 'pid': pid, 'product': 'GameSir-G7 Pro',
                'usb': {'bus': 1, 'address': 2, 'sysfs': '/fake'}}
        state.update(selected='g7', config_wanted=True, edit_profile=1, profile=1)
        patches = [patch.object(g7, 'open_device', return_value=dongle),
                   patch.object(reader, '_rescan', return_value=[{'id': 'g7'}]),
                   patch.object(reader, '_G7_PAD_SILENCE', 0.3)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.thread = threading.Thread(target=reader.read_session_g7usb, args=(ctrl,),
                                       daemon=True)
        self.thread.start()
        return dongle

    def test_dongle_reports_a_quiet_pad_and_recovers(self):
        dongle = self._run(g7.PID_AMZ_DONGLE)
        self.assertTrue(wait_for(lambda: state.get('config_claimed')))
        time.sleep(0.5)                          # streaming: nothing to report
        self.assertFalse(state.get('g7_pad_absent'))
        self.assertEqual(state['config_status'], reader.G7_STATUS_CLAIMED)

        dongle.pad_on.clear()                    # the pad goes to sleep
        self.assertTrue(wait_for(lambda: state.get('g7_pad_absent')))
        self.assertEqual(state['config_status'], reader.G7_STATUS_NO_PAD)
        self.assertEqual(state['config_phase'], 'claimed')   # no Configure overlay
        self.assertTrue(state['config_claimed'])

        dongle.pad_on.set()                      # and comes back
        self.assertTrue(wait_for(lambda: not state.get('g7_pad_absent')))
        self.assertEqual(state['config_status'], reader.G7_STATUS_CLAIMED)

    def test_dongle_with_the_pad_already_off(self):
        self._run(g7.PID_ZZZ_DONGLE, pad_on=False)     # #56's dongle
        self.assertTrue(wait_for(lambda: state.get('g7_pad_absent')))

    def test_a_wired_pad_is_never_reported_absent(self):
        dongle = self._run(g7.PID_AMZ_WIRED)
        self.assertTrue(wait_for(lambda: state.get('config_claimed')))
        dongle.pad_on.clear()
        time.sleep(0.8)
        self.assertFalse(state.get('g7_pad_absent'))

    def test_release_clears_the_flag(self):
        self._run(g7.PID_AMZ_DONGLE, pad_on=False)
        self.assertTrue(wait_for(lambda: state.get('g7_pad_absent')))
        state['config_wanted'] = False
        self.thread.join(3)
        self.assertFalse(state.get('g7_pad_absent'))


class ApplyHeld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.old_state = dict(state)
        profiles.set_active(profiles.G7_PRO)
        state.update(profile=1, edit_profile=1, selected='t', driving='t',
                     config_claimed=True, g7_pad_absent=True)
        self.bridge = GamesirBridge()
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()

    def tearDown(self):
        self.bridge.deleteLater()
        state.clear()
        state.update(self.old_state)
        profiles.set_active(None)

    def test_apply_is_held_and_the_edit_kept(self):
        self.assertTrue(self.bridge.g7PadAbsent)
        self.bridge.setG7Extra('sleep_minutes', 5)
        with patch('vendors.gamesir.control.write_reg') as write:
            self.bridge.applyConfig()
            time.sleep(0.2)
            write.assert_not_called()
        self.assertIn("isn't answering", self.bridge.applyStatus)
        self.assertIn(('g7', 0x20, 'sleep_minutes'), self.bridge._pending)


if __name__ == '__main__':
    unittest.main()
