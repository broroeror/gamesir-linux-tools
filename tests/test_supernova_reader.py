"""reader.read_session_supernova surviving a dongle that disappears mid-check.
No USB access required: the transport is patched."""
import errno
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reader
from vendors.gamesir.models.supernova import transport as sn_transport


class GoneLink:
    """A link whose first write fails the way hidraw does on an unplug."""
    def __init__(self, node):
        self.closed = False

    def request(self, name, payload=b''):
        raise OSError(errno.EPROTO, 'Protocol error')

    def close(self):
        self.closed = True


class ReaderUnplugTests(unittest.TestCase):
    def test_an_unplug_during_the_check_returns_instead_of_raising(self):
        # 2026-10-10 (AppImage H3): EPROTO escaped here and killed the reader
        # thread, so the live view stayed frozen after the dongle came back.
        links = []

        def make_link(node):
            links.append(GoneLink(node))
            return links[-1]

        with mock.patch.object(sn_transport, 'config_node', return_value='/dev/hidraw99'), \
             mock.patch.object(sn_transport, 'SuperNovaLink', side_effect=make_link), \
             mock.patch.object(reader, 'read_session_evdev') as evdev:
            reader.read_session_supernova({'id': 'pad', 'nodes': []})
        self.assertTrue(links and links[0].closed)
        evdev.assert_not_called()          # back to read_controller, which re-detects
        self.assertFalse(reader.state['mode_ok'])


class InfoLink:
    """A Super Nova that answers get_device_info with a given battery byte."""
    def __init__(self, battery):
        self.body = bytes.fromhex('03 01 06 11 22 33 44 55 66') + bytes((battery, 0))
        self.closed = False

    def request(self, name, payload=b''):
        assert name == 'get_device_info', name
        return self.body

    def close(self):
        self.closed = True


class ReaderBatteryTests(unittest.TestCase):
    def session(self, battery):
        link = InfoLink(battery)
        with mock.patch.object(sn_transport, 'config_node', return_value='/dev/hidraw99'), \
             mock.patch.object(sn_transport, 'SuperNovaLink', return_value=link), \
             mock.patch.object(reader, 'read_session_evdev') as evdev:
            reader.read_session_supernova({'id': 'pad', 'nodes': []})
        evdev.assert_called_once()         # the session ran its live view
        self.assertTrue(link.closed)
        return reader.state['battery'], reader.state['charging']

    def tearDown(self):
        reader.state.update(battery=-1, charging=False, driving=None)

    def test_the_session_check_publishes_the_battery(self):
        self.assertEqual(self.session(42), (42, False))

    def test_on_a_charger_it_is_charging_with_no_percentage(self):
        self.assertEqual(self.session(0xFF), (-1, True))

    def test_an_unknown_value_is_no_reading(self):
        self.assertEqual(self.session(0xC8), (-1, False))


if __name__ == '__main__':
    unittest.main()
