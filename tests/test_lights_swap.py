import unittest

import controller_profile as profiles
import vendors.gamesir.models.cyclone2.led as led

LEFT, RIGHT, PROFILE, HOME = (1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4)


class HomeProfileSwapTests(unittest.TestCase):
    """Some Cyclone 2 units light Home and Profile the other way round (#48)."""

    def tearDown(self):
        led.swap_home_profile = False

    def test_swap_exchanges_the_two_positions_when_writing(self):
        profiles.set_active(profiles.CYCLONE)
        plain = led._render_frame([LEFT, RIGHT, PROFILE, HOME])
        led.swap_home_profile = True
        swapped = led._render_frame([LEFT, RIGHT, PROFILE, HOME])
        self.assertEqual((plain[3], plain[4]), (PROFILE, HOME))
        self.assertEqual((swapped[3], swapped[4]), (HOME, PROFILE))
        self.assertEqual(swapped[:3], plain[:3])

    def test_swapped_record_reads_back_as_written(self):
        profiles.set_active(profiles.CYCLONE)
        led.swap_home_profile = True
        rec = led.keyframes_record([[LEFT, RIGHT, PROFILE, HOME]])
        frame = led.decode_record(rec)['frames'][0]
        self.assertEqual([tuple(c) for c in frame], [LEFT, RIGHT, PROFILE, HOME])

    def test_names_and_order_stay_the_same(self):
        profiles.set_active(profiles.CYCLONE)
        before = led.light_names()
        led.swap_home_profile = True
        self.assertEqual(led.light_names(), before)

    def test_models_with_their_own_map_ignore_it(self):
        profiles.set_active(profiles.KALEID)
        led.swap_home_profile = True
        self.assertEqual(led.lights(), profiles.KALEID.lighting_lights)


if __name__ == '__main__':
    unittest.main()
