import unittest

import vendors.gamesir.config as cfg


class NumpadTargetTests(unittest.TestCase):
    def test_every_code_once(self):
        codes = sorted(c for _n, c in cfg.NUMPAD_TARGETS)
        self.assertEqual(codes, list(range(0x7a, 0x9c)))

    def test_measured_codes(self):
        # read from evdev on a Cyclone 2 and an 8K (#47)
        label = dict((c, n) for n, c in cfg.NUMPAD_TARGETS)
        for code, name in ((0x7a, 'Insert'), (0x7d, 'Delete'), (0x7f, 'PgDn'),
                           (0x80, 'Up'), (0x83, 'Right'), (0x84, 'NumLock'),
                           (0x8b, 'Num 0'), (0x95, 'Play/Pause'),
                           (0x99, 'Vol +'), (0x9a, 'Vol -')):
            self.assertEqual(label[code], name)


class RemapRecordTests(unittest.TestCase):
    def test_rebind_clears_combo_keys_but_not_the_macro_switch(self):
        # udbue's L4 after rebinding over a combo: 01 9a 68 81 (#47)
        record = cfg.full_remap_record([0x01, 0x9a])
        self.assertEqual(record, [0x01, 0x9a, 0x00, 0x00, 0x00])
        self.assertEqual(len(record), 5)    # byte 5 of a paddle block is its macro switch

    def test_default_clears_combo_keys_too(self):
        self.assertEqual(cfg.full_remap_record(cfg.remap_write_bytes(cfg.REMAP_NONE)), [0] * 5)


if __name__ == '__main__':
    unittest.main()
