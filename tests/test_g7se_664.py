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


class FullView664Tests(unittest.TestCase):
    """Read-only whole-bank view: 6.64 banks decode with the G7 Pro map."""

    BANK1 = bytes.fromhex((Path(__file__).parent / 'fixtures' / 'g7se_664_bank1.hex')
                          .read_text().replace('\n', ''))

    def setUp(self):
        se.select(0x0664)

    def tearDown(self):
        se.select(0x0630)

    def test_view_reads_cover_the_bank_and_pass_the_guard(self):
        reqs = se.view_requests(1)
        self.assertEqual(sum(ln for _b, _a, ln in reqs), se.PROFILE_SIZE)
        self.assertTrue(all(ln <= se.READ_CHUNK for _b, _a, ln in reqs))
        for bank, addr, ln in reqs:
            self.assertTrue(se.allowed_setting_read(bank, addr, ln))
            self.assertTrue(se.allowed_app_request(
                se.nexus_request(1, 0x05, bytes((0x04, bank, addr >> 8, addr & 0xff, ln)))))
        self.assertFalse(se.allowed_setting_read(4, 0, se.READ_CHUNK))      # not a profile
        self.assertFalse(se.allowed_setting_read(1, 1, se.READ_CHUNK))      # off-grid

    def test_view_is_read_only(self):
        # Widening reads must not widen writes: a deadzone write is still refused.
        self.assertFalse(se.allowed_app_request(
            bytes.fromhex('0f00053c0301013f0105').ljust(64, b'\0')))

    def test_630_has_no_full_view(self):
        se.select(0x0630)
        self.assertFalse(se.FULL_VIEW)
        self.assertFalse(se.allowed_setting_read(1, 0, se.READ_CHUNK))

    def test_stitch_and_decode_with_the_g7_pro_map(self):
        from vendors.gamesir.models.g7pro import protocol as g7
        parts = {off: self.BANK1[off:off + ln] for _b, off, ln in se.view_requests(1)}
        blob = se.stitch_view(1, lambda bank, off: parts.get(off))
        self.assertEqual(blob, self.BANK1)
        self.assertIsNone(se.stitch_view(1, lambda bank, off: None))
        p = g7.decode_profile(blob.ljust(g7.PROFILE_BLOB_SIZE, b'\0'))
        self.assertEqual((p['vib_l'], p['vib_r'], p['vib_trigger_l'], p['vib_trigger_r']),
                         (75, 75, 75, 75))
        self.assertEqual((p['st_dz_min'], p['st_dz_max'], p['rs_dz_min'], p['rs_dz_max']),
                         (10, 100, 10, 100))
        self.assertEqual((p['lt_dz_min'], p['lt_dz_max'], p['rt_dz_min'], p['rt_dz_max']),
                         (5, 95, 5, 95))
        self.assertEqual(p['st_curve']['points'], [[42, 64], [113, 128], [184, 191]])
        self.assertEqual(p['st_sensitivity'], 50)


if __name__ == '__main__':
    unittest.main()
