"""Doctor's report on GameSir USB identities it can't open over HID (#41)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doctor

GIP = [{'name': '1-2:1.0', 'cls': 'ff', 'sub': '47', 'proto': 'd0', 'driver': 'xpad'},
       {'name': '1-2:1.1', 'cls': 'ff', 'sub': '47', 'proto': 'd0', 'driver': '-'}]


def usb(pid, port='1-2'):
    return {'id': port, 'port': port, 'pid': pid, 'nodes': [], 'bcd': 0x0664,
            'product': 'GameSir-G7 SE Controller for Xbox',
            'usb': {'bus': 1, 'address': 3, 'sysfs': '/nonexistent'}}


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux report path')
class DoctorIdentityTests(unittest.TestCase):
    def report(self, *devs):
        with patch('doctor._sysfs_nodes', return_value=[]), \
             patch('doctor._usb_links', return_value=[]), \
             patch('doctor._platform_mode_devices', return_value=[]), \
             patch('doctor._interfaces', return_value=GIP), \
             patch('gs_common.find_controllers', return_value=list(devs)), \
             patch('gs_common.parse_devices', return_value=[]):
            rep = doctor.collect()
        return rep, doctor.format_report(rep)

    def test_g7se_108f_is_named_and_not_called_missing(self):
        rep, text = self.report(usb(0x108f))
        self.assertIn('G7 SE 6.64 Xbox mode', text)
        self.assertIn('class ff/47/d0', text)
        self.assertNotIn('No GameSir device is enumerated', text)
        self.assertTrue(any('3537:108f' in v for v in rep['verdict']))

    def test_unrecognised_identity_is_listed_with_interfaces(self):
        rep, text = self.report(usb(0x7777))
        self.assertIn('GameSir 7777 (not recognised)', text)
        self.assertIn('class ff/47/d0', text)
        self.assertNotIn('No GameSir device is enumerated', text)

    def test_hid_identities_are_left_to_the_hid_section(self):
        dev = usb(0x7777)
        dev['nodes'] = ['/dev/hidraw9']
        rep, _ = self.report(dev)
        self.assertEqual(rep['usb_devices'], [])


if __name__ == '__main__':
    unittest.main()
