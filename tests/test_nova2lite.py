"""Nova 2 Lite (T4N2) detection, protocol framing, input decoding, and register translation."""
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_profile as profiles
import reader
import vendors.gamesir.config as _cy
from gs_state import state
from vendors.gamesir import control
from vendors.gamesir.models.nova2lite import protocol as n2l


class DummyDevice:
    def __init__(self):
        self.packets = []

    def write(self, packet):
        self.packets.append(bytes(packet))
        return len(packet)


class Nova2LiteTests(unittest.TestCase):
    def setUp(self):
        self.old_state = dict(state)
        n2l.reset_session_state()

    def tearDown(self):
        control.clear_device()
        profiles.set_active(None)
        n2l.reset_session_state()
        state.clear()
        state.update(self.old_state)

    def test_detection_and_connection_kind(self):
        self.assertIs(profiles.detect_one(0x100F, 'GameSir-Nova 2 Lite'), profiles.NOVA_2_LITE)
        self.assertIs(profiles.detect_one(0x1098, 'GameSir-Nova 2 Lite Dongle'), profiles.NOVA_2_LITE)
        self.assertTrue(n2l.connection_kind(0x100F))
        self.assertFalse(n2l.connection_kind(0x1098))
        self.assertIsNone(n2l.connection_kind(0x9999))
        self.assertTrue(reader._is_wired(profiles.NOVA_2_LITE, 0x100F, None))
        self.assertFalse(reader._is_wired(profiles.NOVA_2_LITE, 0x1098, None))

    def test_wired_nova2lite_probe_live_skips_hid_open(self):
        ctrl = {'id': 'n2l-wired', 'port': '1-2', 'pid': 0x100F,
                'product': 'GameSir-Nova 2 Lite', 'nodes': ['/dev/hidraw99']}
        with patch.object(n2l, 'streams_live_data') as stream_probe:
            self.assertTrue(reader._probe_live(ctrl, profiles.NOVA_2_LITE))
            stream_probe.assert_not_called()

    def test_packet_framing_and_checksum(self):
        pkt = n2l.frame_packet([0x23, 0x04, 0x06, 0x00, 0x00], 6)
        self.assertEqual(len(pkt), 65)
        self.assertEqual(pkt[0], 0x00)
        # Payload bytes 0..4 reside at pkt[1..5]; checksum is at pkt[6]
        self.assertEqual(list(pkt[1:7]), [0x23, 0x04, 0x06, 0x00, 0x00, 0x2D])
        self.assertEqual(pkt[7:], bytes(58))

    def test_parse_device_info(self):
        report = [0x01, 0x01] + [0x00] * 62
        report[10] = 0x82
        report[11] = 0x01
        report[16] = 0x23   # low nibble 3 -> 75%
        report[17] = 0x02   # charging
        info = n2l.parse_device_info(report)
        self.assertEqual(info, {'firmware': '1.82', 'battery': 75, 'charging': True})
        # Empty/unpaired dongle response (data[1] == 0) is ignored
        self.assertEqual(n2l.parse_device_info([0x01, 0x00] + [0x00] * 62), {})

    def test_parse_input_report(self):
        report = bytearray(64)
        report[0] = 0xF4
        report[1] = 0x01
        report[2] = 0x17
        report[4] = 0x01 | 0x40     # A + LB
        report[5] = 0x08 | 0x80     # Menu + Share/Capture
        report[6] = 0x01 | 0x08 | 0x80  # Dpad Up+Right + L4
        report[7] = 0x01 | 0x40     # R4 + M
        struct.pack_into('<4h', report, 8, 0, 32767, -32768, -32768)
        report[16] = 120            # LT
        report[17] = 0              # RT
        report[20] = 0x82
        report[21] = 0x01
        parsed = n2l.parse_input(report)
        self.assertEqual(parsed['lx'], 128)
        self.assertEqual(parsed['ly'], 0)     # inverted: +32767 (up) -> 0
        self.assertEqual(parsed['rx'], 0)
        self.assertEqual(parsed['ry'], 255)   # inverted: -32768 (down) -> 255
        self.assertEqual(parsed['lt'], 120)
        self.assertTrue(parsed['lt_d'])
        self.assertEqual(parsed['rt'], 0)
        self.assertFalse(parsed['rt_d'])
        self.assertEqual(parsed['dpad'], 'up-right')
        self.assertTrue(parsed['a'])
        self.assertFalse(parsed['b'])
        self.assertTrue(parsed['lb'])
        self.assertTrue(parsed['menu'])
        self.assertTrue(parsed['share'])
        self.assertTrue(parsed['l4'])
        self.assertTrue(parsed['r4'])
        self.assertTrue(parsed['m'])
        self.assertEqual(parsed['firmware'], '1.82')

    def test_vibration_read_and_write_translation(self):
        # Write ACK (data[3] == 0x01) must be ignored by match_read_reply
        ack = [0x25, 0x01, 0x0D, 0x01, 50, 3, 0, 0, 75, 3, 0, 0, 0] + [0] * 51
        self.assertIsNone(n2l.match_read_reply(ack, 1, n2l.VIB_L, 1))
        # Read reply (data[3] == 0x00)
        reply = [0x25, 0x01, 0x0D, 0x00, 50, 3, 0, 0, 100, 3, 0, 0, 0] + [0] * 51
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.VIB_L, 1), [50])
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.VIB_R, 1), [100])
        pkts = n2l.write_packets(1, n2l.VIB_L, [25])
        self.assertEqual(len(pkts), 1)
        self.assertEqual(list(pkts[0][1:10]), [0x25, 0x01, 0x0D, 0x01, 25, 0x03, 0x00, 0x00, 100])

    def test_button_remap_read_and_write_translation(self):
        l4_addr = dict(_cy.REMAP_SLOTS)['L4']
        a_code = dict(n2l.GAMEPAD_TARGETS)['A']
        # Unmapped L4 -> [0x00, 0x00]
        reply_self = [0xF1, 0x00, 0x09, 0xCB, 0x01, 0xCB, 0x00, 0x00, 0x00] + [0] * 55
        self.assertEqual(n2l.match_read_reply(reply_self, 1, l4_addr, 2), [0x00, 0x00])
        # L4 mapped to A (0xB4 -> target code 0x09)
        reply_a = [0xF1, 0x00, 0x09, 0xCB, 0x01, 0xB4, 0x00, 0x00, 0x00] + [0] * 55
        self.assertEqual(n2l.match_read_reply(reply_a, 1, l4_addr, 2), [0x01, a_code])
        # L4 disabled (0xD2 -> [0x01, 0xFF])
        reply_dis = [0xF1, 0x00, 0x09, 0xCB, 0x01, 0xD2, 0x00, 0x00, 0x00] + [0] * 55
        self.assertEqual(n2l.match_read_reply(reply_dis, 1, l4_addr, 2), [0x01, 0xFF])
        # Write ACK (data[1] == 0x01) is ignored
        ack = [0xF1, 0x01, 0x09, 0xCB, 0x01, 0xB4, 0x00, 0x00, 0x00] + [0] * 55
        self.assertIsNone(n2l.match_read_reply(ack, 1, l4_addr, 2))

        # Write L4 -> A ([0x01, a_code])
        pkt_a = n2l.write_packets(1, l4_addr, [0x01, a_code])[0]
        self.assertEqual(list(pkt_a[1:9]), [0xF1, 0x01, 0x09, 0xCB, 0x01, 0xB4, 0x00, 0x00])
        # Write L4 -> Disabled ([0x01, 0xFF])
        pkt_dis = n2l.write_packets(1, l4_addr, [0x01, 0xFF])[0]
        self.assertEqual(list(pkt_dis[1:9]), [0xF1, 0x01, 0x09, 0xCB, 0x01, 0xD2, 0x00, 0x00])
        # Write L4 -> Default ([0x00, 0x00])
        pkt_def = n2l.write_packets(1, l4_addr, [0x00, 0x00])[0]
        self.assertEqual(list(pkt_def[1:9]), [0xF1, 0x02, 0x09, 0xCB, 0x00, 0x00, 0x00, 0x00])

    def test_stick_and_trigger_register_translation(self):
        # Left stick read reply: inner=8, ADZ_min=2, curve=[25,25,50,50,75,75], outer=95, ADZ_max=98, type=0, inten=100
        raw12 = [8, 2, 25, 25, 50, 50, 75, 75, 95, 98, 0, 100]
        reply = [0xF0, 0x00, 0x11, 0x01, *raw12, 0x00] + [0] * 47
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.ST_DZ_MIN, 1), [8])
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.ST_DZ_MAX, 1), [95])
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.ST_ADZ_MIN, 1), [2])
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.ST_ADZ_MAX, 1), [98])
        self.assertEqual(n2l.match_read_reply(reply, 1, n2l.ST_CURVE, 10),
                         list(_cy.CURVE_BLOCKS[0][1]))

        # Hair trigger read/write
        hair_reply = [0x21, 0x00, 0x01, 0x02, 0x24] + [0] * 59
        self.assertEqual(n2l.match_read_reply(hair_reply, 1, n2l.LT_HAIR, 3)[0], 0x81)
        self.assertEqual(n2l.match_read_reply(hair_reply, 1, n2l.RT_HAIR, 3)[0], 0x00)

    def test_control_rumble_and_write_reg_for_nova2lite(self):
        dev = DummyDevice()
        profiles.set_active(profiles.NOVA_2_LITE)
        control.set_device(dev)
        with patch.object(control.time, 'sleep'):
            control.rumble_test(motor='left', strength=180).join(1)
        self.assertEqual(len(dev.packets), 2)
        pulse, stop = dev.packets
        self.assertEqual(len(pulse), 65)
        self.assertEqual(list(pulse[1:6]), [0x04, 180, 0x08, 0, 0x08])
        self.assertEqual(list(stop[1:6]), [0x04, 0, 0x08, 0, 0x08])


if __name__ == '__main__':
    unittest.main()
