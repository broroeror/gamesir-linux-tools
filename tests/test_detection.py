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
from vendors.gamesir.models.supernova import protocol as supernova


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

    def test_super_nova_dongle_is_configurable_and_wired_is_input_only(self):
        # The dongle names itself only "GameSir-Dongle"; the session checks the
        # device type, so detection must not depend on the product string.
        for product in ('GameSir-Dongle', None):
            self.assertIs(profiles.detect_one(0x103e, product), profiles.SUPER_NOVA)
        self.assertEqual(supernova.CONFIG_PIDS, (0x103e,))
        self.assertIs(profiles.detect_one(0x100e, 'GameSir Super Nova'),
                      profiles.SUPER_NOVA_OTHER)
        self.assertEqual(supernova.identity_name(0x100e), 'wired')
        self.assertEqual(profiles.SUPER_NOVA_OTHER.write_style, 'none')
        self.assertEqual(profiles.SUPER_NOVA_OTHER.profile_banks, ())
        # Its neighbour stays the Tarantula: adjacency is not identity.
        self.assertIs(profiles.detect_one(0x103d, 'GameSir-Tarantula Pro'),
                      profiles.TARANTULA_PRO_8K)

    def test_super_nova_profile_maps_exactly_the_four_verified_features(self):
        p = profiles.SUPER_NOVA
        self.assertEqual(p.write_style, 'supernova')
        self.assertEqual(p.transport, 'hidraw_cmd')   # not a claiming session
        self.assertFalse(p.software_profile_switch)
        for f in ('VIB_L', 'VIB_R', 'ST_DZ_MIN', 'RS_DZ_MIN', 'LT_DZ_MIN', 'RT_DZ_MIN'):
            self.assertIsNotNone(getattr(p, f), f)
        for f in ('ST_DZ_MAX', 'ST_ADZ_MIN', 'ST_CURVE', 'ST_TRAJ', 'LT_DZ_MAX',
                  'LT_ADZ_MIN', 'LT_CURVE', 'LT_HAIR', 'POLL_RATE'):
            self.assertIsNone(getattr(p, f), f)
        self.assertEqual((p.lighting_style, p.has_motion, p.has_macros, p.POLL_RATES),
                         ('none', False, False, ()))
        self.assertEqual([n for n, _ in p.REMAP_SLOTS], [n for n, _ in supernova.REMAP_SOURCES])

    def test_wired_super_nova_does_not_steal_selection_from_a_configurable_pad(self):
        nova = controller('nova', 0x100e, 'GameSir Super Nova')
        wired = controller('wired', 0x10a7)
        self.assertIs(reader._pick_selected([nova, wired]), wired)

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
