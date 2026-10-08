import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vendors.gamesir.models.g7se.startup import Startup
from vendors.gamesir.models.g7se import gip


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name, value in {'idVendor': '3537', 'idProduct': '1010',
                            'bcdDevice': '0630', 'busnum': '1', 'devnum': '6',
                            'serial': 'tested-device'}.items():
            (self.root/name).write_text(value)
        self.handle = Mock()
        self.handle.write.side_effect = len
        self.startup = Startup(self.handle, 1, 6, self.root)

    def test_wrong_device_or_firmware_is_rejected_before_transfers(self):
        for name, value in (('idProduct', '10a7'), ('bcdDevice', '0640'), ('devnum', '7')):
            old = (self.root/name).read_text()
            (self.root/name).write_text(value)
            with self.assertRaises(OSError):
                Startup(self.handle, 1, 6, self.root)
            (self.root/name).write_text(old)
        self.handle.write.assert_not_called()

    def test_selection_disconnect_session_and_time_budget_stop_startup(self):
        self.startup.active = lambda: False
        with self.assertRaisesRegex(OSError, 'selection'):
            self.startup.check()
        self.startup.active = lambda: True
        self.startup.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(OSError, 'time budget'):
            self.startup.check()
        self.startup.deadline = time.monotonic() + 10
        (self.root/'serial').write_text('replacement')
        with self.assertRaisesRegex(OSError, 'session changed'):
            self.startup.check()
        (self.root/'devnum').unlink()
        with self.assertRaises(OSError):
            self.startup.check()
        self.handle.write.assert_not_called()

    def test_warm_reads_are_sequence_matched_and_skip_authentication(self):
        def read(*args, **kwargs):
            wire = self.handle.write.call_args.args[0]
            return bytes((16, 0, wire[2], 60, 5, 1, 0, 0, 55)) + bytes(55)
        self.handle.read.side_effect = read
        result = self.startup.run()
        self.assertTrue(result['already_ready'])
        self.assertEqual(len(self.handle.write.call_args_list), 2)
        self.assertTrue(all(c.args[0][4] == 4 for c in self.handle.write.call_args_list))

    def test_cold_start_requires_identity_authentication_and_verified_reads(self):
        with patch.object(self.startup, 'read_probe', side_effect=[False, True]), \
                patch.object(self.startup, 'receive', return_value=bytes(244)), \
                patch('vendors.gamesir.models.g7se.auth.Exchange.run',
                      return_value={'fresh_transcript_verified': True}) as authenticate:
            self.assertTrue(self.startup.run()['fresh_transcript_verified'])
            authenticate.assert_called_once()
        self.assertEqual(self.handle.write.call_args_list[0].args[0], gip.identify(1))
        self.assertFalse(any(c.args[0][0] == 15 for c in self.handle.write.call_args_list))

    def test_failed_authentication_or_missing_reads_never_report_ready(self):
        with patch.object(self.startup, 'read_probe', return_value=False), \
                patch.object(self.startup, 'receive', return_value=bytes(244)), \
                patch('vendors.gamesir.models.g7se.auth.Exchange.run', side_effect=OSError('timeout')):
            with self.assertRaisesRegex(OSError, 'timeout'):
                self.startup.run()
        with patch.object(self.startup, 'read_probe', return_value=False), \
                patch.object(self.startup, 'receive', return_value=bytes(244)), \
                patch('vendors.gamesir.models.g7se.auth.Exchange.run', return_value={}):
            with self.assertRaisesRegex(OSError, 'profile replies unavailable'):
                self.startup.run()

    def test_release_restores_input_but_never_touches_replacement(self):
        self.startup.active = lambda: False
        self.startup.restore_input()
        self.assertEqual(self.handle.write.call_args.args[0], bytes.fromhex('0520010100'))
        self.handle.write.reset_mock()
        (self.root/'devnum').write_text('7')
        with self.assertRaises(OSError):
            self.startup.restore_input()
        self.handle.write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
