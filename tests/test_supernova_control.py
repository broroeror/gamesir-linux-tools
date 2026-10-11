"""Super Nova plumbing in vendors/gamesir/control.py: the published link, the
session-generation guard, and the register paths refusing to frame anything
for it. No USB access required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_profile as profiles
import vendors.gamesir.control as control
from tests.test_supernova_config import FakePad
from vendors.gamesir.models.supernova import editor


class FakeHid:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


class SuperNovaControlTests(unittest.TestCase):
    def setUp(self):
        profiles.set_active(profiles.SUPER_NOVA)

    def tearDown(self):
        control.clear_supernova_link()
        control.clear_device()
        profiles.set_active(None)

    def test_no_link_refuses(self):
        with self.assertRaises(RuntimeError):
            control.supernova_request('get_device_info')

    def test_requests_reach_the_published_link(self):
        pad = FakePad()
        control.set_supernova_link(pad)
        config, _ = editor.read_config(control.SuperNovaSession())
        self.assertEqual(config['vib_l'], 75)
        self.assertEqual(pad.writes(), [])

    def test_a_rebind_refuses_the_old_sessions_work(self):
        control.set_supernova_link(FakePad())
        session = control.SuperNovaSession()
        control.set_supernova_link(FakePad())          # e.g. replugged / switched
        with self.assertRaises(RuntimeError):
            session.request('get_device_info')

    def test_an_unrecognised_controller_is_refused(self):
        control.set_supernova_link(FakePad())
        profiles.set_active(None)
        with self.assertRaises(RuntimeError):
            control.supernova_request('get_device_info')

    def test_register_paths_never_frame_for_it(self):
        dev = FakeHid()
        control.set_device(dev)
        self.assertFalse(control.write_reg(1, 0x20, [50], write_style='supernova'))
        self.assertFalse(control.write_reg(1, 0x20, [50]))        # active profile's style
        self.assertFalse(control.rumble(0x80, 0x80))
        control.request_regs([(1, 0x20, 1)])
        control.pump_reads()
        self.assertEqual(dev.writes, [])

    def test_input_only_profiles_never_frame_either(self):
        dev = FakeHid()
        control.set_device(dev)
        profiles.set_active(profiles.SUPER_NOVA_OTHER)
        self.assertFalse(control.write_reg(1, 0x20, [50]))
        self.assertEqual(dev.writes, [])


class SuperNovaVibrationTestTests(unittest.TestCase):
    """control.supernova_vibrate_test: the pad's own pulse, sent the way it was
    tried on hardware (2026-10-10): the slider's percent in its side's byte."""

    def setUp(self):
        profiles.set_active(profiles.SUPER_NOVA)
        self.pulse, control.SUPERNOVA_TEST_PULSE = control.SUPERNOVA_TEST_PULSE, 0
        self.pad = FakePad()
        control.set_supernova_link(self.pad)

    def tearDown(self):
        control.SUPERNOVA_TEST_PULSE = self.pulse
        control.clear_supernova_link()
        profiles.set_active(None)

    def run_test(self, side, percent):
        done = []
        control.supernova_vibrate_test(side, percent,
                                       on_done=lambda ok, msg: done.append((ok, msg))).join(5)
        return done

    def test_each_side_puts_its_percent_in_its_own_byte(self):
        self.assertEqual(self.run_test('left', 50), [(True, '')])
        self.assertEqual(self.run_test('right', 25), [(True, '')])
        self.assertEqual(self.pad.sent, [('set_vibrate_test', bytes((50, 0, 0, 0))),
                                         ('set_vibrate_test', bytes((0, 25, 0, 0)))])

    def test_it_never_writes_or_saves_settings(self):
        self.run_test('left', 100)
        self.assertEqual(self.pad.writes(), ['set_vibrate_test'])
        self.assertEqual(self.pad.saves, 0)

    def test_the_percent_is_clamped(self):
        self.run_test('left', 150)
        self.assertEqual(self.pad.sent[-1][1], bytes((100, 0, 0, 0)))

    def test_no_pad_reports_instead_of_raising(self):
        control.clear_supernova_link()
        [(ok, msg)] = self.run_test('left', 50)
        self.assertFalse(ok)
        self.assertIn('not connected', msg)


if __name__ == '__main__':
    unittest.main()
