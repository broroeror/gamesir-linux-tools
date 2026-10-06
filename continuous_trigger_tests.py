"""Cyclone flag, profile and recovery checks; all hardware is blocked."""
import copy
import ast
import json
import os
import tempfile
import types
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch

import sys

def forbidden(*args, **kwargs):
    raise AssertionError('hardware access forbidden in Continuous Trigger tests')

hid = types.ModuleType('hid')
hid.device = hid.enumerate = forbidden
sys.modules['hid'] = hid
from gs_state import state
import backup
import controller_profile as profiles
import register_transaction
from vendors.gamesir import config as cfg, control
class Wire:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(bytes(frame))
        return len(frame)


# Independent offsets calculated from the official C2 profile layout:
# name32 + basic32 + normal16*7 + paddles2*159 + triggers2*28.
EXPECTED = {
    'Dpad Up': 0x0046, 'Dpad Down': 0x004d, 'Dpad Left': 0x0054,
    'Dpad Right': 0x005b, 'LB': 0x0062, 'RB': 0x0069, 'LS': 0x0070,
    'RS': 0x0077, 'A': 0x007e, 'B': 0x0085, 'X': 0x008c, 'Y': 0x0093,
    'L4': 0x00b6, 'R4': 0x0155, 'LT': 0x01f9, 'RT': 0x0215,
    'View': 0x00a1, 'Menu': 0x00a8, 'Capture': 0x00af,
}


