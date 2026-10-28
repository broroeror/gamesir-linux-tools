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

    def test_g7se_664_gip_configures_and_fallbacks_follow_the_product(self):
        product = 'GameSir-G7 SE Controller for Xbox'
        self.assertIs(profiles.detect_one(0x1069, product), profiles.G7_SE)
        for pid in (0x10a0, 0x1082):
            self.assertIs(profiles.detect_one(pid, product), profiles.G7_SE_OTHER)
        self.assertEqual(profiles.G7_SE_OTHER.write_style, 'none')
        self.assertIs(profiles.detect_one(0x1082, 'GameSir-K1 Controller for Xbox'),
                      profiles.KALEID_OTHER)
        self.assertIs(profiles.detect_one(0x1082, None), profiles.KALEID_OTHER)

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

    def test_tarantula_pid_variants_resolve_to_tarantula_profile(self):
        self.assertIs(profiles.detect_one(0x103d, 'GameSir-Tarantula Pro'), profiles.TARANTULA_PRO_8K)
        self.assertIs(profiles.detect_one(0x103c, 'GameSir-Tarantula 8K'), profiles.TARANTULA_PRO_8K)
        self.assertIn(0x103c, profiles.TARANTULA_PRO_8K.usb_products)
        self.assertIn(0x103c, profiles.TARANTULA_PRO_8K.wired_products)
        self.assertFalse(profiles.TARANTULA_PRO_8K.has_battery)

    def test_tarantula_enhanced_report_decodes_c_and_t_buttons_and_omits_battery(self):
        from vendors.gamesir.enhanced import parse_enhanced
        old_prof = profiles.active() if profiles.is_recognized() else None
        try:
            profiles.set_active(profiles.TARANTULA_PRO_8K)
            pkt = [0] * 64
            pkt[0] = 0x12
            pkt[1:5] = [128, 128, 128, 128]
            pkt[5] = 0x0f
            pkt[35] = 0x01
            pkt[36] = 42
            pkt[60] = 0x01 | 0x02 | 0x08 | 0x10 | 0x20
            pkt[61] = 0x7f
            pkt[63] = 0xff  # RT analog (does not trigger C/T buttons)
            parsed = parse_enhanced(pkt)
            for k in ('home', 'share', 'l4', 'r4', 'm',
                      'c1', 'c2', 'c3', 'c4', 't1', 't2', 't3'):
                self.assertTrue(parsed[k], k)
            self.assertFalse(parsed['l5'])
            self.assertFalse(parsed['r5'])
            self.assertEqual(parsed['battery'], 0)
            self.assertFalse(parsed['charging'])
        finally:
            profiles.set_active(old_prof)

    def test_tarantula_remap_slots_and_defaults_cover_all_buttons(self):
        from bridge import GamesirBridge
        prof = profiles.TARANTULA_PRO_8K
        names = [n for n, _a in prof.REMAP_SLOTS]
        for expected in ('Dpad Up', 'Dpad Down', 'Dpad Left', 'Dpad Right',
                         'LB', 'RB', 'LS', 'RS', 'A', 'B', 'X', 'Y',
                         'L4', 'R4', 'C1', 'C2', 'C3', 'C4',
                         'T1', 'T2', 'T3', 'LT', 'RT', 'View', 'Menu', 'Share'):
            self.assertIn(expected, names)
        old_prof = profiles.active() if profiles.is_recognized() else None
        try:
            profiles.set_active(prof)
            state.update(connected=True, profile=1, edit_profile=1,
                         selected='tar', driving='tar', controller=prof.short)
            b = GamesirBridge()
            b._apply_profile(prof)
            self.assertFalse(b.hasBattery)
            vals = {addr: [0] * ln for addr, ln in prof.read_fields()}
            for _n, addr in prof.REMAP_SLOTS:
                def_code = prof.REMAP_DEFAULTS.get(addr)
                vals[addr] = [0x01, def_code] if def_code is not None else [0x00, 0x00]
            cfg_out = b._build_config(vals)
            for n in names:
                self.assertEqual(cfg_out['remap'][n], -1, f'{n} factory self-code should decode as Default (-1)')
            b.setRemapCode('T1', -1)
            self.assertEqual(b._pending[(1, 0x04a8)]['data'], [0x01, 0x23])
            b.setRemapCode('C1', -1)
            self.assertEqual(b._pending[(1, 0x0204)]['data'], [0x01, 0x1f])
            b.setRemapCode('A', -1)
            self.assertEqual(b._pending[(1, 0x007a)]['data'], [0x00, 0x00])
        finally:
            profiles.set_active(old_prof)


if __name__ == '__main__':
    unittest.main()
