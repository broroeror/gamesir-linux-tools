"""The G7 Pro's media keys and doctor's media-key hint (#47)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doctor
from vendors.gamesir import config as cfg


class MediaKeyTests(unittest.TestCase):
    def test_doctor_spots_the_unreadable_consumer_range(self):
        desc = bytes(76) + bytes.fromhex('19002bffff0000') + bytes(131)
        self.assertTrue(doctor._media_keys_dropped(desc))

    def test_doctor_is_quiet_once_the_fixup_has_run(self):
        desc = bytes(76) + bytes.fromhex('19002aff03a4b4') + bytes(131)
        self.assertFalse(doctor._media_keys_dropped(desc))

    def test_doctor_ignores_other_descriptors(self):
        self.assertFalse(doctor._media_keys_dropped(bytes(233)))

    def test_picker_offers_the_volume_keys(self):
        names = dict(cfg.NUMPAD_TARGETS)
        self.assertEqual((names['Vol +'], names['Vol -'], names['Mute']), (0x99, 0x9a, 0x9b))


if __name__ == '__main__':
    unittest.main()
