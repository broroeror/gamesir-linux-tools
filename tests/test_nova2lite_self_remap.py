"""N2 Lite stages self mappings in the same form that its firmware reads back."""
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


class MappingPad:
    """Emulate 0xF1 mapping commands, including Default read back as Self."""

    def __init__(self):
        self.mapping = {0xB4: 0xB5}  # A -> B
        self.replies = []
        self.writes = []

    def write(self, packet):
        payload = list(packet[1:])
        assert len(packet) == 65 and payload[0] == 0xF1
        mode, source = payload[1], payload[3]
        if mode:
            self.writes.append(payload[:8])
            self.mapping[source] = source if mode == 2 else payload[5]
        else:
            target = self.mapping.get(source, source)
            self.replies.append(list(n2l.frame_packet(
                [0xF1, 0, 9, source, 1, target, 0, 0], 9)[1:]))
        return len(packet)


class Nova2LiteSelfRemapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        old_profile = profiles.active()
        self.addCleanup(profiles.set_active, old_profile)
        state_patch = patch.dict(state, selected='n2l', driving='n2l',
                                 connected=True, profile=1, edit_profile=1)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        for name in ('_switch_sent_seq', '_switch_target'):
            switch_patch = patch.object(control, name, None)
            switch_patch.start()
            self.addCleanup(switch_patch.stop)
        profiles.set_active(profiles.NOVA_2_LITE)
        self.pad = MappingPad()
        control.set_device(self.pad)
        self.addCleanup(control.clear_device)
        self.bridge = GamesirBridge()
        self.addCleanup(self.bridge.deleteLater)
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()
        self.bridge._driving = 'n2l'
        self.bridge._loaded_profile = 1
        self.bridge._config = {'remap': {name: -1 for name, _ in n2l.REMAP_SLOTS}}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def stage(self, api, source, target):
        if api == 'name':
            self.bridge.setRemap(source, target)
        else:
            code = -1 if target == 'Default' else dict(n2l.GAMEPAD_TARGETS)[target]
            self.bridge.setRemapCode(source, code)

    def save(self, on_first_read=None):
        request_regs = control.request_regs
        first_read = True

        def request_and_pump(reqs):
            nonlocal first_read
            if first_read:
                first_read = False
                if on_first_read is not None:
                    on_first_read()
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

    def test_both_apis_normalize_all_self_targets_before_staging(self):
        targets = dict(n2l.GAMEPAD_TARGETS)
        for api in ('name', 'code'):
            for source, addr in n2l.REMAP_SLOTS:
                if source not in targets:
                    continue
                with self.subTest(api=api, source=source):
                    self.bridge._pending.clear()
                    self.bridge._config['remap'][source] = 0xFF
                    self.stage(api, source, source)
                    pending, = self.bridge._pending.values()
                    self.assertEqual(pending['addr'], addr)
                    self.assertEqual(pending['data'], [0, 0])
                    self.assertEqual(pending['display'], 'Default')
        self.assertEqual(self.pad.writes, [])

    def test_self_or_default_on_loaded_default_cancels_pending_edit(self):
        for api in ('name', 'code'):
            for target in ('A', 'Default'):
                with self.subTest(api=api, target=target):
                    self.stage(api, 'A', 'B')
                    self.assertEqual(self.bridge.pendingCount, 1)
                    self.stage(api, 'A', target)
                    self.assertEqual(self.bridge.pendingCount, 0)
                    self.stage(api, 'A', target)
                    self.assertEqual(self.bridge.pendingCount, 0)
        self.assertEqual(self.pad.writes, [])

    def test_custom_mapping_to_self_saves_and_verifies_with_both_apis(self):
        for api in ('name', 'code'):
            with self.subTest(api=api):
                self.pad.mapping[0xB4] = 0xB5
                self.pad.writes.clear()
                self.bridge._config['remap']['A'] = dict(n2l.GAMEPAD_TARGETS)['B']
                self.stage(api, 'A', 'A')
                self.assertEqual(self.pad.writes, [])
                self.assertIn('1/1 confirmed', self.save())
                self.assertEqual(self.pad.mapping[0xB4], 0xB4)
                self.assertEqual(self.pad.writes, [[0xF1, 2, 9, 0xB4, 0, 0, 0, 0]])
                self.assertEqual(self.bridge.config['remap']['A'], -1)
                self.assertEqual(self.bridge.pendingCount, 0)
                addr = dict(n2l.REMAP_SLOTS)['A']
                recovery = max(Path(self.tmp.name).rglob('before_apply_*.json'),
                               key=lambda path: path.stat().st_mtime_ns)
                before = json.loads(recovery.read_text())['profiles']['1']
                self.assertEqual(before[f'0x{addr:04x}']['bytes'], [1, 10])
                self.assertNotIn(f'0x{addr + 1:04x}', before)

    def test_self_or_default_selected_during_save_remains_pending_for_next_save(self):
        for api in ('name', 'code'):
            for target in ('A', 'Default'):
                with self.subTest(api=api, target=target):
                    self.pad.mapping[0xB4] = 0xB4
                    self.pad.writes.clear()
                    self.bridge._config['remap']['A'] = -1
                    self.stage(api, 'A', 'B')

                    def edit_during_save():
                        self.assertTrue(self.bridge._backup_busy)
                        self.stage(api, 'A', target)

                    self.assertIn('1/1 confirmed', self.save(edit_during_save))
                    self.assertEqual(self.pad.mapping[0xB4], 0xB5)
                    self.assertEqual(self.bridge.config['remap']['A'], 10)
                    self.assertEqual(self.bridge.pendingCount, 1)
                    pending, = self.bridge._pending.values()
                    self.assertEqual(pending['data'], [0, 0])

                    self.assertIn('1/1 confirmed', self.save())
                    self.assertEqual(self.pad.mapping[0xB4], 0xB4)
                    self.assertEqual(self.bridge.config['remap']['A'], -1)
                    self.assertEqual(self.bridge.pendingCount, 0)
                    self.assertEqual(self.pad.writes, [
                        [0xF1, 1, 9, 0xB4, 1, 0xB5, 0, 0],
                        [0xF1, 2, 9, 0xB4, 0, 0, 0, 0],
                    ])

    def test_other_targets_and_disabled_are_preserved(self):
        for api in ('name', 'code'):
            for target in ('B', 'Disabled'):
                with self.subTest(api=api, target=target):
                    self.stage(api, 'A', target)
                    pending, = self.bridge._pending.values()
                    self.assertEqual(pending['data'], [1, dict(n2l.GAMEPAD_TARGETS)[target]])
        self.assertEqual(self.pad.writes, [])

    def test_existing_cyclone_self_mapping_bytes_are_unchanged(self):
        profiles.set_active(profiles.CYCLONE)
        self.bridge._apply_profile(profiles.CYCLONE)
        for api in ('name', 'code'):
            with self.subTest(api=api):
                self.stage(api, 'A', 'A')
                pending, = self.bridge._pending.values()
                self.assertEqual(pending['data'], [1, 9])
        self.assertEqual(self.pad.writes, [])


if __name__ == '__main__':
    unittest.main()