class ContinuousTriggerTests(unittest.TestCase):
    def setUp(self):
        original_state = copy.deepcopy(state)
        original_profile, recognized = profiles.active(), profiles.is_recognized()
        self.addCleanup(lambda: state.update(original_state))
        self.addCleanup(lambda: profiles.set_active(original_profile if recognized else None))
        profiles.set_active(profiles.CYCLONE)
        state.update(connected=True, driving='offline-unit', selected='offline-unit',
                     controller='Cyclone 2', profile=1, edit_profile=1)
        self.gen = patch.object(control, 'generation', return_value=71)
        self.gen.start()
        self.addCleanup(self.gen.stop)
        # Use the actual bridge methods on platforms without Qt. The separate
        # Linux UI harness loads the complete QObject and real QML.
        tree = ast.parse((Path(__file__).parent / 'bridge.py').read_text(encoding='utf-8'))
        names = {'_apply_profile', '_build_config', '_queue', 'hasContinuousTrigger',
                 'setContinuousTrigger', 'applyConfig', '_apply_cyclone_config', '_fold'}
        constants = {'_SCALAR_FIELDS', '_CURVE_FIELDS', '_TRAJ_FIELDS', '_HAIR_FIELDS'}
        assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)]
        methods = [copy.deepcopy(n) for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({m.name for m in methods}, names)
        for method in methods:
            method.decorator_list = []
        wrapper = ast.Module(body=assignments + [ast.ClassDef(
            name='BridgeHarness', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        scope = dict(copy=copy, os=os, time=time, threading=threading, cfg=cfg,
                     profiles=profiles, state=state, control=control, backup=backup,
                     register_transaction=register_transaction)
        exec(compile(ast.fix_missing_locations(wrapper), 'bridge.py', 'exec'), scope)
        self.pad = scope['BridgeHarness']()
        self.pad._apply_profile(profiles.CYCLONE)
        self.pad._backup_busy = self.pad._macro_loading = False
        self.pad._config_loading = None
        self.pad._pending = {}
        self.pad._m_dirty = False
        self.pad._m = {}
        self.pad._m_loaded = {}
        self.pad._set_apply_status = lambda msg: setattr(self.pad, 'applyStatus', msg)
        for signal in ('pendingChanged', 'configLoaded', 'backupBusyChanged'):
            setattr(self.pad, signal, types.SimpleNamespace(emit=lambda: None))
        self.pad._driving = 'offline-unit'
        self.pad._loaded_profile = self.pad._macro_profile = 1
        self.pad._config_generation = 71
        self.pad._macros = {name: {'enable': False, 'events': []}
                            for name, _addr in profiles.CYCLONE.MACRO_SLOTS}
        self.memory = bytearray((i * 17) % 256 for i in range(680))
        for addr in EXPECTED.values():
            self.memory[addr] = 0
        vals = {addr: list(self.memory[addr:addr + length])
                for addr, length in profiles.CYCLONE.read_fields()}
        vals.update({addr: list(self.memory[addr:addr + 2])
                     for _name, addr in profiles.CYCLONE.REMAP_SLOTS})
        self.pad._config = self.pad._build_config(vals)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.writes = []

    def apply(self, write=None):
        requests = {}
        def request(reqs):
            requests.update({(bank, addr): length for bank, addr, length in reqs})
        def read(bank, addr):
            length = requests[(bank, addr)]
            return list(self.memory[addr:addr + length])
        def default_write(bank, addr, data, **kwargs):
            self.writes.append((bank, addr, list(data)))
            self.memory[addr:addr + len(data)] = bytes(data)
            return True
        def thread(*, target, **kwargs):
            return types.SimpleNamespace(start=target)
        with patch.object(threading, 'Thread', side_effect=thread), \
             patch.object(time, 'sleep'), patch.object(control, 'request_regs', side_effect=request), \
             patch.object(control, 'reg_result', side_effect=read), \
             patch.object(control, 'write_reg', side_effect=write or default_write), \
             patch.object(control, 'send_cmd', return_value=True), \
             patch.dict(os.environ, {'XDG_DATA_HOME': self.temp.name}):
            self.pad.applyConfig()

    def test_official_c2_offsets_and_one_byte_wire_frames(self):
        self.assertEqual(dict(profiles.CYCLONE.CONTINUOUS_TRIGGER_SLOTS), EXPECTED)
        self.assertEqual({n for n, _ in profiles.CYCLONE.REMAP_SLOTS}, set(EXPECTED))
        self.assertNotIn('Home', EXPECTED)
        self.assertEqual({n: c for n, c in profiles.CYCLONE.REMAP_TARGETS
                          if n in ('View', 'Menu', 'Capture')},
                         {'View': 14, 'Menu': 15, 'Capture': 16})
        wire = Wire()
        control.set_device(wire)
        try:
            for bank in (1, 2, 3, 4):
                for name, addr in EXPECTED.items():
                    for value in (1, 0):
                        self.assertTrue(control.write_reg(bank, addr, [value], write_style='cyclone'))
                        expected = bytes([15, 3, bank, addr >> 8, addr & 255, 1, value]) + bytes(57)
                        self.assertEqual(wire.frames[-1], expected, name)
        finally:
            control.clear_device()

    def test_missing_short_unknown_and_boolean_flags_are_not_assumed_off(self):
        for raw in (None, [], [0, 0], [2], [0x80], [255], [True]):
            self.assertEqual(cfg.continuous_trigger_state(raw), -1)
        self.assertEqual(cfg.continuous_trigger_state([0]), 0)
        self.assertEqual(cfg.continuous_trigger_state([1]), 1)

    def test_all_sources_stage_only_their_flag_in_the_edit_profile(self):
        state['edit_profile'] = self.pad._loaded_profile = self.pad._macro_profile = 3
        for name, addr in EXPECTED.items():
            self.assertTrue(self.pad.setContinuousTrigger(name, True), name)
            entry = self.pad._pending[(3, addr)]
            self.assertEqual(entry['data'], [1])
            self.assertEqual(entry['generation'], 71)
        self.assertEqual(len(self.pad._pending), 19)
        self.assertEqual(self.writes, [])

    def test_other_controller_models_have_no_cyclone_toggle_map(self):
        for prof in (profiles.G7_PRO, profiles.G7_8K):
            self.pad._apply_profile(prof)
            self.assertFalse(self.pad.hasContinuousTrigger())
            self.assertFalse(self.pad.setContinuousTrigger('L4', True))

    def test_wrong_profile_loading_unknown_and_switched_device_refused(self):
        cases = (
            ('unknown', lambda: self.pad._config['continuous_trigger'].update(A=-1)),
            ('loading', lambda: setattr(self.pad, '_config_loading', 1)),
            ('profile', lambda: state.update(edit_profile=2)),
            ('selected', lambda: state.update(selected='other')),
            ('rebound', lambda: state.update(driving='other', selected='other')),
            ('generation', lambda: setattr(self.pad, '_config_generation', 70)),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                mutate()
                self.assertFalse(self.pad.setContinuousTrigger('A', True))
                self.assertFalse(self.pad._pending)
                self.pad._config['continuous_trigger']['A'] = 0
                self.pad._config_loading = None
                self.pad._config_generation = 71
                state.update(edit_profile=1, driving='offline-unit', selected='offline-unit')

    def test_active_or_unread_paddle_macro_refused(self):
        self.pad._macros['L4']['enable'] = True
        self.assertFalse(self.pad.setContinuousTrigger('L4', True))
        self.pad._macros['L4']['enable'] = False
        self.pad._macro_profile = None
        self.assertFalse(self.pad.setContinuousTrigger('L4', True))
        self.pad._macro_profile = 1
        self.assertTrue(self.pad.setContinuousTrigger('L4', True))

    def test_save_and_disable_preserve_every_other_profile_byte(self):
        before = bytes(self.memory)
        self.assertTrue(self.pad.setContinuousTrigger('L4', True))
        self.apply()
        expected = bytearray(before)
        expected[0xb6] = 1
        self.assertEqual(self.memory, expected)
        self.assertIn('Applied and verified', self.pad.applyStatus)
        directory = os.path.join(self.temp.name, 'deadband', 'controller-backups')
        paths = os.listdir(directory)
        self.assertEqual(len(paths), 1)
        with open(os.path.join(directory, paths[0])) as f:
            saved = json.load(f)
        self.assertEqual(saved['profiles']['1']['0x00b6']['bytes'], [0])
        # Simulate the required fresh profile read after Save.
        self.pad._loaded_profile = 1
        self.pad._config['continuous_trigger']['L4'] = 1
        self.assertTrue(self.pad.setContinuousTrigger('L4', False))
        self.apply()
        self.assertEqual(bytes(self.memory), before)

    def test_snapshot_plan_and_restore_allow_only_the_flag_byte(self):
        fields = backup._profile_fields()
        self.assertIn((0x215, 1, 'Continuous Trigger RT'), fields)
        backup._validate_writes([(4, 0x215, [1])])
        with self.assertRaises(ValueError):
            backup._validate_writes([(4, 0x214, [99, 1])])

    def test_new_unknown_firmware_value_at_apply_refused_without_writes(self):
        self.assertTrue(self.pad.setContinuousTrigger('RT', True))
        self.memory[0x215] = 128
        self.apply()
        self.assertEqual(self.writes, [])
        self.assertEqual(self.memory[0x215], 128)
        self.assertIn('unknown Continuous Trigger flag', self.pad.applyStatus)

    def test_profile_or_session_change_between_stage_and_save_refused(self):
        self.assertTrue(self.pad.setContinuousTrigger('RT', True))
        with patch.object(control, 'generation', return_value=72):
            self.apply()
        self.assertFalse(self.writes)
        state['edit_profile'] = 2
        self.apply()
        self.assertFalse(self.writes)

    def test_durable_backup_failure_prevents_the_flag_write(self):
        self.assertTrue(self.pad.setContinuousTrigger('LT', True))
        with patch('register_transaction.os.replace', side_effect=OSError('disk full')):
            self.apply()
        self.assertFalse(self.writes)
        self.assertIn('disk full', self.pad.applyStatus)

    def test_dropped_flag_write_recovers_and_keeps_staged_edit(self):
        self.assertTrue(self.pad.setContinuousTrigger('R4', True))
        before = bytes(self.memory)
        self.apply(write=lambda *a, **k: True)
        self.assertEqual(bytes(self.memory), before)
        self.assertIn('restored and verified', self.pad.applyStatus)
        self.assertEqual(len(self.pad._pending), 1)

    def test_remap_and_toggle_are_verified_as_one_batch(self):
        before = bytes(self.memory)
        self.pad._queue(0x7a, [1, 20], 'Rebind A', 'RT')
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        self.apply()
        expected = bytearray(before)
        expected[0x7a:0x7c] = bytes([1, 20])
        expected[0x7e] = 1
        self.assertEqual(self.memory, expected)
        self.assertFalse(self.pad._pending)

    def test_failed_second_write_recovers_the_prior_remap_too(self):
        before = bytes(self.memory)
        self.pad._queue(0x7a, [1, 20], 'Rebind A', 'RT')
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        def write(bank, addr, data, **kwargs):
            self.writes.append((bank, addr, list(data)))
            if addr == 0x7e and data == [1]:
                return False
            self.memory[addr:addr + len(data)] = bytes(data)
            return True
        self.apply(write=write)
        self.assertEqual(bytes(self.memory), before)
        self.assertIn('restored and verified', self.pad.applyStatus)
        self.assertEqual(len(self.pad._pending), 2)

    def test_selection_change_after_staging_refuses_the_batch(self):
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        state['selected'] = 'another-controller'
        self.apply()
        self.assertFalse(self.writes)
        self.assertEqual(len(self.pad._pending), 1)

    def test_saved_motion_becomes_the_discard_baseline(self):
        self.pad._m = {'aim': {'enabled': True}}
        self.pad._m_dirty = True
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        self.apply()
        self.assertEqual(self.pad._m_loaded, self.pad._m)
        self.assertFalse(self.pad._m_dirty)

    def test_edit_during_apply_keeps_new_motion_and_flag_staged(self):
        self.pad._m = {'aim': {'enabled': True}}
        self.pad._m_dirty = True
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        def write(bank, addr, data, **kwargs):
            self.memory[addr:addr + len(data)] = bytes(data)
            self.pad._m['aim']['enabled'] = False
            self.pad._pending[(bank, addr)]['data'] = [0]
            return True
        self.apply(write=write)
        self.assertEqual(self.pad._m_loaded, {'aim': {'enabled': True}})
        self.assertTrue(self.pad._m_dirty)
        self.assertEqual(self.pad._pending[(1, 0x7e)]['data'], [0])
        self.assertEqual(self.pad._loaded_profile, 1)
        self.assertEqual(self.pad._config['continuous_trigger']['A'], 1)

    def test_model_changed_after_staging_refuses_the_batch(self):
        self.assertTrue(self.pad.setContinuousTrigger('A', True))
        profiles.set_active(profiles.G7_PRO)
        self.apply()
        self.assertFalse(self.writes)
        self.assertEqual(len(self.pad._pending), 1)


if __name__ == '__main__':
    unittest.main()
