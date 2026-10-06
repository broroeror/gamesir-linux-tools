"""Controller selection and edition boundaries; no USB access required."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_profile as profiles
import reader
from gs_state import state
from vendors.gamesir.models.g7pro import protocol as g7


def controller(name, pid, product='GameSir-G7 Pro'):
    return {'id': name, 'pid': pid, 'product': product, 'nodes': []}


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.old_state = dict(state)
        state.update(selected=None, driving=None)

    def tearDown(self):
        state.clear()
        state.update(self.old_state)

    def test_wuchang_wired_is_configurable_and_other_identity_is_input_only(self):
        self.assertIs(profiles.detect_one(0x10a7, 'GameSir-G7 Pro'), profiles.G7_PRO)
        self.assertEqual(g7.edition_name(0x10a7), 'Wuchang Edition (wired)')
        self.assertTrue(g7.connection_kind(0x10a7))
        self.assertIs(profiles.detect_one(0x10a8, 'GameSir-G7 Pro'), profiles.G7_PRO_OTHER)
        self.assertNotIn(0x10a8, g7.CONFIG_PIDS)
        self.assertEqual(profiles.G7_PRO_OTHER.write_style, 'none')

    def test_wired_controller_wins_over_input_only_receiver_without_hid_probe(self):
        receiver = controller('receiver', 0x10a8)
        wired = controller('wired', 0x10a7)
        with patch.object(reader, 'has_live_pad') as probe:
            self.assertIs(reader._pick_selected([receiver, wired]), wired)
            probe.assert_not_called()

    def test_explicit_selection_of_input_only_receiver_is_respected(self):
        receiver = controller('receiver', 0x10a8)
        wired = controller('wired', 0x10a7)
        state['selected'] = 'receiver'
        self.assertIs(reader._pick_selected([receiver, wired]), receiver)

    def test_legacy_live_selection_order_and_empty_dongle_fallback_remain(self):
        cyclone = controller('cyclone', 0x100b, 'GameSir-Cyclone 2')
        eight_k = controller('8k', 0x10c7, 'GameSir-G7 Pro 8K PC')
        tarantula = controller('tarantula', 0x103d, 'GameSir-Tarantula Pro')
        with patch.object(reader, '_probe_live', return_value=True):
            for first, second in ((cyclone, eight_k), (eight_k, cyclone), (tarantula, eight_k)):
                self.assertIs(reader._pick_selected([first, second]), first)
        with patch.object(reader, '_probe_live', side_effect=lambda c: c is eight_k):
            self.assertIs(reader._pick_selected([cyclone, eight_k]), eight_k)
        with patch.object(reader, '_probe_live', return_value=False):
            self.assertIs(reader._pick_selected([cyclone, eight_k]), cyclone)

    def test_shared_or_foreign_pids_do_not_gain_configuration_access(self):
        self.assertIsNone(profiles.detect_one(0x1004, 'GameSir T4 Kaleid'))
        self.assertIsNone(profiles.detect_one(0x1004, None))
        self.assertIs(profiles.detect_one(0x1004, 'GameSir-G7 Pro'), profiles.G7_PRO)
        for pid in (0x100f, 0x1010):
            self.assertNotIn(pid, g7.CONFIG_PIDS)
        self.assertIs(profiles.detect_one(0x0575, 'GameSir-Cyclone 2'), profiles.CYCLONE)
        self.assertIs(profiles.detect_one(0x0575, 'Gamepad'), profiles.G7_8K)


if __name__ == '__main__':
    unittest.main()
