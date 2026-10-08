"""G7 SE isolation and diagnostic safety; replies here are synthetic candidates."""
import ctypes
import errno
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import controller_profile as profiles
import g7se_probe as probe
import reader
from gs_state import state
from vendors.gamesir.models.g7se import protocol as se
from vendors.gamesir.models.g7pro import protocol as pro
from vendors.gamesir.usb_transport import UsbTransportError


def reply(profile=1, offset=0, length=55):
    return bytes((0x10, 0, 1, 0x3c, 5, profile, offset >> 8, offset & 255, length)) + bytes(range(length))


class ProtocolTests(unittest.TestCase):
    def test_identity_and_configuration_isolation(self):
        self.assertIs(profiles.detect_one(0x1010, 'GameSir-G7 SE'), profiles.G7_SE)
        self.assertNotIn(se.PID, pro.ALL_PIDS)
        self.assertNotIn(se.PID, pro.CONFIG_PIDS)
        self.assertTrue(se.CONFIGURATION_VERIFIED)
        prof = profiles.G7_SE
        self.assertEqual(prof.profile_banks, (1, 2, 3))
        self.assertIsNone(prof.profile_bank(4))
        self.assertEqual(prof.write_style, 'g7se')
        self.assertEqual(prof.REMAP_SLOTS, (('L4', 0xab), ('R4', 0xc7)))
        self.assertEqual(len(prof.REMAP_TARGETS), 14)
        for value in (prof.read_fields(), prof.extras, prof.MACRO_SLOTS):
            self.assertFalse(value)

    def test_prefer_configurable_device_over_se(self):
        se_ctrl = {'id': 'se', 'pid': se.PID, 'product': 'GameSir-G7 SE', 'nodes': []}
        pro_ctrl = {'id': 'pro', 'pid': 0x10a7, 'product': 'GameSir-G7 Pro', 'nodes': []}
        with patch.dict(state, selected=None):
            self.assertIs(reader._pick_selected([se_ctrl, pro_ctrl]), pro_ctrl)
        with patch.dict(state, selected='se'):
            self.assertIs(reader._pick_selected([se_ctrl, pro_ctrl]), se_ctrl)

    def test_candidate_read_encoding(self):
        request = se.read_request(7, 1, 0x100, 55)
        self.assertEqual(request, bytes.fromhex('0f 00 07 05 04 01 01 00 37') + bytes(55))
        self.assertEqual(len(request), 64)

    def test_confirmed_firmware_fixture_does_not_qualify_as_profile_reply(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'g7se-0630-firmware.json').read_text())
        self.assertEqual(se.packet(25, 1, b'\x09'), bytes.fromhex(fixture['request']))
        frame = bytes.fromhex(fixture['response'])
        self.assertEqual(frame[3:5], b'\x3c\x0a')
        self.assertEqual(frame[5:-1].decode('utf-16-le').split('\0')[0], '0108')
        self.assertIsNone(se.match_read(frame, 1, 0, 55))

    def test_confirmed_information_fixture_is_not_a_configuration_reply(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'g7se-0630-info-0b.json').read_text())
        self.assertEqual(se.packet(9, 1, b'\x0b'), bytes.fromhex(fixture['request']))
        frame = bytes.fromhex(fixture['response'])
        self.assertEqual(frame[3:7], b'\x3c\x0c\x01\x01')
        self.assertIsNone(se.match_read(frame, 1, 0, 1))
        self.assertIsNone(se.match_legacy_read(frame, 1, 0, 1))

    def test_only_read_only_candidates_are_allowed(self):
        for command, payload in ((0x3c, b'\x03'), (3, b''), (1, b'\x0d'),
                                 (2, b'\x00'), (5, b'\x04\x20\x00\x00\x37'),
                                 (5, b'\x04\x01\x01\xdf\x37')):
            with self.subTest(command=command, payload=payload), self.assertRaises(ValueError):
                se.packet(1, command, payload)

    def test_matching_requires_profile_offset_and_length(self):
        self.assertEqual(se.match_read(reply(), 1, 0, 55), bytes(range(55)))
        for params in ((2, 0, 55), (1, 1, 55), (1, 0, 54)):
            self.assertIsNone(se.match_read(reply(), *params))

    def test_malformed_and_truncated_replies(self):
        for size in range(64):
            self.assertIsNone(se.match_read(reply()[:size], 1, 0, 55))
        for index in (0, 3, 4, 5, 6, 7, 8):
            frame = bytearray(reply())
            frame[index] ^= 0xff
            self.assertIsNone(se.match_read(frame, 1, 0, 55))
        self.assertIsNone(se.match_read(reply() + b'\x00', 1, 0, 55))

    def test_legacy_candidates_encoding_and_reply_matching(self):
        self.assertEqual(se.legacy_packet(4, b'\x01\x00\x00\x01'),
                         bytes.fromhex('0f 04 01 00 00 01') + bytes(58))
        self.assertEqual(se.legacy_packet(0xf2), b'\x0f\xf2' + bytes(62))
        frame = b'\x10\x05\x01\x00\x00\x01\x09'
        self.assertEqual(se.match_legacy_read(frame, 1, 0, 1), b'\x09')
        for parameters in ((2, 0, 1), (1, 1, 1), (1, 0, 2)):
            self.assertIsNone(se.match_legacy_read(frame, *parameters))
        self.assertIsNone(se.match_legacy_read(frame[:-1], 1, 0, 1))
        self.assertIsNone(se.match_legacy_read(reply(), 1, 0, 55))
        for command, payload in ((3, b'\x01\x00\x00\x01'), (7, b'\x01'),
                                 (0xf2, b'\x01'), (4, b'\x20\x00\x00\x01')):
            with self.assertRaises(ValueError):
                se.legacy_packet(command, payload)

    def test_standard_xpad_input_initialization(self):
        self.assertEqual(se.gip_power_on(3), bytes.fromhex('05 20 03 01 00'))
        with self.assertRaises(ValueError):
            se.gip_power_on(256)


