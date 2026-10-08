"""Validate raw supplied Windows evidence independently of its decoder summary."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import g7se_probe as probe
from vendors.gamesir.models.g7se import protocol as se
from vendors.gamesir.usb_transport import UsbTransportError


FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'g7se-0630-nexus.json').read_text())


class NexusCaptureTests(unittest.TestCase):
    def test_raw_startup_candidate_is_separate_from_normal_input_power(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'g7se-0630-nexus-startup.json').read_text())
        self.assertGreater(len(fixture['packet_candidates']), 2)
        for item in fixture['packet_candidates']:
            request = bytes.fromhex(item['request'])
            self.assertEqual(se.nexus_initialize(request[2]), request)
            self.assertNotEqual(se.gip_power_on(request[2]), request)
            self.assertFalse(se.allowed_app_request(request))
        for sequence in (0, -1, 256):
            with self.assertRaises(ValueError):
                se.nexus_initialize(sequence)

    def test_linux_full_record_writes_clear_and_restore_in_every_bank(self):
        captured = json.loads((Path(__file__).parent / 'fixtures' /
                               'g7se-0630-linux-roundtrip.json').read_text())
        observed = set()
        for item in captured['writes']:
            write = bytes.fromhex(item['request'])
            read = bytes.fromhex(item['read_request'])
            reply = bytes.fromhex(item['response'])
            bank, address = item['profile'], item['offset']
            record = write[9:17]
            if bank in se.PROFILE_BANKS:
                self.assertEqual(write, se.remap_write(write[2], bank, address, record))
            else:
                # Historical evidence includes readable bank 4. Nexus exposes
                # only 1–3; production must not expose or write the fourth bank.
                with self.assertRaises(ValueError):
                    se.remap_write(write[2], bank, address, record)
                self.assertFalse(se.allowed_app_request(write))
            self.assertEqual(read, se.nexus_request(read[2], 5,
                bytes((4, bank)) + address.to_bytes(2, 'big') + bytes((8,))))
            self.assertEqual(reply[2], read[2])
            self.assertEqual(se.match_read(reply, bank, address, 8), record)
            observed.add((bank, address, se.decode_remap(record)))
        for bank in (1, 2, 3, 4):
            for _, address in se.REMAP_SLOTS:
                self.assertIn((bank, address, 15), observed)
                self.assertIn((bank, address, -1), observed)
        self.assertTrue(captured['all_readable_settings_unchanged'])

    def test_reads_match_exact_short_out_and_complete_echo(self):
        for item in FIXTURE['reads']:
            request, response = bytes.fromhex(item['request']), bytes.fromhex(item['response'])
            with self.subTest(capture=item['capture'], frame=item['request_frame']):
                payload = bytes((4, item['profile'])) + item['offset'].to_bytes(2, 'big') + bytes((item['length'],))
                self.assertEqual(request, se.nexus_request(request[2], 5, payload))
                self.assertEqual(len(request), 9)
                self.assertEqual(response[2], request[2])
                data = se.match_read(response, item['profile'], item['offset'], item['length'])
                self.assertIsNotNone(data)
                self.assertEqual(len(data), item['length'])
                self.assertIsNone(se.match_read(response, item['profile'], item['offset'] + 1, item['length']))

    def test_captured_rear_writes_readbacks_and_acknowledgments(self):
        for item in FIXTURE['writes']:
            request, readback = bytes.fromhex(item['request']), bytes.fromhex(item['readback'])
            with self.subTest(capture=item['capture'], frame=item['frame']):
                body = bytes((3, item['profile'])) + item['offset'].to_bytes(2, 'big')
                body += bytes((item['length'],)) + bytes.fromhex(item['data'])
                self.assertEqual(request, bytes((15, 0, request[2], 60)) + body.ljust(60, b'\0'))
                bank, offset, length = readback[5], int.from_bytes(readback[6:8], 'big'), readback[8]
                data = se.match_read(readback, bank, offset, length)
                self.assertIsNotNone(data)
                self.assertEqual(bank, item['profile'])
                start = item['offset'] - offset
                self.assertGreaterEqual(start, 0)
                self.assertEqual(data[start:start + item['length']].hex(), item['data'])
                if item['ack']:
                    ack = bytes.fromhex(item['ack'])
                    self.assertEqual(ack[:3], bytes((16, 0, request[2])))
                    self.assertEqual(ack[3:5], b'\x3c\x06')

    def test_fourteen_se_target_codes_are_captured(self):
        observed = {int(item['data'], 16) for item in FIXTURE['writes'] if item['length'] == 1}
        self.assertEqual(observed, {1, 2, 3, 4, 5, 6, 7, 8, 15, 16, 17, 18, 22, 23})
        clear = [item for item in FIXTURE['writes'] if item['data'] == '00' * 8]
        self.assertTrue(clear)
        self.assertTrue(all(item['profile'] == 3 and item['offset'] == 0xab for item in clear))

    def test_nexus_constructor_does_not_allow_writes(self):
        for command, payload in ((60, b'\x03\x01\x00\xb2\x01\x0f'), (3, b''), (2, b'')):
            with self.assertRaises(ValueError):
                se.nexus_request(1, command, payload)

    def test_rear_record_encoding_and_rejection(self):
        for code in (-1, 1, 8, 15, 23):
            self.assertEqual(se.decode_remap(se.remap_record(code)), code)
        for code in (-2, 0, 9, 24, 0xc8):
            with self.assertRaises(ValueError):
                se.remap_record(code)
        for record in (b'', bytes(7), bytes(9), b'\x03' + bytes(6) + b'\x0f'):
            with self.assertRaises(ValueError):
                se.decode_remap(record)
        self.assertEqual(se.remap_write(1, 1, 0xab, se.remap_record(15))[:17],
                         bytes.fromhex('0f00013c030100ab08040000000000010f'))
        for bank, address in ((0x20, 0xab), (1, 0xb2), (1, 0x0036), (5, 0xab)):
            with self.assertRaises(ValueError):
                se.remap_write(1, bank, address, se.remap_record(15))

    def test_roundtrip_restores_complete_profiles_after_success_and_failed_verification(self):
        import tempfile
        for corrupt in (False, True):
            session = self.session()
            banks = {bank: bytearray(421) for bank in (1, 2, 3, 4)}
            banks[1][0xab:0xb3], banks[1][0xc7:0xcf] = se.remap_record(7), se.remap_record(8)
            original = {str(bank): data.hex() for bank, data in banks.items()}
            baseline = {'snapshots': [original, original], 'repeatable_full_profiles': True}
            session.evidence['channels'].append(baseline)
            current = [None]
            handle = Mock(cleanup=[])
            def write(wire):
                current[0] = wire
                if wire[3] == 60:
                    bank, addr, length = wire[5], int.from_bytes(wire[6:8], 'big'), wire[8]
                    banks[bank][addr:addr + length] = wire[9:9 + length]
                    if corrupt and wire[9:17] == se.remap_record(15):
                        banks[bank][addr + 7] = 16
                return len(wire)
            handle.write.side_effect = write
            def receive(handle, log, matcher, **kwargs):
                wire = current[0]
                bank, addr, length = wire[5], int.from_bytes(wire[6:8], 'big'), wire[8]
                payload = bytes(banks[bank][addr:addr + length])
                response = bytes((16, 0, wire[2], 60, 5)) + wire[5:9] + payload
                return matcher(response.ljust(64, b'\0'))
            with tempfile.TemporaryDirectory() as directory, patch.object(session, 'check'), \
                    patch.object(session, 'nexus_reads', return_value=True), \
                    patch.object(session, 'receive', side_effect=receive), \
                    patch.object(probe.ProbeHandle, 'open', return_value=handle), \
                    patch.object(probe.time, 'sleep'):
                self.assertEqual(session.nexus_roundtrip(directory), not corrupt,
                                 session.evidence['channels'][-1].get('error'))
            result = session.evidence['channels'][-1]
            self.assertTrue(result['original_records_restored'])
            self.assertTrue(result['all_readable_settings_unchanged'])
            self.assertEqual({str(bank): data.hex() for bank, data in banks.items()}, original)
            handle.close.assert_called_once()

    def session(self):
        session = object.__new__(probe.Session)
        session.bus, session.address, session.root = 1, 5, '/unused'
        session.sequence, session.evidence = 0, {'channels': []}
        return session

    def test_short_send_and_short_transfer_rejection(self):
        session, handle = self.session(), Mock()
        handle.write.side_effect = len
        with patch.object(session, 'check'):
            session.send(handle, 2, b'\xf2\x00', [], short=True)
        self.assertEqual(handle.write.call_args.args[0], b'\x0f\x00\x01\x02\xf2\x00')
        handle.write.return_value, handle.write.side_effect = 5, None
        with patch.object(session, 'check'), self.assertRaises(UsbTransportError):
            session.send(handle, 2, b'\xf2\x00', [], short=True)

    def test_full_snapshots_are_bounded_and_read_only(self):
        session, handle = self.session(), Mock(_interface=0, cleanup=[])
        handle.write.side_effect = len
        def receive(handle, log, matcher, **kwargs):
            request = bytes.fromhex(log[-1]['request'])
            if request[3] == 1:
                reply = bytes((16, 0, request[2], 60, 12, 1, 1)) + bytes(57)
            else:
                reply = bytes((16, 0, request[2], 60, 5)) + request[5:9] + bytes(55)
            return matcher(reply)
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle), \
                patch.object(session, 'receive', side_effect=receive):
            self.assertTrue(session.nexus_reads())
        evidence = session.evidence['channels'][0]
        self.assertTrue(evidence['repeatable_full_profiles'])
        self.assertEqual(len(evidence['reads']), 66)
        for snapshot in evidence['snapshots']:
            self.assertEqual(set(snapshot), {'1', '2', '3', '4'})
            self.assertTrue(all(len(bytes.fromhex(v)) == 421 for v in snapshot.values()))
        for call in handle.write.call_args_list:
            wire = call.args[0]
            self.assertIn(wire[3], (1, 2, 5))
            self.assertEqual(len(wire), 4 + wire[3])
        handle.close.assert_called_once()

    def test_mismatched_sequences_fail_and_cleanup_runs(self):
        session, handle = self.session(), Mock(_interface=0, cleanup=[])
        handle.write.side_effect = len
        def receive(handle, log, matcher, **kwargs):
            request = bytes.fromhex(log[-1]['request'])
            reply = bytes((16, 0, (request[2] + 1) % 256, 60, 5)) + request[5:9] + bytes(55)
            self.assertIsNone(matcher(reply))
            return None
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle), \
                patch.object(session, 'receive', side_effect=receive):
            self.assertFalse(session.nexus_reads())
        self.assertNotIn('snapshots', session.evidence['channels'][0])
        handle.close.assert_called_once()

    def test_disconnect_stops_without_snapshot_and_releases(self):
        session, handle = self.session(), Mock(_interface=0, cleanup=[])
        handle.write.side_effect = UsbTransportError(19, 'disconnect')
        with patch.object(session, 'check'), patch.object(probe.ProbeHandle, 'open', return_value=handle):
            self.assertFalse(session.nexus_reads())
        self.assertEqual(handle.write.call_count, 1)
        handle.close.assert_called_once()

    def test_startup_candidate_restores_input_state_after_read_failure(self):
        session, handle = self.session(), Mock(_interface=0, cleanup=[])
        handle.write.side_effect = len
        with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', return_value=handle), \
                patch.object(session, 'receive', side_effect=UsbTransportError('read failed')):
            self.assertFalse(session.nexus_reads(initialize=True))
        sent = [call.args[0] for call in handle.write.call_args_list]
        self.assertEqual(sent[0], se.nexus_initialize(sent[0][2]))
        self.assertEqual(sent[-1], se.gip_power_on(sent[-1][2]))
        self.assertFalse(any(len(wire) == 64 and wire[4] == 3 for wire in sent))
        handle.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
