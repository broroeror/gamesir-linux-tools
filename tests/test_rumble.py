"""Rumble transport and reconnect regressions; no hardware required."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_profile as profiles
from vendors.gamesir import control


class Device:
    def __init__(self):
        self.packets = []

    def write(self, packet):
        self.packets.append(bytes(packet))
        return len(packet)


class RumbleTests(unittest.TestCase):
    def setUp(self):
        self.device = Device()
        profiles.set_active(profiles.G7_PRO)
        control.set_device(self.device)

    def tearDown(self):
        control.clear_device()
        profiles.set_active(None)

    def test_g7_test_uses_bounded_gip_pulse_and_explicit_cancel(self):
        outcome = []
        with patch.object(control.time, 'sleep'):
            thread = control.rumble_test(lambda *result: outcome.append(result))
            thread.join(1)
        self.assertFalse(thread.is_alive())
        pulse, stop = self.device.packets
        self.assertEqual(len(pulse), 13)
        self.assertEqual(pulse[:2], bytes((0x09, 0)))
        self.assertNotEqual(pulse[2], 0)
        self.assertEqual(pulse[3:], bytes((9, 0, 15, 0, 0, 75, 75, 40, 0, 0)))
        self.assertEqual(stop[3:], bytes((9, 0, 15, 0, 0, 0, 0, 0, 0, 0)))
        self.assertEqual(outcome, [(True, '')])

    def test_cyclone_still_uses_its_vendor_command(self):
        for profile in (profiles.CYCLONE, profiles.G7_8K):
            with self.subTest(model=profile.name):
                profiles.set_active(profile)
                self.device.packets.clear()
                with patch.object(control.time, 'sleep'):
                    control.rumble_test().join(1)
                pulse, stop = self.device.packets
                self.assertEqual(len(pulse), 64)
                self.assertEqual(pulse[:6], bytes((15, 32, 102, 85, 192, 192)))
                self.assertEqual(stop[:6], bytes((15, 32, 102, 85, 0, 0)))

    def test_individual_g7_motors_leave_other_channels_silent_and_expire(self):
        for motor, index in (('left_trigger', 0), ('right_trigger', 1),
                             ('left', 2), ('right', 3)):
            with self.subTest(motor=motor):
                self.device.packets.clear()
                outcome = []
                with patch.object(control.time, 'sleep'), \
                     patch.object(control, 'write_reg') as writes:
                    thread = control.rumble_test(lambda *r: outcome.append(r),
                                                 motor=motor, strength=153)
                    thread.join(1)
                    writes.assert_not_called()
                self.assertFalse(thread.is_alive())
                pulse, stop = self.device.packets
                expected = [0, 0, 0, 0]
                expected[index] = 60
                self.assertEqual(len(pulse), 13)
                self.assertEqual(pulse[5], 15)
                self.assertEqual(list(pulse[6:10]), expected)
                self.assertEqual(pulse[10:13], bytes((40, 0, 0)))
                self.assertEqual(stop[6:13], bytes(7))
                self.assertEqual(outcome, [(True, '')])

    def test_individual_legacy_grip_tests_and_unsupported_triggers(self):
        profiles.set_active(profiles.CYCLONE)
        for motor, expected in (('left', (153, 0)), ('right', (0, 153))):
            self.device.packets.clear()
            with patch.object(control.time, 'sleep'):
                control.rumble_test(motor=motor, strength=153).join(1)
            self.assertEqual(self.device.packets[0][:6], bytes((15, 32, 102, 85, *expected)))
            self.assertEqual(self.device.packets[1][:6], bytes((15, 32, 102, 85, 0, 0)))
        for motor in ('left_trigger', 'right_trigger', 'unknown'):
            self.device.packets.clear()
            outcome = []
            control.rumble_test(lambda *r: outcome.append(r), motor=motor).join(1)
            self.assertEqual(self.device.packets, [])
            self.assertFalse(outcome[0][0])

    def test_trigger_test_reconnect_never_stops_another_controller(self):
        other = Device()
        outcome = []
        with patch.object(control.time, 'sleep', side_effect=lambda _: control.set_device(other)):
            control.rumble_test(lambda *r: outcome.append(r), motor='left_trigger').join(1)
        self.assertEqual(len(self.device.packets), 1)
        self.assertEqual(self.device.packets[0][6:10], bytes((75, 0, 0, 0)))
        self.assertEqual(self.device.packets[0][10:13], bytes((40, 0, 0)))
        self.assertEqual(other.packets, [])
        self.assertFalse(outcome[0][0])

    def test_controller_switch_cannot_send_stop_to_new_controller(self):
        other = Device()
        outcome = []
        with patch.object(control.time, 'sleep', side_effect=lambda _: control.set_device(other)):
            control.rumble_test(lambda *result: outcome.append(result)).join(1)
        self.assertEqual(len(self.device.packets), 1)
        self.assertEqual(other.packets, [])
        self.assertFalse(outcome[0][0])
        # The old controller's pulse expires without needing a stop packet.
        self.assertEqual(self.device.packets[0][10:13], bytes((40, 0, 0)))

    def test_unknown_device_is_refused_and_failure_is_reported(self):
        profiles.set_active(None)
        outcome = []
        control.rumble_test(lambda *result: outcome.append(result)).join(1)
        self.assertEqual(self.device.packets, [])
        self.assertFalse(outcome[0][0])

    def test_gip_sequence_wrap_skips_reserved_zero(self):
        with patch.object(control, '_gip_seq', 255):
            self.assertTrue(control.rumble(255, 255))
        packet = self.device.packets[0]
        self.assertEqual(packet[2], 1)
        self.assertEqual(packet[8:10], bytes((100, 100)))

    def test_input_only_g7_identity_never_receives_vendor_rumble(self):
        profiles.set_active(profiles.G7_PRO_OTHER)
        self.assertFalse(control.rumble(192, 192))
        self.assertEqual(self.device.packets, [])


if __name__ == '__main__':
    unittest.main()
