"""Super Nova framing, layouts and safety rails; no USB access required.

Byte strings marked "capture NN" are copied from USBPcap captures of GameSir
Connect 1.16.7 driving a real Super Nova over its dongle (captures/NN_*.pcapng).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vendors.gamesir.models.supernova import protocol as sn


def h(s):
    return bytes.fromhex(s)


class FramingTests(unittest.TestCase):
    def test_requests_match_the_capture_byte_for_byte(self):
        cases = {   # capture 01 unless noted
            'get_device_info': ((), '07 03 0a 01'),
            'get_key_mapping': ((0x00, 0x24), '07 05 05 02 00 24'),
            'get_stick_curve': ((0x01, 0x00), '07 05 02 02 01 00'),
            'get_trigger_param': ((0x01,), '07 04 03 02 01'),
            'get_vibrate_param': ((), '07 03 06 02'),
            'get_version': ((0x02,), '07 04 84 01 02'),
            'save_config_page': ((), '07 03 08 03'),               # capture 02
            'set_vibrate_param': ((0x32, 0x4B, 0, 0, 0, 0),
                                  '07 09 06 01 32 4b 00 00 00 00'),  # capture 02
        }
        for name, (payload, wire) in cases.items():
            self.assertEqual(sn.encode_request(*sn.COMMANDS[name], bytes(payload)),
                             h(wire), name)

    def test_vibrate_test_matches_the_bytes_gamesirs_javascript_writes(self):
        self.assertEqual(sn.encode_request(*sn.COMMANDS['set_vibrate_test'],
                                           bytes((0x40, 0x80, 0, 0))),
                         bytes((7, 7, 0x0A, 0x04, 0x40, 0x80, 0, 0)))

    def test_a_get_reply_is_all_data(self):
        reply = h('06 09 06 02 4b 4b 00 00 4b 4b') + bytes(54)        # capture 01
        self.assertEqual(sn.decode_reply(reply), (0x06, 0x02, h('4b 4b 00 00 4b 4b')))

    def test_a_set_reply_is_one_status_byte(self):
        g, op, body = sn.decode_reply(h('06 04 08 03 00') + bytes(59))  # capture 02
        self.assertEqual((g, op), sn.COMMANDS['save_config_page'])
        self.assertTrue(sn.set_succeeded(body))
        self.assertFalse(sn.set_succeeded(b'\x03'))

    def test_device_info_names_the_pad_behind_the_shared_dongle(self):
        _, _, body = sn.decode_reply(h('06 0e 0a 01 03 01 06 11 22 33 44 55 66 64 00'))
        self.assertEqual(sn.device_type_from_info(body), sn.DEVICE_TYPE_ID)

    def test_device_info_carries_the_battery(self):
        # Real replies from the dongle, 2026-10-10: full, after ~3 h of play,
        # and on a charger.
        info = lambda b: sn.decode_reply(h('06 0e 0a 01 03 01 06 11 22 33 44 55 66 %s 00' % b))[2]
        self.assertEqual(sn.battery_from_info(info('64')), (100, False))
        self.assertEqual(sn.battery_from_info(info('5e')), (94, False))
        self.assertEqual(sn.battery_from_info(info('ff')), (None, True))
        self.assertEqual(sn.battery_from_info(info('65')), (None, False))   # > 100
        self.assertEqual(sn.battery_from_info(h('03 01 06')), (None, False))

    def test_the_two_notifications_the_app_listens_for_decode(self):
        g, op, _ = sn.decode_reply(bytes((6, 5, 0x0A, 0x0D, 0x10, 0)))
        self.assertEqual((g, op), sn.NOTIFY_PROFILE_CHANGED)
        g, op, _ = sn.decode_reply(bytes((6, 0x1A, 0x0A, 0x03)) + bytes(0x17))
        self.assertEqual((g, op), sn.NOTIFY_GAMEPAD_STATE)

    def test_other_reports_are_not_mistaken_for_replies(self):
        self.assertIsNone(sn.decode_reply(h('07 03 0a 01')))
        self.assertIsNone(sn.decode_reply(bytes(64)))    # the idle all-zero report
        self.assertIsNone(sn.decode_reply(b'\x06\x03'))


class LayoutTests(unittest.TestCase):
    STICK_READ = h('00 00 00 00 00 00 00 01 32 05 00 14 10 35 32 55 54 64 64 00 32')
    TRIG_READ = h('01 00 0a 14 05 00 13 10 32 32 51 54 5f 64 00 32')

    def test_lengths_match_the_capture(self):
        self.assertEqual(len(self.STICK_READ), sn.STICK_LEN)
        self.assertEqual(len(self.TRIG_READ), sn.TRIG_LEN)

    def test_default_blocks_decode_to_the_apps_defaults(self):
        s, t = sn.STICK_POINTS, sn.TRIG_POINTS
        self.assertEqual((self.STICK_READ[s + sn.P_DZ_BEGIN],
                          self.STICK_READ[s + sn.P_DZ_END]), (5, 100))
        self.assertEqual((self.TRIG_READ[t + sn.P_DZ_BEGIN],
                          self.TRIG_READ[t + sn.P_DZ_END]), (5, 95))

    def test_stick_deadzone_writes_reproduce_capture_04(self):
        for dz, wire in ((3, '00 00 00 00 00 00 00 01 32 03 00 12 10 34 32 55 54 64 64 00 32'),
                         (10, '00 00 00 00 00 00 00 01 32 0a 00 18 10 37 32 56 54 64 64 00 32')):
            self.assertEqual(sn.with_begin_deadzone(self.STICK_READ, sn.STICK_POINTS, dz),
                             h(wire), dz)

    def test_trigger_deadzone_writes_reproduce_capture_05(self):
        for dz, wire in ((4, '01 00 0a 14 04 00 12 10 32 32 51 54 5f 64 00 32'),
                         (7, '01 00 0a 14 07 00 15 10 33 32 51 54 5f 64 00 32'),
                         (10, '01 00 0a 14 0a 00 17 10 35 32 52 54 5f 64 00 32')):
            self.assertEqual(sn.with_begin_deadzone(self.TRIG_READ, sn.TRIG_POINTS, dz),
                             h(wire), dz)

    def _with_x(self, block, at, xs, dz=None):
        out = bytearray(block)
        for ix, x in zip(sn.P_CURVE_X, xs):
            out[at + ix] = x
        if dz is not None:
            out[at + sn.P_DZ_BEGIN] = dz
        return bytes(out)

    def test_the_factory_curve_is_recognised_even_drifted(self):
        self.assertTrue(sn.has_factory_shape(self.STICK_READ, sn.STICK_POINTS))
        self.assertTrue(sn.has_factory_shape(self.TRIG_READ, sn.TRIG_POINTS))
        # Linux, 2026-10-10: left stick back at 5 after several applies.
        drifted = self._with_x(self.STICK_READ, sn.STICK_POINTS, (18, 53, 87))
        self.assertTrue(sn.has_factory_shape(drifted, sn.STICK_POINTS))
        # ...and the factory curve rescaled to another deadzone still is.
        at30 = sn.with_begin_deadzone(self.STICK_READ, sn.STICK_POINTS, 30)
        self.assertTrue(sn.has_factory_shape(at30, sn.STICK_POINTS))

    def test_a_shaped_curve_is_not_mistaken_for_the_factory_one(self):
        shaped_y = bytearray(self.STICK_READ)
        shaped_y[sn.STICK_POINTS + 5] = 30                  # y1 50 -> 30
        self.assertFalse(sn.has_factory_shape(bytes(shaped_y), sn.STICK_POINTS))
        shaped_x = self._with_x(self.STICK_READ, sn.STICK_POINTS, (40, 53, 85))
        self.assertFalse(sn.has_factory_shape(shaped_x, sn.STICK_POINTS))

    def test_deadzone_round_trips_return_the_factory_curve_exactly(self):
        for block, at in ((self.STICK_READ, sn.STICK_POINTS),
                          (self.TRIG_READ, sn.TRIG_POINTS)):
            cur = block
            for dz in (30, 10, 49, 3, 17, 5):
                cur = sn.with_begin_deadzone(cur, at, dz)
            self.assertEqual(cur, block, at)

    def test_a_drifted_curve_is_repaired_on_its_next_change(self):
        drifted = self._with_x(self.STICK_READ, sn.STICK_POINTS, (18, 53, 87))
        self.assertEqual(sn.with_begin_deadzone(drifted, sn.STICK_POINTS, 10),
                         h('00 00 00 00 00 00 00 01 32 0a 00 18 10 37 32 56 54 64 64 00 32'))
        at30 = self._with_x(drifted, sn.STICK_POINTS, (40, 66, 90), dz=30)
        self.assertEqual(sn.with_begin_deadzone(at30, sn.STICK_POINTS, 5), self.STICK_READ)

    def test_a_shaped_curve_still_rescales_from_what_the_pad_holds(self):
        shaped = bytearray(self.STICK_READ)
        shaped[sn.STICK_POINTS + 5] = 30                    # not the factory curve
        out = sn.with_begin_deadzone(bytes(shaped), sn.STICK_POINTS, 10)
        expect = [sn._round_half_up(10 + (x - 5) * 90 / 95) for x in (0x14, 0x35, 0x55)]
        self.assertEqual([out[sn.STICK_POINTS + i] for i in sn.P_CURVE_X], expect)

    def test_default_restores_the_factory_turbo_byte(self):
        remapped = h('00 00 00 00 00 00 01 00 00 01 01 01 00 00 00 00')  # A -> B
        self.assertEqual(sn.with_key_target(remapped, sn.KEYS['CRO']),
                         h('00 00 00 00 00 00 01 00 00 00 01 01 01 00 00 00'))  # capture 01
        # Turbo on: its count is the user's, kept.
        turbo = bytearray(remapped)
        turbo[sn.KEY_TURBO_MODE], turbo[sn.KEY_TURBO_TIMES] = 1, 12
        self.assertEqual(sn.with_key_target(bytes(turbo), sn.KEYS['CRO'])[sn.KEY_TURBO_TIMES], 12)

    def test_a_deadzone_at_or_past_the_end_is_refused(self):
        with self.assertRaises(ValueError):
            sn.with_begin_deadzone(self.TRIG_READ, sn.TRIG_POINTS, 95)

    def test_remap_a_to_b_reproduces_capture_03(self):
        read_a = h('00 00 00 00 00 00 01 00 00 00 01 01 01 00 00 00')   # capture 01, key 0x01
        self.assertEqual(sn.with_key_target(read_a, sn.KEYS['CIR']),
                         h('00 00 00 00 00 00 01 00 00 01 01 01 00 00 00 00'))
        self.assertEqual(read_a[sn.KEY_SOURCE], sn.KEYS['CRO'])

    def test_every_button_code_is_distinct(self):
        self.assertEqual(len(set(sn.KEYS.values())), len(sn.KEYS))
        self.assertIn('CRO', sn.KEYS)
        self.assertIn('SQU', sn.KEYS)


class SafetyTests(unittest.TestCase):
    def test_dangerous_commands_cannot_be_encoded(self):
        for name in sn.FORBIDDEN:
            with self.assertRaises(ValueError, msg=name):
                sn.encode_request(*sn.COMMANDS[name])

    def test_the_whole_firmware_update_group_is_refused(self):
        for op in range(0x100):
            with self.assertRaises(ValueError):
                sn.encode_request(sn.UPDATE_GROUP, op)

    def test_reads_are_never_forbidden_and_never_writes(self):
        self.assertFalse(sn.READ_ONLY & sn.FORBIDDEN)
        self.assertTrue(all(n.startswith('get_') for n in sn.READ_ONLY))

    def test_every_command_code_is_unique(self):
        codes = list(sn.COMMANDS.values())
        self.assertEqual(len(codes), len(set(codes)))

    def test_only_the_verified_dongle_is_configurable(self):
        self.assertEqual(sn.CONFIG_PIDS, (sn.PID_DONGLE,))
        self.assertNotIn(sn.PID_WIRED, sn.CONFIG_PIDS)
        self.assertIn(sn.PID_DONGLE, sn.SHARED_PIDS)    # hence the device-type check


if __name__ == '__main__':
    unittest.main()
