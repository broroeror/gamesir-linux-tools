"""The doctor's udev rule status compares rules, not bytes (#74)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import doctor  # noqa: E402

SHIPPED = (
    '# comment\n'
    'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3537", TAG+="uaccess"\n'
    '\n'
    'SUBSYSTEM=="usb", ATTR{idVendor}=="3537", ATTR{idProduct}=="106a", TAG+="uaccess"\n'
    'SUBSYSTEM=="usb", ATTR{idVendor}=="3537", ATTR{product}=="GameSir-G7 Pro", TAG+="uaccess"\n'
)


class RuleStatus(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.source = self._file('shipped.rules', SHIPPED)

    def tearDown(self):
        self.dir.cleanup()

    def _file(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, 'w', newline='') as f:
            f.write(text)
        return path

    def _status(self, installed_text):
        installed = self._file('installed.rules', installed_text)
        diff = doctor._compare_rules(installed, self.source)
        rule = {'installed': True, 'packaged': False,
                'current': not diff['missing'], **diff}
        return rule, doctor._rule_status(rule)

    def test_identical_matches(self):
        rule, status = self._status(SHIPPED)
        self.assertTrue(rule['current'])
        self.assertEqual(status, 'installed, matches this version')

    def test_comments_spacing_and_line_endings_still_match(self):
        text = ('# a different comment\n'
                + SHIPPED.replace('\n', '\r\n').replace(', TAG', ',   TAG')
                         .rstrip('\r\n'))   # and no final newline
        rule, status = self._status(text)
        self.assertTrue(rule['current'])
        self.assertEqual(status, 'installed, matches this version')

    def test_missing_rules_are_named(self):
        text = '\n'.join(l for l in SHIPPED.splitlines() if '106a' not in l
                         and 'product}' not in l)
        rule, status = self._status(text)
        self.assertFalse(rule['current'])
        self.assertEqual(status, 'installed, missing 2 rules from this version '
                                 '(3537:106a, "GameSir-G7 Pro")')

    def test_local_extra_rule_is_not_stale(self):
        text = SHIPPED + 'SUBSYSTEM=="usb", ATTR{idVendor}=="3537", ATTR{idProduct}=="beef", TAG+="uaccess"\n'
        rule, status = self._status(text)
        self.assertTrue(rule['current'])
        self.assertEqual(status, 'installed, matches this version; has 1 rule '
                                 "this version doesn't (3537:beef)")

    def test_long_lists_are_shortened(self):
        self.source = self._file('shipped.rules', SHIPPED + ''.join(
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="3537", ATTR{{idProduct}}=="{p:04x}", TAG+="uaccess"\n'
            for p in range(0x1000, 0x1004)))
        _rule, status = self._status(SHIPPED)
        self.assertEqual(status, 'installed, missing 4 rules from this version '
                                 '(3537:1000, 3537:1001, 3537:1002, +1 more)')

    def test_nothing_to_compare_claims_only_installed(self):
        rule = {'installed': True, 'packaged': True, 'current': None,
                'missing': [], 'extra': []}
        self.assertEqual(doctor._rule_status(rule), 'installed (packaged)')

    def test_not_installed(self):
        self.assertEqual(doctor._rule_status({'installed': False}), 'NOT INSTALLED')


if __name__ == '__main__':
    unittest.main()
