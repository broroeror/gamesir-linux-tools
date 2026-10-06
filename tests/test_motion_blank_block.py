"""Blank gyro block repair (G7 Pro).

On an Amazon edition (10ba, fw 2.36) profile 1's gyro blocks were zeros apart
from the deadzones. Single-field writes into such a block were ignored by the
firmware (Right Stick selected, gyro drove the left stick). Writing a complete
default block fixed it on the same pad. These tests pin the repair: a blank
section's first edit stages ONE full block containing the defaults plus the
edit; later edits land in the same block; Discard drops it; a real (non-blank)
section -- including the Wuchang's Tilt, whose axis code 0x02 is not in the
app's list -- keeps single-field writes.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

import controller_profile as profiles  # noqa: E402
from bridge import GamesirBridge  # noqa: E402
from gs_state import state  # noqa: E402
from vendors.gamesir import motion  # noqa: E402
from vendors.gamesir.models.g7pro import protocol as g7  # noqa: E402
from test_motion import captured_blob, read_values  # noqa: E402

# The Amazon pad's real bytes at 0x19c (both sections), as read on 2026-10-06.
AMAZON_BLANK = bytes([0, 0, 0, 1, 0, 0x64, 0, 0x64] + [0] * 26
                     + [0, 0, 0, 1, 5, 0x64, 0, 0x64] + [0] * 26)


def blob_with(motion_bytes):
    blob = bytearray(g7.PROFILE_BLOB_SIZE)
    blob[0x19c:0x19c + len(motion_bytes)] = motion_bytes
    return blob


class BlankBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def load(self, blob):
        mp = g7.MOTION_MAP
        vals = read_values(mp, blob)
        self.bridge._m = {n: motion.decode_section(mp, vals, off) for n, off in motion.sections(mp)}
        self.bridge._m_loaded = copy.deepcopy(self.bridge._m)
        self.bridge._m_profile = 1
        self.bridge._m_init = {}
        self.bridge._pending = {}

    def setUp(self):
        self.old_state = dict(state)
        profiles.set_active(profiles.G7_PRO)
        state.update(profile=1, edit_profile=1, selected='t', driving='t', config_claimed=True)
        self.bridge = GamesirBridge()
        for timer in (self.bridge._input_timer, self.bridge._status_timer,
                      self.bridge._light_timer, self.bridge._sensor_timer):
            timer.stop()

    def tearDown(self):
        self.bridge.deleteLater()
        state.clear()
        state.update(self.old_state)
        profiles.set_active(None)

    def test_blank_section_first_edit_stages_one_full_block(self):
        self.load(blob_with(AMAZON_BLANK))
        self.assertTrue(motion.is_blank_section(g7.MOTION_MAP, self.bridge._m_loaded['Aim']))
        self.bridge.setMotionEnum('Aim', 'output', 1)          # "Right Stick" (code 2)
        writes = list(self.bridge._pending.values())
        self.assertEqual(len(writes), 1)
        w = writes[0]
        self.assertEqual(w['addr'], 0x19c)
        expected = bytearray(g7.MOTION_MAP['default_blocks']['Aim'])
        expected[0x1b7 - 0x19c] = 2
        self.assertEqual(bytes(w['data']), bytes(expected))
        self.assertEqual(w['data'][0], 0, 'initialising must not switch the gyro on')
        self.assertEqual(self.bridge.motionAim['output'], 1)
        self.assertNotEqual(self.bridge.motionAim['curve_points'], [[0, 0]] * 3)

    def test_later_edits_land_in_the_same_block(self):
        self.load(blob_with(AMAZON_BLANK))
        self.bridge.setMotionEnum('Aim', 'output', 1)
        self.bridge.setMotionEnum('Aim', 'act_method', 3)      # Always on
        writes = list(self.bridge._pending.values())
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['data'][0], 3)
        self.assertEqual(writes[0]['data'][0x1b7 - 0x19c], 2)

    def test_discard_drops_the_block_and_restores_the_blank_view(self):
        self.load(blob_with(AMAZON_BLANK))
        self.bridge.setMotionEnum('Aim', 'output', 1)
        self.bridge.discardConfig()
        self.assertEqual(self.bridge._pending, {})
        self.assertEqual(self.bridge._m_init, {})
        self.assertTrue(motion.is_blank_section(g7.MOTION_MAP, self.bridge._m['Aim']))

    def test_real_blocks_keep_single_field_writes(self):
        self.load(captured_blob())                              # the Wuchang's real storage
        for name in ('Aim', 'Tilt'):
            self.assertFalse(motion.is_blank_section(g7.MOTION_MAP, self.bridge._m_loaded[name]),
                             f'{name} is a real block')
        self.bridge.setMotionEnum('Aim', 'output', 1)
        self.assertEqual([(r['addr'], r['data']) for r in self.bridge._pending.values()],
                         [(0x1b7, [2])])

    def test_other_models_never_repair(self):
        for prof in (profiles.CYCLONE, profiles.G7_8K, profiles.TARANTULA_PRO_8K):
            self.assertFalse(motion.is_blank_section(prof.motion, {'curve_points': [[0, 0]] * 3}))


if __name__ == '__main__':
    unittest.main()
