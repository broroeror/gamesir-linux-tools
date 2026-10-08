import json
from pathlib import Path
import struct
import unittest
from vendors.gamesir.models.g7se.input import decode


def report(buttons=0, lt=0, rt=0, lx=0, ly=0, rx=0, ry=0):
    payload = struct.pack('<HHHhhhh', buttons, lt, rt, lx, ly, rx, ry) + bytes(18)
    return bytes((32, 0, 1, len(payload))) + payload


class InputTests(unittest.TestCase):
    def test_trigger_travel_and_independent_signed_axes(self):
        values = decode(report(lt=512, rt=1023, lx=-32768, ly=32767,
                               rx=32767, ry=-32768))
        self.assertEqual({k: values[k] for k in ('lt','rt','lx','ly','rx','ry')},
                         dict(lt=128, rt=255, lx=0, ly=0, rx=255, ry=255))
        values = decode(report(lt=1023, rt=0, lx=16384, ly=-16384, rx=-16384, ry=16384))
        self.assertEqual((values['lt'], values['rt']), (255, 0))
        self.assertGreater(values['lx'], 128)
        self.assertGreater(values['ly'], 128)
        self.assertLess(values['rx'], 128)
        self.assertLess(values['ry'], 128)

    def test_release_clears_buttons_triggers_and_dpad(self):
        pressed = decode(report(buttons=0xffff, lt=1023, rt=1023))
        self.assertTrue(all(pressed[k] for k in ('a','b','x','y','ls','rs','lb','rb')))
        released = decode(report())
        self.assertFalse(any(released[k] for k in ('a','b','x','y','ls','rs','lb','rb')))
        self.assertEqual((released['lt'], released['rt'], released['dpad']), (0,0,'neutral'))
        self.assertEqual((released['lx'],released['rx']), (128,128))

    def test_dpad_diagonals_and_y_orientation(self):
        self.assertEqual(decode(report(buttons=0x0900))['dpad'], 'up-right')
        self.assertEqual(decode(report(buttons=0x0600))['dpad'], 'down-left')
        self.assertLess(decode(report(ly=32767))['ly'], 128)

    def test_malformed_non_input_and_wrong_client_frames_are_ignored(self):
        wire = report()
        for value in (b'', wire[:17], wire[:-1], bytes((16,))+wire[1:],
                      wire[:1]+bytes((1,))+wire[2:], wire[:3]+bytes((14,))+wire[4:]):
            self.assertIsNone(decode(value))

    def test_captured_windows_inputs_match_linux_button_and_axis_layout(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/g7se-0630-input.json').read_text())
        for item in fixture['reports']:
            actual = decode(bytes.fromhex(item['wire']))
            self.assertIsNotNone(actual)
            for key, value in item['expected'].items():
                self.assertEqual(actual[key], value)


if __name__ == '__main__':
    unittest.main()
