"""G7 Pro gyro capture, profile routing and neighbouring-storage regressions."""
import copy
import os
import struct
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
import controller_profile as profiles
import backup
from bridge import GamesirBridge
from gs_state import state
from vendors.gamesir import control, motion
from vendors.gamesir.models.g7pro import protocol as g7


# Motion storage read from USB 3537:10a7, firmware 5.41, profile 1.
CAPTURE = bytes.fromhex(
    '01 ff 03 01 00 64 00 64 01 00 64 00 00 29 29 80 80 d6 d6 '
    'ff ff 01 00 00 00 32 32 01 00 ff ff ff ff ff '
    '00 ff 02 01 05 64 00 64 01 00 64 00 00 28 29 81 80 d7 d6 '
    'ff ff 01 00 00 00 32 32 00 00 ff ff ff ff ff')


def captured_blob():
    blob = bytearray(g7.PROFILE_BLOB_SIZE)
    blob[0x19c:0x19c + len(CAPTURE)] = CAPTURE
    return blob


def read_values(mp, blob):
    return {a: list(blob[a:a + size]) for a, size in motion.read_addrs(mp)}


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.old_state = dict(state)
        profiles.set_active(profiles.G7_PRO)
        state.update(profile=3, edit_profile=1, selected='test', driving='test',
                     config_claimed=True)
        self.bridge = GamesirBridge()
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()
        mp = g7.MOTION_MAP
        vals = read_values(mp, captured_blob())
        self.bridge._m = {n: motion.decode_section(mp, vals, off) for n, off in motion.sections(mp)}
        self.bridge._m_loaded = copy.deepcopy(self.bridge._m)
        self.bridge._m_profile = 1

    def tearDown(self):
        self.bridge.deleteLater()
        state.clear()
        state.update(self.old_state)
        profiles.set_active(None)

    def test_capture_decodes_real_curve_points_and_axis_codes(self):
        aim = self.bridge.motionAim
        self.assertEqual(aim['xaxis'], 1)  # code 03 = Yaw + Roll, not Roll alone
        self.assertEqual(aim['curve_points'], [[41, 41], [128, 128], [214, 214]])
        self.assertEqual(aim['act_slots'], [255])
        self.assertEqual(aim['xy_scale'], 50)
        self.assertEqual(aim['output'], 0)
        self.assertEqual(self.bridge.motionTilt['dz_min'], 5)
        self.assertEqual(self.bridge.motionTilt['xaxis'], -1)
        self.assertEqual(self.bridge.motionTilt['output'], -1)
        self.assertEqual(self.bridge.motionXAxisModes, ['Yaw', 'Yaw + Roll'])

    def test_sensor_parser_decodes_signed_little_endian_axes(self):
        report = bytearray(64)
        report[0], report[3], report[4] = 0x10, g7.RESPONSE_MARKER, g7.INPUT_MARKER
        struct.pack_into('<6h', report, 17, -32768, -1, 32767, -1234, 8192, 0)
        with patch.object(g7.time, 'monotonic', return_value=100):
            self.assertTrue(g7.parse_input(report, state))
        self.assertEqual(state['gyro'], (-32768, -1, 32767))
        self.assertEqual(state['accel'], (-1234, 8192, 0))
        self.assertEqual(state['imu_time'], 100)
        for invalid in (report[:28], report[:60], bytearray(64)):
            self.assertFalse(g7.parse_input(invalid, state))
        report[4] = 0x05  # configuration reply, not a sensor sample
        with patch.object(g7.time, 'monotonic', return_value=101):
            self.assertFalse(g7.parse_input(report, state))
        self.assertEqual(state['imu_time'], 100)

    def test_captured_wired_10a7_stationary_frame_keeps_gravity_out_of_gyro(self):
        # Real 64-byte frame captured on 10a7/fw 5.41 while lying flat.
        report = bytes.fromhex(
            '1000953ce0808080800f00000000000000fbff01000200f5fe03210d0b00000000'
            '64000000000000000000000000008f5268d4837c82800f0000000000000000')
        self.assertEqual(len(report), 64)
        with patch.object(g7.time, 'monotonic', return_value=100):
            self.assertTrue(g7.parse_input(report, state))
            self.bridge._poll_sensors()
        self.assertEqual(self.bridge.motionSensors['gyro'], [-5, 1, 2])
        self.assertEqual(self.bridge.motionSensors['accel'], [-267, 8451, 2829])
        self.assertTrue(self.bridge.motionSensors['available'])

    def test_sensor_display_clears_stale_or_released_samples_and_is_read_only(self):
        state.update(gyro=(0, 0, 0), accel=(-1, 2, 8192), imu_time=100)
        notifications = []
        self.bridge.motionSensorsChanged.connect(lambda: notifications.append(True))
        with patch.object(control, 'write_reg') as write, \
             patch('bridge.time.monotonic', return_value=100.1):
            self.bridge._poll_sensors()
            self.bridge._poll_sensors()  # unchanged values don't repaint
            self.assertEqual(len(notifications), 1)
            self.assertEqual(self.bridge.motionSensors['gyro'], [0, 0, 0])
            self.assertTrue(self.bridge.motionSensors['available'])
            write.assert_not_called()
        with patch('bridge.time.monotonic', return_value=100.6):
            self.bridge._poll_sensors()
        self.assertEqual(self.bridge.motionSensors, {'available': False, 'gyro': [], 'accel': []})
        with patch('bridge.time.monotonic', return_value=100.1):
            self.bridge._poll_sensors()
            state['config_claimed'] = False
            self.bridge._poll_sensors()
        self.assertFalse(self.bridge.motionSensors['available'])
        self.assertEqual(self.bridge._pending, {})

    def test_sensor_values_from_other_device_or_model_are_never_shown(self):
        state.update(gyro=(1, 2, 3), accel=(4, 5, 6), imu_time=100)
        with patch('bridge.time.monotonic', return_value=100.1):
            state['selected'] = 'other'
            self.bridge._poll_sensors()
            self.assertFalse(self.bridge.motionSensors['available'])
            state['selected'] = 'test'
            profiles.set_active(profiles.CYCLONE)
            self.bridge._poll_sensors()
            self.assertFalse(self.bridge.motionSensors['available'])

    def test_tilt_yaw_exception_never_reads_or_writes_sensitivity_neighbour(self):
        reads = dict(motion.read_addrs(g7.MOTION_MAP))
        self.assertIn(0x1d4, reads)
        self.assertNotIn(0x1d6, reads)
        self.bridge.setMotionInvert('Tilt', 2, True)
        self.assertEqual(self.bridge._pending[(1, 0x1d4)]['data'], [1])
        self.bridge.setMotionInvert('Tilt', 0, True)  # no Tilt roll field
        self.assertEqual(len(self.bridge._pending), 1)

    def test_every_gyro_edit_targets_edited_profile_and_is_staged(self):
        with patch.object(control, 'write_reg') as write:
            self.bridge.setMotionEnum('Aim', 'act_method', 1)
            self.bridge.setMotionEnum('Aim', 'xaxis', 1)
            self.bridge.setMotionEnum('Aim', 'output', 3)
            self.bridge.setMotionValue('Tilt', 'overlap_area', 37)
            self.bridge.setMotionDeadzone('Tilt', 'dz_min', 12)
            self.bridge.setMotionDir('Tilt', 0, 0x09)
            write.assert_not_called()
        self.assertEqual({v['bank'] for v in self.bridge._pending.values()}, {1})
        self.assertEqual(self.bridge._pending[(1, 0x19e)]['data'], [3])
        self.assertEqual(self.bridge._pending[(1, 0x1da)]['data'], [37])
        self.assertEqual(self.bridge._pending[(1, 0x1c2)]['data'], [12])
        self.assertEqual(self.bridge._pending[(1, 0x1db)]['data'], [9])

    def test_range_sensitivity_stages_only_upper_endpoint_and_discard_restores(self):
        self.bridge._m['Aim']['output'] = 1  # Right Stick
        self.bridge._m_loaded = copy.deepcopy(self.bridge._m)
        before = copy.deepcopy(self.bridge.motionAim)
        with patch.object(control, 'write_reg') as write:
            self.assertEqual(self.bridge.setMotionRangeSensitivity('Aim', 2.0), 50)
            write.assert_not_called()
        expected = dict(before, dz_max=50)
        self.assertEqual(self.bridge.motionAim, expected)
        self.assertEqual(set(self.bridge._pending), {(1, 0x1a1)})
        self.assertEqual(self.bridge._pending[(1, 0x1a1)]['data'], [50])
        self.bridge.discardConfig()
        self.assertEqual(self.bridge.motionAim, before)
        self.assertEqual(self.bridge._pending, {})

    def test_range_sensitivity_preserves_lower_deadzone_and_routes_tilt(self):
        self.bridge._m['Tilt']['output'] = 0  # Left Stick
        before = copy.deepcopy(self.bridge.motionTilt)
        high = self.bridge.setMotionRangeSensitivity('Tilt', 2.0)
        self.assertEqual(high, 53)  # 5 + round(95 / 2), integer percentage
        self.assertEqual(self.bridge.motionTilt, dict(before, dz_max=high))
        self.assertEqual(set(self.bridge._pending), {(1, 0x1c3)})
        self.assertAlmostEqual(motion.range_sensitivity(5, high), 95 / 48)
        self.assertIsNone(motion.range_sensitivity(5, 5))
        self.assertIsNone(motion.range_sensitivity(100, 100))
        self.assertEqual(motion.sensitivity_dz_max(99, 10), 100)
        self.assertEqual(motion.sensitivity_dz_max(0, 1000), 1)
        self.assertEqual(motion.sensitivity_dz_max(5, 0), 100)

    def test_range_sensitivity_rejects_unloaded_unsupported_and_invalid_inputs(self):
        before = copy.deepcopy(self.bridge._m)
        for output in (2, 3, -1):  # Button Binds, Mouse, unknown
            self.bridge._m['Aim']['output'] = output
            self.assertEqual(self.bridge.setMotionRangeSensitivity('Aim', 2.0), -1)
        self.bridge._m = before
        for value in (float('nan'), float('inf'), float('-inf')):
            self.assertEqual(self.bridge.setMotionRangeSensitivity('Aim', value), -1)
        self.assertEqual(self.bridge.setMotionRangeSensitivity('Unknown', 2.0), -1)
        self.assertEqual(self.bridge._m, before)
        self.assertEqual(self.bridge._pending, {})
        self.bridge._m.clear()
        self.assertEqual(self.bridge.setMotionRangeSensitivity('Aim', 2.0), -1)
        profiles.set_active(profiles.G7_8K)
        self.bridge._prof = profiles.G7_8K
        self.assertFalse(self.bridge.motionHasRangeSensitivity)
        self.assertEqual(self.bridge.setMotionRangeSensitivity('Aim', 2.0), -1)

    def test_activation_button_can_be_replaced_and_direction_cleared(self):
        self.bridge.setMotionButton('Aim', 0x13, True)
        self.bridge.setMotionButton('Aim', 0x1f, True)
        self.assertEqual(self.bridge.motionAim['act_slots'], [0x1f])
        self.bridge.setMotionButton('Aim', 0x1f, False)
        self.assertEqual(self.bridge._pending[(1, 0x19d)]['data'], [255])
        self.bridge.setMotionDir('Aim', 0, -1)
        self.assertEqual(self.bridge._pending[(1, 0x1b9)]['data'], [255])

    def test_curve_presets_match_captures_and_custom_preserves_points(self):
        for idx, expected in enumerate((
                '0064000028288081d7d7', '016400005e17ae4fe8a2', '02640000284c8081d7b3')):
            self.bridge.setMotionCurveType('Tilt', idx)
            self.assertEqual(bytes(self.bridge._pending[(1, 0x1c7)]['data']).hex(), expected)
        pts = copy.deepcopy(self.bridge._m_loaded['Tilt']['curve_points'])
        self.bridge.setMotionCurveType('Tilt', 3)
        self.assertEqual(self.bridge._pending[(1, 0x1c7)]['data'], [3])
        self.bridge.setMotionCurveStrength('Tilt', 42)
        self.bridge.setMotionCurvePoint('Tilt', 0, 99, 100)
        self.assertEqual(self.bridge.motionTilt['curve_points'], pts)
        self.assertEqual(self.bridge._pending[(1, 0x1c7)]['data'], [3])

    def test_deadzone_writes_preserve_live_neighbouring_settings(self):
        for addr in (0x1a0, 0x1a1, 0x1a2, 0x1a3, 0x1c2, 0x1c3, 0x1c4, 0x1c5):
            with self.subTest(addr=hex(addr)):
                storage = bytearray(range(256)) * 2
                original = bytes(storage)
                def read(bank, start, length, gen=None):
                    self.assertEqual(bank, 4)
                    return list(storage[start:start + length])
                def write(bank, start, data, gen=None):
                    storage[start:start + len(data)] = bytes(data)
                    return True
                with patch.object(control, 'g7_heartbeat', return_value=True), \
                     patch.object(control, 'read_reg_sync', side_effect=read) as reads, \
                     patch.object(control, '_g7_addressed', side_effect=write), \
                     patch.object(control.time, 'sleep'):
                    self.assertTrue(control.write_reg(4, addr, [17], write_style='g7'))
                reads.assert_called_once_with(4, addr + 1, g7.LONG_SUFFIX[addr], gen=None)
                expected = bytearray(original)
                expected[addr] = 17
                self.assertEqual(storage, expected)

    def test_profile_change_clears_pending_motion_and_reloads_edited_bank(self):
        self.bridge.setMotionEnum('Aim', 'act_method', 3)
        self.bridge.setProfile(2)
        self.assertEqual(self.bridge._pending, {})
        self.assertEqual(self.bridge.motionAim, {})
        with patch.object(control, 'request_regs') as req, \
             patch.object(control, 'reg_result', return_value=None):
            self.bridge._poll_motion()
        self.assertEqual({r[0] for r in req.call_args.args[0]}, {2})

    def test_legacy_models_keep_their_motion_enums_and_point_offsets(self):
        for profile in (profiles.CYCLONE, profiles.G7_8K, profiles.TARANTULA_PRO_8K):
            mp = profile.motion
            blob = bytes([1]) * 4096
            vals = read_values(mp, blob)
            aim = motion.decode_section(mp, vals, 0)
            self.assertEqual(motion.enum_table(mp, 'xaxis'), motion.XAXIS_MODES)
            self.assertEqual(aim['curve_points'], [[1, 1]] * mp['curve_npts'])
            self.assertEqual(len(motion.curve_payload(mp, 1)), 2 + 2 * mp['curve_npts'])

    def test_legacy_motion_edits_keep_original_encodings_and_capabilities(self):
        for profile in (profiles.CYCLONE, profiles.G7_8K, profiles.TARANTULA_PRO_8K):
            with self.subTest(model=profile.name):
                profiles.set_active(profile)
                self.bridge._apply_profile(profile)
                mp = profile.motion
                vals = read_values(mp, bytes([1]) * 4096)
                for _, off in motion.sections(mp):
                    vals[mp['curve'] + 1 + off] = [100]
                self.bridge._m = {n: motion.decode_section(mp, vals, off)
                                  for n, off in motion.sections(mp)}
                self.bridge._m_loaded = copy.deepcopy(self.bridge._m)
                self.bridge._pending.clear()
                with patch.object(control, 'write_reg') as write:
                    self.bridge.setMotionEnum('Aim', 'xaxis', 0)
                    self.bridge.setMotionEnum('Aim', 'output', 1)
                    self.bridge.setMotionDeadzone('Aim', 'dz_max', 73)
                    self.bridge.setMotionInvert('Tilt', 1, True)
                    self.bridge.setMotionDir('Tilt', 2, -1)
                    self.bridge.setMotionCurveType('Aim', 1)
                    write.assert_not_called()
                pending = self.bridge._pending
                self.assertEqual(pending[(1, mp['xaxis'])]['data'], [2])
                self.assertEqual(pending[(1, mp['output'])]['data'], [2])
                self.assertEqual(pending[(1, mp['dz_max'])]['data'],
                                 [2, 218] if mp['dz_wide'] else [73])
                self.assertEqual(pending[(1, mp['inverts'][1][1] + mp['tilt_offset'])]['data'], [1])
                self.assertEqual(pending[(1, mp['dir_macros'][2] + mp['tilt_offset'])]['data'], [0])
                points = ([94, 23, 176, 79, 232, 161] if profile is profiles.CYCLONE
                          else [64, 10, 122, 38, 176, 79, 217, 133, 245, 191])
                self.assertEqual(pending[(1, mp['curve'])]['data'], [1, 100] + points)
                self.assertFalse(self.bridge.motionHasRangeSensitivity)
                self.assertFalse(self.bridge.motionHasOverlap)
                self.assertTrue(self.bridge.motionHasCurveStrength)
                self.assertEqual(self.bridge.motionDirectionEmpty, 0)
                self.assertEqual(self.bridge.motionHasSens, profile is not profiles.CYCLONE)

    def test_motion_page_keeps_legacy_controls_and_hides_g7_additions(self):
        from PySide6.QtCore import QObject
        root = Path(__file__).resolve().parents[1]
        for profile in (profiles.CYCLONE, profiles.G7_8K, profiles.TARANTULA_PRO_8K):
            with self.subTest(model=profile.name):
                profiles.set_active(profile)
                self.bridge._apply_profile(profile)
                mp = profile.motion
                vals = read_values(mp, bytes([1]) * 4096)
                self.bridge._m = {n: motion.decode_section(mp, vals, off)
                                  for n, off in motion.sections(mp)}
                engine = QQmlApplicationEngine()
                engine.addImportPath(str(root / 'qml'))
                engine.rootContext().setContextProperty('bridge', self.bridge)
                errors = []
                engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
                engine.load(QUrl.fromLocalFile(str(root / 'qml/App/MotionPage.qml')))
                self.assertTrue(engine.rootObjects(), errors)
                page = engine.rootObjects()[0]
                self.assertFalse(page.property('rangeSensitivityVisible'))
                self.assertFalse(page.findChild(QObject, 'motionSensors').property('visible'))
                self.assertEqual(self.bridge.motionXAxisModes, ['Yaw', 'Roll', 'Both'])
                page.setProperty('sec', 1)
                self.assertEqual(page.property('section'), 'Tilt')
                self.assertEqual(errors, [])
                page.deleteLater()
                engine.deleteLater()

    def test_motion_backup_validates_before_writing_and_legacy_backups_work(self):
        blob = captured_blob()
        decoded = g7.decode_profile(blob)
        data = {'device': profiles.G7_PRO.name,
                'profiles': {str(b): copy.deepcopy(decoded) for b in range(1, 5)},
                'device_settings': {'dock_auto': False, 'dock_brightness': 0}}
        writes = backup._g7_writes_from(data)
        self.assertIn((4, 0x1c7, list(blob[0x1c7:0x1d1])), writes)
        self.assertIn((4, 0x1d4, [0]), writes)
        self.assertNotIn((4, 0x1d6, [0]), writes)
        data['profiles']['1']['motion']['Tilt']['xaxis'] = 255
        with self.assertRaises(ValueError):
            backup._g7_writes_from(data)
        for obj in data['profiles'].values():
            obj.pop('motion')
        old_writes = backup._g7_writes_from(data)
        self.assertFalse(any(0x19c <= a <= 0x1de for _b, a, _d in old_writes))

    def test_custom_backup_restore_refuses_shape_mismatch_before_any_write(self):
        blob = captured_blob()
        blob[0x1a5] = 3
        decoded = g7.decode_profile(blob)
        data = {'device': profiles.G7_PRO.name,
                'profiles': {str(b): copy.deepcopy(decoded) for b in range(1, 5)},
                'device_settings': {'dock_auto': False, 'dock_brightness': 0}}
        done = threading.Event()
        result = []
        def callback(*args):
            result.append(args)
            done.set()
        with patch.object(control, 'read_reg_sync', return_value=[0] * 9), \
             patch.object(control, 'write_reg') as write:
            backup._apply_g7_backup(data, backup._g7_writes_from(data), on_done=callback)
            self.assertTrue(done.wait(1))
            write.assert_not_called()
        self.assertFalse(result[0][0])
        self.assertIn('No settings written', result[0][1])

    def test_legacy_backup_verification_ignores_new_motion_field(self):
        blob = captured_blob()
        decoded = g7.decode_profile(blob)
        decoded.pop('motion')
        data = {'device': profiles.G7_PRO.name,
                'profiles': {str(b): copy.deepcopy(decoded) for b in range(1, 5)},
                'device_settings': {'dock_auto': False, 'dock_brightness': 0}}
        blobs = {b: blob for b in range(1, 5)}
        blobs[0x20] = bytes(g7.DOCK_BLOB_SIZE)
        values = {}
        def requested(reqs):
            values.update({(b, a): list(blobs[b][a:a + n]) for b, a, n in reqs})
        done = threading.Event()
        result = []
        def callback(*args):
            result.append(args)
            done.set()
        with patch.object(control, 'request_regs', side_effect=requested), \
             patch.object(control, 'reg_result', side_effect=lambda b, a: values.get((b, a))):
            backup._apply_g7_backup(data, [], on_done=callback)
            self.assertTrue(done.wait(1))
        self.assertTrue(result[0][0], result)

    def test_motion_page_loads_for_g7_and_exposes_both_sections(self):
        engine = QQmlApplicationEngine()
        root = Path(__file__).resolve().parents[1]
        engine.addImportPath(str(root / 'qml'))
        engine.rootContext().setContextProperty('bridge', self.bridge)
        errors = []
        engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        engine.load(QUrl.fromLocalFile(str(root / 'qml/App/MotionPage.qml')))
        self.assertTrue(engine.rootObjects(), errors)
        page = engine.rootObjects()[0]
        self.assertEqual(page.property('section'), 'Aim')
        page.setProperty('sec', 1)
        self.assertEqual(page.property('section'), 'Tilt')
        self.assertEqual(page.property('enabled'), True)
        from PySide6.QtCore import QObject
        sensors = page.findChild(QObject, 'motionSensors')
        self.assertIsNotNone(sensors)
        self.assertFalse(sensors.property('streaming'))
        state.update(gyro=(-32768, 0, 32767), accel=(0, 8192, -8192), imu_time=100)
        with patch('bridge.time.monotonic', return_value=100.1):
            self.bridge._poll_sensors()
        self.assertTrue(sensors.property('streaming'))
        # Losing config access hides readings while the read-only panel stays enabled.
        state['config_claimed'] = False
        self.bridge.statusChanged.emit()
        self.bridge._poll_sensors()
        self.assertFalse(sensors.property('streaming'))
        self.assertTrue(sensors.property('enabled'))
        self.assertEqual(errors, [])
        page.deleteLater()
        engine.deleteLater()

    def test_sensitivity_slider_updates_range_without_writing_or_crossing_sections(self):
        from PySide6.QtCore import QObject, QMetaObject, Q_ARG
        self.bridge._m['Aim']['output'] = 1
        self.bridge._m['Tilt']['output'] = 0
        self.bridge._m_loaded = copy.deepcopy(self.bridge._m)
        engine = QQmlApplicationEngine()
        root = Path(__file__).resolve().parents[1]
        engine.addImportPath(str(root / 'qml'))
        engine.rootContext().setContextProperty('bridge', self.bridge)
        errors = []
        engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        engine.load(QUrl.fromLocalFile(str(root / 'qml/App/MotionPage.qml')))
        self.assertTrue(engine.rootObjects(), errors)
        page = engine.rootObjects()[0]
        slider = page.findChild(QObject, 'motionRangeSensitivity')
        self.assertIsNotNone(slider)
        self.assertTrue(page.property('rangeSensitivityVisible'))
        self.assertEqual(slider.property('value'), 1.0)
        with patch.object(control, 'write_reg') as write:
            self.assertTrue(QMetaObject.invokeMethod(slider, 'moved', Q_ARG(float, 2.0)))
            self.assertEqual(self.bridge.motionAim['dz_max'], 50)
            self.assertEqual(self.bridge.motionTilt['dz_max'], 100)
            self.assertEqual(page.property('rangeSensitivity'), 2.0)
            page.setProperty('sec', 1)
            self.assertEqual(slider.property('value'), 1.0)
            self.assertTrue(QMetaObject.invokeMethod(slider, 'moved', Q_ARG(float, 3.0)))
            self.assertEqual(self.bridge.motionTilt['dz_min'], 5)
            self.assertEqual(self.bridge.motionTilt['dz_max'], 37)
            self.assertEqual(self.bridge.motionAim['dz_max'], 50)
            self.bridge.discardConfig()
            self.assertEqual(self.bridge.motionAim['dz_max'], 100)
            self.assertEqual(self.bridge.motionTilt['dz_max'], 100)
            self.assertEqual(slider.property('value'), 1.0)
            write.assert_not_called()
        self.assertEqual(errors, [])
        page.deleteLater()
        engine.deleteLater()

    def test_vibration_buttons_route_slider_strength_and_serialize_previews(self):
        from PySide6.QtCore import QObject, QMetaObject
        self.bridge._config = {
            'vib_l': 21, 'vib_r': 42, 'vib_trigger_l': 63, 'vib_trigger_r': 84,
            'vib_force_l': False, 'vib_force_r': False,
            'vib_sync_l': False, 'vib_sync_r': False,
        }
        engine = QQmlApplicationEngine()
        root = Path(__file__).resolve().parents[1]
        engine.addImportPath(str(root / 'qml'))
        engine.rootContext().setContextProperty('bridge', self.bridge)
        errors = []
        engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        engine.load(QUrl.fromLocalFile(str(root / 'qml/App/VibrationPage.qml')))
        self.assertTrue(engine.rootObjects(), errors)
        page = engine.rootObjects()[0]
        cases = [('testLeftGrip', 'left', 21), ('testRightGrip', 'right', 42),
                 ('testLeftTrigger', 'left_trigger', 63),
                 ('testRightTrigger', 'right_trigger', 84)]
        buttons = [page.findChild(QObject, name) for name, _, _ in cases]
        self.assertTrue(all(buttons))
        with patch.object(control, 'rumble_test') as test, \
             patch.object(control, 'write_reg') as write:
            for button, (_, motor, percent) in zip(buttons, cases):
                self.assertTrue(button.property('enabled'))
                self.assertTrue(QMetaObject.invokeMethod(button, 'clicked'))
                self.assertEqual(test.call_args.kwargs['motor'], motor)
                self.assertEqual(test.call_args.kwargs['strength'], (percent * 255 + 50) // 100)
                self.assertTrue(page.property('testRunning'))
                self.assertTrue(all(not b.property('enabled') for b in buttons))
                test.call_args.kwargs['on_done'](True, '')
                self.assertFalse(page.property('testRunning'))
            write.assert_not_called()
        self.assertEqual(self.bridge._pending, {})
        self.bridge.rumbleTestStatus.emit(False, 'Controller disconnected')
        self.assertEqual(page.property('testError'), 'Controller disconnected')
        state['config_claimed'] = False
        self.bridge.statusChanged.emit()
        self.assertTrue(all(not b.property('enabled') for b in buttons))
        self.assertEqual(errors, [])
        page.deleteLater()
        engine.deleteLater()

    def test_range_drag_stages_before_curve_change_section_switch_and_discard(self):
        from PySide6.QtCore import QObject, QMetaObject, Q_ARG
        engine = QQmlApplicationEngine()
        root = Path(__file__).resolve().parents[1]
        engine.addImportPath(str(root / 'qml'))
        engine.rootContext().setContextProperty('bridge', self.bridge)
        errors = []
        engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        engine.load(QUrl.fromLocalFile(str(root / 'qml/App/MotionPage.qml')))
        self.assertTrue(engine.rootObjects(), errors)
        page = engine.rootObjects()[0]
        dz = page.findChild(QObject, 'motionDeadzone')
        adz = page.findChild(QObject, 'motionAntiDeadzone')
        with patch.object(control, 'write_reg') as write:
            dz.setProperty('lo', 7); dz.setProperty('hi', 60)
            self.assertTrue(QMetaObject.invokeMethod(dz, 'moved', Q_ARG(float, 7), Q_ARG(float, 60)))
            self.assertEqual(self.bridge.motionAim['dz_min'], 7)
            self.assertEqual(self.bridge.motionAim['dz_max'], 60)
            # A curve choice re-seeds the UI; it must retain the range drag.
            self.assertTrue(QMetaObject.invokeMethod(page, 'setCurveType', Q_ARG('QVariant', 1)))
            self.assertEqual(dz.property('lo'), 7)
            self.assertEqual(dz.property('hi'), 60)
            page.setProperty('sec', 1)
            adz.setProperty('lo', 9); adz.setProperty('hi', 90)
            self.assertTrue(QMetaObject.invokeMethod(adz, 'moved', Q_ARG(float, 9), Q_ARG(float, 90)))
            self.assertEqual(self.bridge.motionTilt['adz_min'], 9)
            self.assertEqual(self.bridge.motionTilt['adz_max'], 90)
            self.assertEqual(self.bridge.motionAim['dz_max'], 60)
            self.bridge.discardConfig()
            self.app.processEvents()
            self.assertEqual(self.bridge._pending, {})
            self.assertEqual(self.bridge.motionAim['dz_max'], 100)
            self.assertEqual(self.bridge.motionTilt['adz_min'], 0)
            write.assert_not_called()
        self.assertEqual(errors, [])
        page.deleteLater()
        engine.deleteLater()


if __name__ == '__main__':
    unittest.main()
