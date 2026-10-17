"""G7 SE firmware 6.64 reply framing; no USB access required."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vendors.gamesir.models.g7se import protocol as se

# Read reply captured on 3537:1069 descriptor 6.64 for request 0f 00 0b 05 04 01 00 00 37.
REPLY_664 = bytes.fromhex('10000a3c0501000037' + '00' * 31 + '4b4b4b4b00000132320002' + '00' * 13)


class SequenceEchoTests(unittest.TestCase):
    def test_630_requires_the_echoed_sequence(self):
        with patch.object(se, 'TESTED_DESCRIPTOR', 0x0630):
            self.assertFalse(se.reply_sequence_ok(REPLY_664, 0x0b))
            self.assertTrue(se.reply_sequence_ok(REPLY_664, 0x0a))

    def test_664_replies_carry_their_own_counter(self):
        with patch.object(se, 'TESTED_DESCRIPTOR', 0x0664):
            self.assertTrue(se.reply_sequence_ok(REPLY_664, 0x0b))
            self.assertIsNotNone(se.match_read(REPLY_664, 1, 0, 55))
            self.assertIsNone(se.match_read(REPLY_664, 2, 0, 55))

    def test_unknown_firmware_keeps_the_strict_check(self):
        with patch.object(se, 'TESTED_DESCRIPTOR', 0x0700):
            self.assertFalse(se.reply_sequence_ok(REPLY_664, 0x0b))


if __name__ == '__main__':
    unittest.main()


class Layout664Tests(unittest.TestCase):
    """Packets compared byte for byte with Nexus 2.5.8 captures on 1069/6.64."""

    def setUp(self):
        se.select(0x0664)

    def tearDown(self):
        se.select(0x0630)

    def write(self, captured_seq_free):
        return bytes.fromhex(captured_seq_free).ljust(64, b'\0')

    def test_rear_remaps_match_nexus(self):
        self.assertEqual(se.remap_write(0x76, 1, 0x00b3, se.remap_record(9, 0x00b3)),
                         self.write('0f00763c030100b30109'))          # L4 -> A
        self.assertEqual(se.remap_write(0x76, 1, 0x00c1, se.remap_record(10, 0x00c1)),
                         self.write('0f00763c030100c1010a'))          # R4 -> B
        self.assertEqual(se.remap_record(-1, 0x00b3), b'\x11')       # L4 default
        self.assertEqual(se.remap_record(-1, 0x00c1), b'\x12')       # R4 default

    def test_decode_treats_own_code_as_default(self):
        self.assertEqual(se.decode_remap(b'\x11', 0x00b3), -1)
        self.assertEqual(se.decode_remap(b'\x0b', 0x00b3), 11)       # X
        with self.assertRaises(ValueError):
            se.decode_remap(b'\x12', 0x00b3)                         # R4's code on L4
        with self.assertRaises(ValueError):
            se.decode_remap(b'\x04\x00\x00\x00\x00\x00\x01\x0f', 0x00b3)

    def test_rate_is_per_profile_and_matches_nexus(self):
        self.assertEqual(se.rate_write(0x0e, 1, b'\x02'), self.write('0f000e3c03010030010' + '2'))
        self.assertEqual(se.rate_banks(2), (2,))
        self.assertTrue(se.allowed_setting_read(1, 0x0030, 1))
        self.assertFalse(se.allowed_setting_read(1, 0x0036, 1))
        self.assertTrue(se.allowed_setting_read(1, 0x00b3, 1))
        self.assertFalse(se.allowed_setting_read(1, 0x00b3, 8))

    def test_app_guard_accepts_only_these_writes(self):
        ok = se.remap_write(5, 2, 0x00c1, b'\x05')
        self.assertTrue(se.allowed_app_request(ok))
        bad = bytearray(ok); bad[9] = 0x20                           # unknown target
        self.assertFalse(se.allowed_app_request(bytes(bad)))
        self.assertFalse(se.allowed_app_request(self.write('0f00053c030100ba0101')))

    def test_630_layout_is_unchanged(self):
        se.select(0x0630)
        self.assertEqual((se.PID, se.POLL_RATE, se.REMAP_LEN), (0x1010, 0x0036, 8))
        self.assertEqual(se.rate_banks(2), (1, 2, 3, 4))
        self.assertEqual(se.remap_record(-1), bytes(8))
        self.assertFalse(se.select(0x0700))
        self.assertEqual(se.TESTED_DESCRIPTOR, 0x0630)
