import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from bridge import GamesirBridge
import controller_profile as profiles
from gs_state import state
from vendors.gamesir import control
from vendors.gamesir.models.g7se import protocol as se
import reader


class ReaderStopped(BaseException):
    """Exit the infinite reader loop without being treated as a device error."""


def se_controller(identity='se', bcd=se.TESTED_DESCRIPTOR):
    return {'id': identity, 'port': identity, 'pid': se.PID,
            'product': 'GameSir G7 SE', 'bcd': bcd, 'nodes': [],
            'usb': {'bus': 1, 'address': 6, 'sysfs': '/unused'}}


class SeAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.verified = patch.object(se, 'CONFIGURATION_VERIFIED', True)
        self.verified.start()  # Exercise the gated implementation against captured semantics.
        self.old = profiles.active()
        profiles.set_active(profiles.G7_SE)
        self.bridge = GamesirBridge()
        self.bridge._apply_profile(profiles.G7_SE)
        self.patch = patch.dict(state, selected='se', driving='se', connected=True,
            profile=1, edit_profile=1, demo=False, config_claimed=True, config_wanted=True,
            usb_bcd=se.TESTED_DESCRIPTOR)
        self.patch.start()
        self.memory = {(1, 0xab): list(se.remap_record(7)), (1, 0xc7): list(se.remap_record(8))}
        self.wires = []
        def write(wire):
            self.wires.append(wire)
            if wire[3:5] == b'\x3c\x03':
                self.memory[(wire[5], int.from_bytes(wire[6:8], 'big'))] = list(wire[9:17])
            return len(wire)
        self.handle = Mock(write=write)
        control.set_device(self.handle)
        self.bridge._driving = 'se'
        self.bridge._loaded_profile = 1
        self.bridge._config_loading = None
        self.bridge._config_generation = control.generation()
        self.bridge._config = {'remap': {'L4': 7, 'R4': 8}}

    def tearDown(self):
        self.verified.stop()
        control.clear_device()
        profiles.set_active(self.old)
        self.patch.stop()
        for timer in self.bridge.findChildren(QTimer):
            timer.stop()
        self.bridge.deleteLater()

    def run_save(self, bad_readback=False, changed_session=False):
        queried = []
        def request(reqs):
            queried.extend(reqs)
        def read(bank, addr):
            if changed_session and self.wires:
                state['selected'] = 'other'
            raw = self.memory[(bank, addr)]
            if bad_readback and raw == list(se.remap_record(15)):
                return list(se.remap_record(16))
            return raw
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_DATA_HOME=directory), \
                patch.object(control, 'request_regs', side_effect=request), \
                patch.object(control, 'reg_result', side_effect=read), \
                patch('bridge.threading.Thread', side_effect=lambda target, **kwargs: Mock(start=target)):
            self.bridge.applyConfig()
            files = list(__import__('pathlib').Path(directory).rglob('before_apply_*.json'))
            self.assertTrue(files)
        return queried

    def test_stages_only_and_verified_save(self):
        self.bridge.setRemapCode('L4', 15)
        self.assertEqual(self.wires, [])
        self.assertEqual(self.bridge.pendingCount, 1)
        self.assertEqual(self.bridge.config['remap']['L4'], 7)
        queried = self.run_save()
        self.assertTrue(all(q == (1, 0xab, 8) for q in queried))
        self.assertEqual(self.memory[(1, 0xab)], list(se.remap_record(15)))
        self.assertEqual(self.bridge.pendingCount, 0)
        self.assertEqual(self.bridge.config['remap']['L4'], 15)
        self.assertIn('1/1', self.bridge._apply_status)
        self.assertTrue(all(se.allowed_app_request(w) for w in self.wires))

    def test_three_nexus_profiles_and_fourth_bank_refused(self):
        self.assertEqual(self.bridge.profileCount, 3)
        self.bridge.setProfile(3)
        self.assertEqual(state['edit_profile'], 3)
        self.bridge.setProfile(4)
        self.assertEqual(state['edit_profile'], 3)
        state['edit_profile'] = 4
        self.bridge.setRemapCode('L4', 15)
        self.assertEqual(self.bridge.pendingCount, 0)
        self.assertFalse(control.write_reg(4, 0xab, se.remap_record(15), gen=control.generation()))
        self.assertEqual(self.wires, [])

    def test_profile_count_changes_only_for_se_and_restores_on_model_switch(self):
        for profile, expected in ((profiles.G7_SE, 3), (profiles.CYCLONE, 4),
                                  (profiles.G7_PRO, 4), (profiles.G7_8K, 4),
                                  (profiles.TARANTULA_PRO_8K, 4), (profiles.G7_SE, 3),
                                  (profiles.G7_PRO, 4)):
            with self.subTest(controller=profile.short):
                profiles.set_active(profile)
                self.bridge._apply_profile(profile)
                self.assertEqual(self.bridge.profileCount, expected)

    def test_readback_failure_restores_and_keeps_staged_edit(self):
        self.bridge.setRemapCode('L4', 15)
        self.run_save(bad_readback=True)
        self.assertEqual(self.memory[(1, 0xab)], list(se.remap_record(7)))
        self.assertEqual(self.bridge.pendingCount, 1)
        self.assertEqual(self.bridge.config['remap']['L4'], 7)
        self.assertIn('original settings restored', self.bridge._apply_status)

    def test_changed_selected_device_prevents_further_writes(self):
        self.bridge.setRemapCode('L4', 15)
        self.bridge.setRemapCode('R4', 16)
        self.run_save(changed_session=True)
        self.assertEqual(len(self.wires), 1)
        self.assertEqual(self.bridge.pendingCount, 2)
        self.assertIn('recovery NOT confirmed', self.bridge._apply_status)

    def test_rejects_sources_targets_and_stale_profile(self):
        for source in ('A', 'L5', 'R5', 'invalid'):
            self.bridge.setRemapCode(source, 15)
        for target in (-2, 0, 9, 24, 0xc8, 0xffff):
            self.bridge.setRemapCode('L4', target)
        self.assertEqual(self.bridge.pendingCount, 0)
        self.bridge.setRemapCode('L4', 15)
        state['edit_profile'] = 2
        self.bridge.applyConfig()
        self.assertEqual(self.wires, [])
        self.assertIn('older session/profile', self.bridge._apply_status)

    def test_clear_and_only_se_features(self):
        self.bridge.setRemapCode('R4', -1)
        self.run_save()
        self.assertEqual(self.memory[(1, 0xc7)], [0] * 8)
        self.assertEqual(self.bridge.remapSources, ['L4', 'R4'])
        self.assertEqual(len(self.bridge.buttonTargets), 14)
        self.assertEqual(self.bridge.mouseTargets, [])
        self.assertTrue(self.bridge.remapOnly)
        self.assertFalse(self.bridge.isG7Pro)
        self.assertEqual([c['name'] for c in self.bridge.targetCategories], ['Buttons'])

    def test_se_reader_does_not_request_pro_settings_and_cleans_up(self):
        ctrl = {'id': 'se', 'usb': {'bus': 1, 'address': 5, 'sysfs': '/unused'}}
        def read(*args, **kwargs):
            state['config_wanted'] = False
            return b''
        self.handle.read.side_effect = read
        with patch.object(se, 'open_device', return_value=self.handle), \
                patch.object(reader, '_rescan', return_value=[ctrl]), \
                patch.object(reader.g7pro, 'open_device') as pro:
            reader.read_session_seusb(ctrl)
        pro.assert_not_called()
        self.handle.close.assert_called_once()
        self.assertFalse(state['config_claimed'])
        self.assertIsNone(state['driving'])
        self.assertTrue(all(se.allowed_app_request(w) for w in self.wires))

    def test_strict_read_routing_and_no_unsupported_reads(self):
        control.request_regs([(1, 0xab, 8), (0x20, 0, 55), (1, 0x36, 1)])
        control.pump_reads()
        wire = self.wires[-1]
        self.assertEqual(len(wire), 9)
        reply = bytes((16, 0, wire[2], 60, 5)) + wire[5:9] + se.remap_record(7) + bytes(47)
        wrong = bytearray(reply)
        wrong[2] ^= 1
        self.assertFalse(control.store_se_reply(wrong))
        self.assertFalse(control.store_se_reply(reply[:10]))
        self.assertFalse(control.store_se_reply(b''))
        self.assertTrue(control.store_se_reply(reply))
        self.assertEqual(control.reg_result(1, 0xab), list(se.remap_record(7)))
        control.pump_reads()
        self.assertEqual(len(self.wires), 1)

    def test_partial_transfer_and_session_change_refuse_writes(self):
        generation = control.generation()
        self.handle.write = Mock(return_value=63)
        self.assertFalse(control.write_reg(1, 0xab, se.remap_record(15), gen=generation))
        self.handle.write.reset_mock()
        state['selected'] = 'other'
        self.assertFalse(control.write_reg(1, 0xab, se.remap_record(15), gen=generation))
        self.handle.write.assert_not_called()
        state['selected'] = 'se'
        control.clear_device()
        self.assertFalse(control.write_reg(1, 0xab, se.remap_record(15), gen=generation))

    def test_disconnect_during_read_releases_interface(self):
        ctrl = {'id': 'se', 'usb': {'bus': 1, 'address': 5, 'sysfs': '/unused'}}
        self.handle.read.side_effect = OSError('controller disconnected')
        with patch.object(se, 'open_device', return_value=self.handle), \
                patch.object(reader, '_rescan', return_value=[ctrl]), \
                patch('vendors.gamesir.models.g7se.startup.Startup'):
            reader.read_session_seusb(ctrl)
        self.handle.close.assert_called_once()
        self.assertFalse(state['config_claimed'])
        self.assertFalse(state['config_wanted'])
        self.assertIsNone(state['driving'])
        self.assertIn('controller disconnected', state['config_status'])

    def test_disabled_gate_blocks_loaded_edits_save_claim_and_transport(self):
        self.bridge.setRemapCode('L4', 15)
        self.assertEqual(self.bridge.pendingCount, 1)
        with patch.object(se, 'CONFIGURATION_VERIFIED', False):
            self.bridge.setRemapCode('R4', 16)
            self.assertEqual(self.bridge.pendingCount, 1)
            self.bridge.applyConfig()
            self.assertIn('cold-start', self.bridge._apply_status)
            self.assertFalse(control.write_reg(1, 0xab, se.remap_record(15), gen=control.generation()))
            state['config_wanted'] = False
            self.bridge.setConfigClaimed(True)
            self.assertFalse(state['config_wanted'])
            self.assertEqual(self.bridge.profileCount, 0)
            self.assertEqual(self.bridge.remapSources, [])
            self.assertFalse(self.bridge.hasUsbConfiguration)
        self.assertEqual(self.wires, [])

    def test_startup_failure_releases_interface_without_binding_register_channel(self):
        ctrl = {'id': 'se', 'usb': {'bus': 1, 'address': 6, 'sysfs': '/unused'}}
        with patch.object(se, 'open_device', return_value=self.handle), \
                patch('vendors.gamesir.models.g7se.startup.Startup') as startup, \
                patch.object(control, 'set_device') as bind:
            startup.return_value.run.side_effect = OSError('authentication failed')
            reader.read_session_seusb(ctrl)
            bind.assert_not_called()
            startup.return_value.restore_input.assert_called_once()
        self.handle.close.assert_called_once()
        self.assertFalse(state['config_claimed'])
        self.assertFalse(state['config_wanted'])
        self.assertIn('authentication failed', state['config_status'])

    def test_disabled_transport_never_claims_usb(self):
        with patch.object(se, 'CONFIGURATION_VERIFIED', False), \
                patch('vendors.gamesir.usb_transport.InterruptHandle.open') as opened:
            with self.assertRaises(OSError):
                se.open_device(1, 6, '/unused')
        opened.assert_not_called()

    def test_reader_preserves_failures_across_input_only_iterations_until_retry(self):
        for error, restore_error in (
                ('G7 SE initialization requires the system OpenSSL command', None),
                ('authentication failed', None),
                ('authentication failed', 'Short G7 SE input restoration transfer')):
            with self.subTest(error=error, restore_error=restore_error):
                state.update(selected='se', config_wanted=True, config_status='')
                expected = ('G7 SE input restoration failed: ' + restore_error
                            if restore_error else 'G7 SE configuration ended: ' + error)
                observed = []

                def input_only(*args, **kwargs):
                    observed.append(state['config_status'])
                    if len(observed) == 2:
                        raise ReaderStopped()

                with patch.object(reader, '_rescan', return_value=[se_controller()]), \
                        patch.object(se, 'open_device', return_value=self.handle), \
                        patch('vendors.gamesir.models.g7se.startup.Startup') as startup, \
                        patch.object(reader, 'read_session_evdev', side_effect=input_only), \
                        patch.object(reader.time, 'sleep'):
                    startup.return_value.run.side_effect = OSError(error)
                    if restore_error:
                        startup.return_value.restore_input.side_effect = OSError(restore_error)
                    with self.assertRaises(ReaderStopped):
                        reader.read_controller()
                self.assertEqual(observed, [expected, expected])
                self.bridge.setConfigClaimed(True)
                self.assertTrue(state['config_wanted'])
                self.assertEqual(state['config_status'], 'Connecting configuration…')

    def test_reader_drops_previous_devices_error_and_publishes_descriptor(self):
        state.update(selected='other-se', config_wanted=False,
                     config_status='G7 SE configuration ended: old device error')
        with patch.object(reader, '_rescan', return_value=[se_controller('other-se')]), \
                patch.object(reader, 'read_session_evdev', side_effect=ReaderStopped):
            with self.assertRaises(ReaderStopped):
                reader.read_controller()
        self.assertEqual(state['config_status'], 'Released to games')
        self.assertEqual(state['usb_bcd'], se.TESTED_DESCRIPTOR)

    def test_unsupported_firmware_stays_input_only(self):
        for bcd in (0x0640, None):
            with self.subTest(bcd=bcd), \
                    patch.object(reader, '_rescan', return_value=[se_controller(bcd=bcd)]), \
                    patch.object(se, 'open_device') as opened, \
                    patch.object(reader, 'read_session_evdev', side_effect=ReaderStopped):
                state.update(config_wanted=True, config_status='')
                with self.assertRaises(ReaderStopped):
                    reader.read_controller()
                opened.assert_not_called()
                self.assertEqual(state['usb_bcd'], bcd)
                self.assertFalse(self.bridge.hasUsbConfiguration)
                self.assertEqual(self.bridge.profileCount, 0)
                self.assertEqual(self.bridge.remapSources, [])
                self.assertIn('6.30', self.bridge.modeMessage)
                self.bridge.setConfigClaimed(True)
                self.assertFalse(state['config_wanted'])
                self.bridge.setProfile(2)
                self.assertIsNone(state['edit_profile'])

    def test_qml_capabilities_refresh_when_only_se_firmware_changes(self):
        state['controller'] = profiles.G7_SE.short
        self.bridge._poll_status()
        engine = QQmlEngine()
        engine.rootContext().setContextProperty('bridge', self.bridge)
        component = QQmlComponent(engine)
        component.setData(b'''import QtQml
            QtObject {
                property bool configurable: bridge.hasUsbConfiguration
                property int profiles: bridge.profileCount
                property int sources: bridge.remapSources.length
            }''', QUrl())
        view = component.create()
        self.assertIsNotNone(view, component.errors())
        for bcd, supported in ((se.TESTED_DESCRIPTOR, True), (0x0640, False),
                               (None, False), (se.TESTED_DESCRIPTOR, True)):
            state['usb_bcd'] = bcd
            self.bridge._poll_status()
            self.assertEqual(view.property('configurable'), supported)
            self.assertEqual(view.property('profiles'), 3 if supported else 0)
            self.assertEqual(view.property('sources'), 2 if supported else 0)
        view.deleteLater()


if __name__ == '__main__':
    unittest.main()
