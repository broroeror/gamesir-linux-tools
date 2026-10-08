"""Diagnostic authentication framing checked against raw Windows packets."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from vendors.gamesir.models.g7se import auth
from vendors.gamesir.models.g7se import gip



FIXTURE = Path(__file__).parent/'fixtures/g7se-0630-auth.json'


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())

    def test_framing_matches_every_captured_auth_packet(self):
        for entry in self.fixture['packets']:
            wire = bytes.fromhex(entry['request'])
            d = gip.decode(wire)
            encoded = auth.frame(d['sequence'], d['options'], d['payload'],
                d['offset'] if d['options'] & 128 else None)
            self.assertEqual(gip.decode(encoded), d)
            if entry['endpoint'] == 2:
                self.assertEqual(encoded, wire)

    def test_host_bodies_and_client_bounds_match_capture(self):
        commands = {item['sequence']: bytes.fromhex(item['body'])
                    for item in self.fixture['messages'] if item['endpoint'] == 2}
        for command, sequence, length in ((2,2,80),(3,3,1024),(8,6,64)):
            self.assertEqual(auth.request(command,length), commands[sequence])
        for sequence, command in ((1,1),(4,5),(5,7)):
            body = commands[sequence]
            self.assertEqual(auth.message(command,body[10:-8]),body)
        for item in self.fixture['messages']:
            body = bytes.fromhex(item['body'])
            if item['endpoint'] == 130 and len(body) > 6:
                self.assertEqual(auth.client_data(body,body[3]),body[10:])
                for mutation in (body[:-1], body[:2]+b'\x01'+body[3:],body[:7]+b'\x02'+body[8:]):
                    with self.assertRaises(ValueError):
                        auth.client_data(mutation,body[3])

    def test_reassembly_ack_is_limited_to_requested_auth_sequence(self):
        for sequence in (2,3,6):
            transfer = gip.IdentificationTransfer(command=6,minimum=2,expected_sequence=sequence)
            value = None
            for item in self.fixture['packets']:
                wire=bytes.fromhex(item['request'])
                if item['endpoint'] != 130 or wire[2] != sequence:
                    continue
                value,ack=transfer.accept(wire)
                if ack:
                    self.assertEqual(ack[4:7],bytes((0,6,32)))
            expected=next(bytes.fromhex(item['body']) for item in self.fixture['messages']
                          if item['endpoint']==130 and item['sequence']==sequence)
            self.assertEqual(value,expected)

    def test_wrong_fresh_transcript_prevents_completion(self):
        exchange=auth.Exchange(Mock(),Mock(),[])
        hello=bytes(80)
        queries=[(bytes(6)+bytes(4)+hello,hello), (bytes(6)+b'certificate',b'certificate'),
                 (b'',bytes(64))]
        with patch.object(exchange,'host'), patch.object(exchange,'query',side_effect=queries), \
                patch.object(auth,'encrypt_secret',return_value=bytes(256)), patch.object(exchange,'raw') as raw:
            with self.assertRaisesRegex(ValueError,'transcript'):
                exchange.run()
        raw.assert_not_called()

    def test_host_chunk_ack_matches_capture_and_rejects_mutations(self):
        exchange = auth.Exchange(Mock(), Mock(), [])
        for received in (58, 274):
            wire = next(bytes.fromhex(value) for value in self.fixture['acknowledgements']
                        if bytes.fromhex(value)[2] == 4 and int.from_bytes(bytes.fromhex(value)[7:9], 'little') == received)
            def receive(handle, log, match, seconds):
                for index in (2, 5, 6, 7, 11):
                    mutation = bytearray(wire)
                    mutation[index] ^= 1
                    self.assertIsNone(match(bytes(mutation)))
                return match(wire)
            exchange.session.receive.side_effect = receive
            exchange.chunk_ack(4, received, 274)
        exchange.session.receive.side_effect = None
        exchange.session.receive.return_value = None
        with self.assertRaisesRegex(OSError, 'timed out'):
            exchange.chunk_ack(4, 58, 274)

    def test_one_byte_rejection_is_reported_and_stale_rejection_ignored(self):
        exchange = auth.Exchange(Mock(), Mock(), [])
        def receive(handle, log, match, seconds):
            self.assertIsNone(match(bytes.fromhex('0630020107')))
            return match(bytes.fromhex('0630030107'))
        exchange.session.receive.side_effect = receive
        with self.assertRaisesRegex(ValueError, 'status 0x07'):
            exchange.receive(3)

    def test_public_certificate_can_encrypt_fresh_secret_with_openssl(self):
        certificate=next(bytes.fromhex(i['body'])[10:] for i in self.fixture['messages']
                         if i['endpoint']==130 and len(bytes.fromhex(i['body']))>500)
        first=auth.encrypt_secret(certificate,b'a'*48)
        second=auth.encrypt_secret(certificate,b'a'*48)
        self.assertEqual(len(first),256)
        self.assertNotEqual(first,second)
        with self.assertRaises(ValueError):
            auth.encrypt_secret(b'incomplete',bytes(48))


if __name__ == '__main__':
    unittest.main()
