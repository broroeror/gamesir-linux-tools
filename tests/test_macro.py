import unittest

import controller_profile as profiles
import vendors.gamesir.macro as macro


class MacroBlockTests(unittest.TestCase):
    def test_short_macro_clears_the_old_tail(self):
        # the firmware plays past `count` until an empty step (#51)
        out = macro.block_bytes([{'target': 9, 'hold': 100, 'delay': 100}], 31)
        self.assertEqual(out[:6], [1, 9, 0, 100, 0, 100])
        self.assertEqual(len(out), 1 + 31 * macro.EVENT_LEN)
        self.assertFalse(any(out[6:]))

    def test_macro_writes_stay_inside_their_paddle_block(self):
        for prof in profiles.ALL:
            if not prof.has_macros:
                continue
            bases = sorted(b for _n, b in prof.MACRO_SLOTS)
            stride = min(b - a for a, b in zip(bases, bases[1:]))
            end = macro.COUNT_OFF + len(macro.block_bytes([], prof.macro_max))
            self.assertLessEqual(end, stride, prof.name)

    def test_8k_keeps_the_setting_byte_at_the_end_of_each_block(self):
        end = macro.COUNT_OFF + len(macro.block_bytes([], profiles.G7_8K.macro_max))
        self.assertLessEqual(end, 0xa8)


if __name__ == '__main__':
    unittest.main()