class SessionTests(unittest.TestCase):
    def session(self):
        info = {'busnum': '1', 'devnum': '12', 'idVendor': '3537',
                'idProduct': '1010', 'bcdDevice': '0630', 'serial': ''}
        with patch.object(probe, 'topology', return_value=info):
            return probe.Session('/tmp', {'channels': []})

    def test_session_changed_or_disconnected(self):
        session = self.session()
        for change in ({'devnum': '13'}, {'bcdDevice': '0633'}, {'idProduct': '109b'}):
            with patch.object(Path, 'read_text', autospec=True, side_effect=lambda *a, **kw:
                    ({**session.identity, **change}).get(a[0].name, '')):
                with self.assertRaises(UsbTransportError):
                    session.check()
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                session.check()

    def test_total_budget(self):
        session = self.session()
        with patch.object(Path, 'read_text', autospec=True, side_effect=lambda *a, **kw:
                session.identity.get(a[0].name, '')), \
                patch.object(probe.time, 'monotonic', return_value=session.started + 56):
            with self.assertRaises(UsbTransportError):
                session.check()

    def test_no_write_on_session_change(self):
        session = self.session()
        handle = Mock()
        with patch.object(session, 'check', side_effect=UsbTransportError('changed')):
            with self.assertRaises(UsbTransportError):
                session.send(handle, 2, b'\xf2\x00', [])
        handle.write.assert_not_called()

    def test_short_write(self):
        session = self.session()
        with patch.object(session, 'check'), self.assertRaises(UsbTransportError):
            session.send(Mock(write=Mock(return_value=63)), 2, b'\xf2\x00', [])

    def test_receive_ignores_wrong_replies(self):
        session = self.session()
        handle = Mock(read=Mock(side_effect=[reply(2), reply()]))
        log = []
        with patch.object(session, 'check'):
            got = session.receive(handle, log, lambda r: se.match_read(r, 1, 0, 55))
        self.assertEqual(got, bytes(range(55)))
        self.assertFalse(log[0]['matched'])
        self.assertTrue(log[1]['matched'])

    def test_timeouts_and_busy_stream_are_bounded(self):
        session = self.session()
        for value in (b'', b'garbage'):
            handle = Mock(read=Mock(return_value=value))
            log = []
            with patch.object(session, 'check'):
                self.assertIsNone(session.receive(handle, log, lambda r: None))
            self.assertEqual(handle.read.call_count, 4096)
            self.assertEqual(log[-1]['packet_limit'], 4096)

    def test_receive_deadline(self):
        session = self.session()
        handle, log = Mock(), []
        with patch.object(session, 'check'), \
                patch.object(probe.time, 'monotonic', side_effect=[0, 3]):
            self.assertIsNone(session.receive(handle, log, lambda r: None, seconds=2))
        handle.read.assert_not_called()
        self.assertTrue(log[-1]['timeout'])

    def test_maintained_heartbeats_while_waiting(self):
        session = self.session()
        clock, pulses, log = [0.0], [], []
        def read(*args, **kwargs):
            clock[0] += 0.2
            return b''
        with patch.object(session, 'check'), \
                patch.object(probe.time, 'monotonic', side_effect=lambda: clock[0]):
            self.assertIsNone(session.receive(Mock(read=read), log, lambda r: None,
                seconds=1, heartbeat=lambda: pulses.append(clock[0])))
        self.assertEqual(len(pulses), 2)
        self.assertTrue(log[-1]['timeout'])

    def test_candidate_matrix_is_read_only_and_closes_both_interfaces(self):
        session = self.session()
        handles = [Mock(original_alt=None, cleanup=[], _interface=0),
                   Mock(original_alt=0, cleanup=[], _interface=2)]
        for handle in handles:
            handle.write.side_effect = lambda wire: len(wire)
        closed = []
        handles[0].close.side_effect = lambda: closed.append(0)
        handles[1].close.side_effect = lambda: closed.append(2)
        with patch.object(session, 'check'), patch.object(session, 'receive', return_value=None), \
                patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', side_effect=handles):
            self.assertFalse(session.investigate())
        self.assertEqual(closed, [2, 0])
        evidence = session.evidence['channels'][0]
        self.assertEqual(len(evidence['reads']), 14)
        self.assertEqual(evidence['reads'][0]['stage'], 'early-two-heartbeats')
        for handle in handles:
            for call in handle.write.call_args_list:
                wire = call.args[0]
                if wire[0] == 5:
                    self.assertEqual(wire, se.gip_power_on(wire[2]))
                    continue
                self.assertEqual(len(wire), 64)
                if wire[1] == 0:
                    self.assertIn(wire[3], (1, 2, 5))
                    if wire[3] == 1:
                        self.assertIn(wire[4], (9, 0x0b))
                else:
                    self.assertIn(wire[1], (4, 0xf2))

    def test_candidate_matrix_stops_on_session_change_and_cleans_up(self):
        session = self.session()
        handle = Mock(original_alt=None, cleanup=[])
        with patch.object(session, 'check', side_effect=[None, UsbTransportError('session changed')]), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle):
            self.assertFalse(session.investigate())
        handle.write.assert_not_called()
        handle.close.assert_called_once()
        self.assertIn('session changed', session.evidence['channels'][0]['error'])

    def test_bulk_tests_direct_reads_even_when_writes_stall(self):
        session = self.session()
        handle = Mock(original_alt=0, cleanup=[])
        handle.write.side_effect = UsbTransportError('USB bulk write: LIBUSB_ERROR_PIPE')
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle):
            self.assertFalse(session.channel(2, 1, 0x81))
        self.assertEqual(handle.write.call_count, 2)
        for call in handle.write.call_args_list:
            self.assertEqual(call.args[0][3:9], b'\x05\x04\x01\x00\x00\x37')
        self.assertEqual(len(session.evidence['channels'][0]['reads']), 2)
        handle.close.assert_called_once()

    def test_disconnect_stops_bulk_retry(self):
        session = self.session()
        handle = Mock(original_alt=0, cleanup=[])
        handle.write.side_effect = UsbTransportError(errno.ENODEV, 'disconnected')
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle):
            self.assertFalse(session.channel(2, 1, 0x81))
        self.assertEqual(handle.write.call_count, 1)
        handle.close.assert_called_once()

    def test_cleanup_on_read_error(self):
        session = self.session()
        handle = Mock(original_alt=None, cleanup=[])
        handle.write.return_value = 64
        handle.read.side_effect = UsbTransportError('disconnected')
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle):
            self.assertFalse(session.channel(0, 2, 0x82))
        handle.close.assert_called_once()
        self.assertIn('disconnected', session.evidence['channels'][0]['error'])

    def test_repeatable_reads_required(self):
        for values, expected in (([b'abc', b'abc'], True), ([b'abc', b'def'], False),
                                 ([None, None], False)):
            session = self.session()
            handle = Mock(original_alt=0, cleanup=[])
            with patch.object(session, 'check'), patch.object(session, 'send'), \
                    patch.object(session, 'receive', side_effect=values), \
                    patch.object(probe.time, 'sleep'), \
                    patch.object(probe.ProbeHandle, 'open', return_value=handle):
                self.assertEqual(session.channel(2, 1, 0x81), expected)
            handle.close.assert_called_once()


