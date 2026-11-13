"""Every rebind Deadband stages must pass the register-map check Apply runs (#47:
the 5-byte combo-clearing write was refused as outside the map)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup
import controller_profile as profiles
from vendors.gamesir import config as cfg


class RemapApplyTests(unittest.TestCase):
    def setUp(self):
        self.old = profiles.active() if profiles.is_recognized() else None
        self.addCleanup(profiles.set_active, self.old)

    def test_rebinds_stay_inside_the_known_register_map(self):
        for prof in (profiles.CYCLONE, profiles.G7_8K, profiles.TARANTULA_PRO_8K):
            profiles.set_active(prof)
            bank = prof.profile_banks[0]
            for name, addr in prof.REMAP_SLOTS:
                data = [0x01, 0x9a]
                if prof.remap_len(addr) == 4:
                    data = cfg.full_remap_record(data)
                with self.subTest(controller=prof.short, slot=name):
                    backup._validate_writes([(bank, addr, data)])

    def test_backups_capture_the_combo_keys(self):
        profiles.set_active(profiles.CYCLONE)
        lens = {addr: ln for addr, ln, name in backup._profile_fields() if name == 'Remap Capture'}
        self.assertEqual(list(lens.values()), [4])

    def test_rebinds_never_reach_a_continuous_trigger_flag(self):
        prof = profiles.CYCLONE
        slots = dict(prof.REMAP_SLOTS)
        for name, flag in prof.CONTINUOUS_TRIGGER_SLOTS:
            with self.subTest(slot=name):
                self.assertLessEqual(slots[name] + prof.remap_len(slots[name]), flag)


if __name__ == '__main__':
    unittest.main()
