"""Super Nova editor: config decode and staged-edit writes, against the
capture-backed simulated pad. Expected bytes are copied from captures 02-05 of
GameSir Connect driving a real pad. No USB access required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_supernova_config import FakePad
from vendors.gamesir.models.supernova import config as nova
from vendors.gamesir.models.supernova import editor
from vendors.gamesir.models.supernova import protocol as sn


def h(s):
    return bytes.fromhex(s)


def key_addr(name):
    return sn.VADDR_KEY | dict(sn.REMAP_SOURCES)[name]


class DecodeTests(unittest.TestCase):
    def test_the_captured_pad_decodes_to_its_settings(self):
        cfg, blocks = editor.read_config(FakePad())
        self.assertEqual((cfg['vib_l'], cfg['vib_r']), (75, 75))
        self.assertEqual((cfg['st_dz_min'], cfg['rs_dz_min']), (5, 5))
        self.assertEqual((cfg['lt_dz_min'], cfg['rt_dz_min']), (5, 5))
        self.assertEqual((cfg['st_dz_max'], cfg['lt_dz_max']), (100, 95))
        self.assertEqual(set(cfg['remap']), {n for n, _ in sn.REMAP_SOURCES})
        self.assertTrue(all(v == -1 for v in cfg['remap'].values()))

    def test_reading_never_writes(self):
        pad = FakePad()
        editor.read_config(pad)
        self.assertEqual(pad.writes(), [])

    def test_a_t3_pro_behind_the_shared_dongle_is_refused(self):
        with self.assertRaises(nova.PadError):
            editor.read_config(FakePad(device_type=0))

    def test_remap_decodes(self):
        a = h('00 00 00 00 00 00 01 00 00 01 01 01 00 00 00 00')     # capture 03: A -> B
        self.assertEqual(editor.decode_remap(a), sn.KEYS['CIR'])
        default = h('00 00 00 00 00 00 01 00 00 00 01 01 01 00 00 00')
        self.assertEqual(editor.decode_remap(default), -1)
        keyboard = h('00 00 00 00 00 00 01 00 00 01 02 01 04 00 00 00')  # type 2
        self.assertEqual(editor.decode_remap(keyboard), editor.REMAP_FOREIGN)
        to_paddle = h('00 00 00 00 00 00 01 00 00 01 01 01 24 00 00 00')
        self.assertEqual(editor.decode_remap(to_paddle), editor.REMAP_FOREIGN)


class ApplyTests(unittest.TestCase):
    def _block(self, pad, key):
        return pad.store[f'get_{nova.BLOCKS[key].kind}/{bytes(nova.BLOCKS[key].args).hex()}']

    def test_each_feature_writes_what_gamesirs_app_writes(self):
        cases = (
            (sn.VADDR_VIB + sn.VIB_LEFT, b'\x19', 'vibrate_param',
             '19 4b 00 00 4b 4b'),                                       # capture 02 byte 0
            (sn.VADDR_TRIG_DZ + 1, b'\x0a', 'trigger_param/01',
             '01 00 0a 14 0a 00 17 10 35 32 52 54 5f 64 00 32'),         # capture 05
            (sn.VADDR_STICK_DZ + 0, b'\x0a', 'stick_curve/00/00',
             '00 00 00 00 00 00 00 01 32 0a 00 18 10 37 32 56 54 64 64 00 32'),  # capture 04
            (key_addr('A'), bytes((1, sn.KEYS['CIR'])), 'key_mapping/00/01',
             '00 00 00 00 00 00 01 00 00 01 01 01 00 00 00 00'),         # capture 03
        )
        for addr, data, key, wire in cases:
            pad = FakePad()
            self.assertEqual(editor.apply_edits(pad, {addr: data}), [key], key)
            self.assertEqual(self._block(pad, key), h(wire), key)
            self.assertEqual(pad.saves, 1, key)

    def test_two_edits_to_one_block_are_one_write(self):
        pad = FakePad()
        editor.apply_edits(pad, {sn.VADDR_VIB + sn.VIB_LEFT: b'\x19',
                                 sn.VADDR_VIB + sn.VIB_RIGHT: b'\x32'})
        self.assertEqual(pad.writes(), ['set_vibrate_param', 'save_config_page'])
        self.assertEqual(self._block(pad, 'vibrate_param')[:2], h('19 32'))

    def test_several_blocks_are_saved_once(self):
        pad = FakePad()
        written = editor.apply_edits(pad, {sn.VADDR_VIB: b'\x19',
                                           sn.VADDR_TRIG_DZ: b'\x0a'})
        self.assertEqual(sorted(written), ['trigger_param/00', 'vibrate_param'])
        self.assertEqual(pad.saves, 1)

    def test_default_maps_a_button_back_to_itself(self):
        pad = FakePad()
        editor.apply_edits(pad, {key_addr('A'): bytes((1, sn.KEYS['CIR']))})
        editor.apply_edits(pad, {key_addr('A'): b'\x00\x00'})
        cfg, _ = editor.read_config(pad)
        self.assertEqual(cfg['remap']['A'], -1)

    def test_an_unchanged_edit_writes_and_saves_nothing(self):
        pad = FakePad()
        self.assertEqual(editor.apply_edits(pad, {sn.VADDR_VIB: b'\x4b'}), [])
        self.assertEqual((pad.writes(), pad.saves), ([], 0))

    def test_a_failure_on_a_later_block_undoes_the_earlier_ones(self):
        pad = FakePad()
        before = nova.snapshot(pad)
        real = pad.request

        def flaky(name, payload=b''):
            if name == 'set_trigger_param':
                return b'\x01'                      # the pad rejects this one
            return real(name, payload)
        pad.request = flaky
        with self.assertRaises(nova.PadError):
            editor.apply_edits(pad, {sn.VADDR_VIB: b'\x19', sn.VADDR_TRIG_DZ: b'\x0a'})
        pad.request = real
        self.assertEqual(nova.diff(before, nova.snapshot(pad)), {})
        self.assertEqual(pad.saves, 0)

    def test_bad_edits_are_refused_before_anything_is_written(self):
        for addr, data in ((sn.VADDR_VIB, b'\x65'),                    # 101 %
                           (sn.VADDR_TRIG_DZ, b'\x5f'),                # = end (95)
                           (key_addr('A'), bytes((1, sn.KEYS['FL1']))),  # paddle target
                           (key_addr('A'), b'\x01'),                   # no target
                           (0x0700, b'\x01')):                         # not a feature
            pad = FakePad()
            with self.assertRaises(nova.PadError, msg=f'{addr:#06x} {data.hex()}'):
                editor.apply_edits(pad, {addr: data})
            self.assertEqual(pad.writes(), [])

    def test_a_t3_pro_is_never_written(self):
        pad = FakePad(device_type=0)
        with self.assertRaises(nova.PadError):
            editor.apply_edits(pad, {sn.VADDR_VIB: b'\x19'})
        self.assertEqual(pad.writes(), [])


if __name__ == '__main__':
    unittest.main()
