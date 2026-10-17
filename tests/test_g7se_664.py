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