class CleanupTests(unittest.TestCase):
    def test_restore_release_reattach_order_even_on_errors(self):
        lib = Mock()
        lib.libusb_set_interface_alt_setting.return_value = -4
        lib.libusb_release_interface.return_value = -4
        lib.libusb_attach_kernel_driver.return_value = -4
        handle = probe.ProbeHandle(lib, ctypes.c_void_p(1), ctypes.c_void_p(2), 2, 1, 0x81)
        handle.original_alt = 0
        handle.restore_alt = handle._claimed = handle._detached = True
        handle.close()
        self.assertEqual([c[0] for c in lib.mock_calls], [
            'libusb_set_interface_alt_setting', 'libusb_release_interface',
            'libusb_attach_kernel_driver', 'libusb_close', 'libusb_exit'])
        self.assertEqual([e['result'] for e in handle.cleanup], [-4, -4, -4])
        handle.close()
        self.assertEqual(len(lib.mock_calls), 5)

    def test_claim_failure_restores_before_close(self):
        handle = probe.ProbeHandle(Mock(), None, None, 2, 1, 0x81)
        with patch.object(handle, '_claim_probe', side_effect=UsbTransportError('claim failed')), \
                patch.object(handle, 'close') as close:
            with self.assertRaises(UsbTransportError) as caught:
                handle._claim()
        close.assert_called_once()
        self.assertEqual(caught.exception.cleanup, [])


class DisabledEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QGuiApplication
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_se_rejects_edits_and_save_without_loaded_session(self):
        from PySide6.QtCore import QTimer
        from bridge import GamesirBridge
        from vendors.gamesir import control
        bridge = GamesirBridge()
        bridge._apply_profile(profiles.G7_SE)
        old_profile = profiles.active()
        try:
            profiles.set_active(profiles.G7_SE)
            with patch.dict(state, demo=False, profile=None, edit_profile=None,
                            config_wanted=False), patch.object(control, 'write_reg') as write, \
                    patch.object(control, 'request_regs') as read, patch.object(se, 'CONFIGURATION_VERIFIED', False):
                for source in ('L4', 'R4', 'L5', 'A', 'invalid'):
                    bridge.setRemap(source, 'A')
                    for target in (-1, 9, 0xc8, 0xffff):
                        bridge.setRemapCode(source, target)
                bridge.setConfigClaimed(True)
                bridge._poll_config()
                bridge.applyConfig()
                self.assertEqual(bridge.pendingCount, 0)
                self.assertFalse(state['config_wanted'])
                self.assertEqual(bridge.profileCount, 0)
                self.assertEqual(bridge.remapSources, [])
                self.assertFalse(bridge.hasUsbConfiguration)
                self.assertIn('disabled', bridge.modeMessage)
                read.assert_not_called()
                write.assert_not_called()
        finally:
            profiles.set_active(old_profile)
            for timer in bridge.findChildren(QTimer):
                timer.stop()
            bridge.deleteLater()


if __name__ == '__main__':
    unittest.main()
