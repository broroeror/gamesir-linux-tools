import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

import g7se_probe as probe
from vendors.gamesir.models.g7se import gip, protocol as se
from vendors.gamesir.usb_transport import UsbTransportError


def frame(payload, options=0x20, offset=0, sequence=7):
    def integer(value):
        out = bytearray()
        while value >= 128:
            out.append((value & 127) | 128)
            value >>= 7
        out.append(value)
        return out
    length = integer(len(payload))
    position = integer(offset) if options & 128 else b''
    if (3 + len(length) + len(position)) % 2:
        length[-1] |= 128
        length.append(0)
    return bytes((4, options, sequence)) + length + position + payload


class GipTests(unittest.TestCase):
    def test_confirmed_hardware_identification_transcript(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'g7se-0630-gip-identification.json').read_text())
        transfer = gip.IdentificationTransfer()
        acknowledgments, value = [], None
        transmitted = []
        for event in fixture['events']:
            if 'response' in event:
                value, ack = transfer.accept(bytes.fromhex(event['response']))
                if ack is not None:
                    acknowledgments.append(ack.hex())
            elif event.get('stage') == 'identification-ack':
                transmitted.append(event['request'])
        self.assertEqual(acknowledgments, transmitted)
        self.assertEqual(value.hex(), fixture['payload'])
        self.assertEqual(gip.describe(value), fixture['decoded'])

    def test_fixed_length_read_changes_only_payload_length(self):
        request = se.fixed_length_read_request(7, 1, 0, 55)
        original = se.read_request(7, 1, 0, 55)
        self.assertEqual(request[:3] + request[4:], original[:3] + original[4:])
        self.assertEqual(request[3:9], bytes.fromhex('3c 04 01 00 00 37'))
        with self.assertRaises(ValueError):
            se.fixed_length_read_request(7, 5, 0, 55)

    def test_request_exact_and_sequence_bounded(self):
        self.assertEqual(gip.identify(7), b'\x04\x20\x07\x00')
        for sequence in (-1, 0, 256):
            with self.assertRaises(ValueError):
                gip.identify(sequence)

    def test_single_reply(self):
        value = bytes(32)
        transfer = gip.IdentificationTransfer()
        self.assertEqual(transfer.accept(frame(value)), (value, None))
        self.assertEqual(gip.describe(value)['client_commands'], [])

    def test_chunk_reassembly_and_exact_ack(self):
        payload = bytes(range(128))
        transfer = gip.IdentificationTransfer()
        value, ack = transfer.accept(frame(payload[:58], 0xf0, 128))
        self.assertIsNone(value)
        self.assertEqual(ack, bytes.fromhex('01 20 07 09 00 04 20 3a 00 00 00 46 00'))
        self.assertEqual(transfer.accept(frame(payload[58:116], 0xa0, 58)), (None, None))
        _, ack = transfer.accept(frame(payload[116:], 0xb0, 116))
        self.assertEqual(ack[-2:], b'\x00\x00')
        self.assertEqual(transfer.accept(frame(b'', 0xa0, 128)), (payload, None))

    def test_invalid_chunks_cannot_trigger_ack_or_change_buffer(self):
        cases = [frame(bytes(32), 0xf0, 4097), frame(bytes(32), 0x70),
                 frame(bytes(32), 0xb0, 0), frame(b'', 0xf0, 32)]
        for packet in cases:
            transfer = gip.IdentificationTransfer()
            with self.subTest(packet=packet.hex()), self.assertRaises(ValueError):
                transfer.accept(packet)
            self.assertEqual(transfer.data, b'')
            self.assertIsNone(transfer.total)
        transfer = gip.IdentificationTransfer()
        transfer.accept(frame(bytes(32), 0xf0, 64))
        for packet in (frame(bytes(32), 0xb0, 33), frame(bytes(32), 0xb0, 32, 8),
                       frame(b'', 0xb0, 32), frame(bytes(33), 0xb0, 32)):
            with self.assertRaises(ValueError):
                transfer.accept(packet)
        self.assertEqual(len(transfer.data), 32)

    def test_malformed_packets_and_unrelated_clients(self):
        for packet in (b'', b'\x04\x20\x01\x80', b'\x04\x20\x01\x80\x80\x80',
                       b'\x04\x20\x01\x01', bytes(65)):
            with self.assertRaises(ValueError):
                gip.decode(packet)
        for options in (0x21, 0):
            self.assertEqual(gip.IdentificationTransfer().accept(frame(bytes(32), options)),
                             (None, None))

    def test_descriptor_tables_and_bounds(self):
        data = bytearray(16)
        data[0:2] = (16).to_bytes(2, 'little')
        command = bytearray(23)
        command[2], command[3], command[7] = 0x20, 14, 0
        data += bytes((1,)) + command
        data[10:12] = len(data).to_bytes(2, 'little')
        data += b'\x01\x07\x00Gamepad'
        decoded = gip.describe(bytes(16) + data)
        self.assertEqual(decoded['classes'], ['Gamepad'])
        self.assertEqual(decoded['client_commands'][0]['command'], 0x20)
        for payload in (bytes(31), bytes(16) + data[:-1],
                        bytes(16) + b'\xff\xff' + bytes(14)):
            with self.assertRaises(ValueError):
                gip.describe(payload)

    def session(self):
        session = object.__new__(probe.Session)
        session.bus, session.address, session.root = 1, 14, '/unused'
        session.sequence, session.evidence = 0, {'channels': []}
        return session

    def test_probe_timeouts_allowlisted_requests_and_cleanup(self):
        session = self.session()
        handles = [Mock(_interface=0, cleanup=[]), Mock(_interface=2, original_alt=0, cleanup=[])]
        closed = []
        for handle in handles:
            handle.write.side_effect = len
            handle.close.side_effect = lambda h=handle: closed.append(h._interface)
        with patch.object(session, 'check'), patch.object(session, 'receive', return_value=None), \
                patch.object(probe.time, 'sleep'), \
                patch.object(probe.ProbeHandle, 'open', side_effect=handles):
            self.assertFalse(session.identify_gip())
        self.assertEqual(closed, [2, 0])
        evidence = session.evidence['channels'][0]
        self.assertFalse(evidence['repeatable_identification'])
        self.assertEqual(len(evidence['reads']), 8)
        for handle in handles:
            for call in handle.write.call_args_list:
                packet = call.args[0]
                self.assertIn(packet[0], (4, 5, 15))
                if packet[0] == 4:
                    self.assertEqual(packet, gip.identify(packet[2]))
                if packet[0] == 15:
                    self.assertIn(packet[3], (1, 2, 5))

    def test_session_change_and_disconnect_always_close(self):
        for error in (UsbTransportError('session changed'), UsbTransportError(19, 'disconnect')):
            session, handle = self.session(), Mock(_interface=0, cleanup=[])
            with patch.object(session, 'check', side_effect=[None, error]), \
                    patch.object(probe.ProbeHandle, 'open', return_value=handle):
                self.assertFalse(session.identify_gip())
            handle.write.assert_not_called()
            handle.close.assert_called_once()

    def test_fixed_framing_requires_matching_advertised_metadata(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'g7se-0630-gip-identification.json').read_text())
        payload = bytes.fromhex(fixture['payload'])
        for second, expected in ((payload, 4), (None, 0), (bytes(32), 0)):
            session = self.session()
            handles = [Mock(_interface=0, cleanup=[]), Mock(_interface=2, cleanup=[], original_alt=0)]
            for handle in handles:
                handle.write.side_effect = len
            with patch.object(session, 'check'), patch.object(probe.time, 'sleep'), \
                    patch.object(probe.ProbeHandle, 'open', side_effect=handles), \
                    patch.object(session, 'receive', side_effect=[payload, second] + [None] * 13):
                self.assertFalse(session.identify_gip())
            fixed = [c.args[0] for c in handles[0].write.call_args_list
                     if c.args[0][:2] == b'\x0f\x00' and c.args[0][3] == 60]
            self.assertEqual(len(fixed), expected)
            for wire in fixed:
                self.assertEqual(wire, se.fixed_length_read_request(wire[2], 1, 0, wire[8]))


if __name__ == '__main__':
    unittest.main()
