"""Kaleid detection, GIP register framing, and the 0x07 hazard. No USB access."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controller_profile as profiles
import vendors.gamesir.control as control
import vendors.gamesir.models.cyclone2.led as led
from vendors.gamesir.models.kaleid import protocol as kaleid


class FakeDevice:
    """Records what the command layer would put on the wire."""

    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


def envelope(report):
    """Strip a GIP vendor message down to (command, body) with padding removed."""
    return report[3], report[4:]


class KaleidDetectionTests(unittest.TestCase):
    def tearDown(self):
        profiles.set_active(None)

    def test_each_mode_resolves_to_the_right_profile(self):
        self.assertIs(profiles.detect_one(0x1012, 'GameSir-K1 Controller for Xbox'),
                      profiles.KALEID)
        for pid in (0x1082, 0x1086):
            self.assertIs(profiles.detect_one(pid, 'GameSir-K1 Controller for Xbox'),
                          profiles.KALEID_OTHER)

    def test_only_the_gip_identity_is_writable(self):
        self.assertEqual(profiles.KALEID.write_style, 'gip')
        self.assertEqual(profiles.KALEID_OTHER.write_style, 'none')
        self.assertEqual(profiles.KALEID.usb_products, kaleid.CONFIG_PIDS)
        self.assertEqual(profiles.KALEID_OTHER.usb_products, kaleid.OTHER_MODE_PIDS)

    def test_lighting_is_claimed_but_the_profile_banks_are_not(self):
        # Lighting is confirmed on hardware; the profile banks are read-only
        # evidence, so declaring banks (or analog addresses) would overstate it.
        self.assertEqual(profiles.KALEID.lighting_style, 'cyclone_keyframe')
        self.assertEqual(profiles.KALEID.profile_banks, ())
        for attr in ('VIB_L', 'VIB_R', 'POLL_RATE', 'LT_DZ_MIN', 'ST_DZ_MIN'):
            self.assertIsNone(getattr(profiles.KALEID, attr), attr)
        self.assertEqual(profiles.KALEID.REMAP_SLOTS, ())

    def test_cyclone_lighting_sub_features_are_switched_off(self):
        for attr in ('software_profile_switch', 'lighting_slot_select',
                     'lighting_power', 'lighting_playback'):
            self.assertFalse(getattr(profiles.KALEID, attr), attr)
            self.assertTrue(getattr(profiles.CYCLONE, attr), attr)


class ProfileSwitchHazardTests(unittest.TestCase):
    """Vendor command 0x07 corrupts the Kaleid's profile -> lighting link."""

    def setUp(self):
        self.dev = FakeDevice()
        control.set_device(self.dev)

    def tearDown(self):
        control.clear_device()
        profiles.set_active(None)

    def test_set_profile_is_refused_for_the_kaleid(self):
        profiles.set_active(profiles.KALEID)
        self.assertFalse(control.set_profile(2))
        self.assertEqual(self.dev.writes, [])

    def test_set_profile_still_works_for_the_cyclone(self):
        profiles.set_active(profiles.CYCLONE)
        self.assertTrue(control.set_profile(2))
        self.assertEqual(self.dev.writes[0][:3], bytes((0x0F, 0x07, 0x02)))

    def test_no_kaleid_write_path_emits_the_command(self):
        profiles.set_active(profiles.KALEID)
        control.set_profile(1)
        control.write_reg(kaleid.LIGHT_BANK, led.record_addr(0), [1, 5, 3, 100])
        control.request_regs([(kaleid.LIGHT_BANK, 0x0000, 1)])
        control.pump_reads()
        for report in self.dev.writes:
            self.assertEqual(report[0], kaleid.COMMAND)
            self.assertNotIn(report[1], kaleid.HAZARD_COMMANDS)  # options, not 0x07
            self.assertEqual(report[1], kaleid.OPTIONS)


class GipFramingTests(unittest.TestCase):
    """The framing verified on hardware; see models/kaleid/protocol.py."""

    def setUp(self):
        self.dev = FakeDevice()
        control.set_device(self.dev)
        profiles.set_active(profiles.KALEID)

    def tearDown(self):
        control.clear_device()
        profiles.set_active(None)

    def test_a_register_write_is_a_gip_message_carrying_the_bare_command(self):
        self.assertTrue(control.write_reg(0x20, 0x0081, [0xFF, 0x00, 0x00]))
        self.assertEqual(len(self.dev.writes), 1)
        report = self.dev.writes[0]
        self.assertEqual(len(report), 64)
        self.assertEqual(report[0], kaleid.COMMAND)
        self.assertEqual(report[1], kaleid.OPTIONS)
        self.assertNotEqual(report[2], 0)           # GIP reserves sequence zero
        command, body = envelope(report)
        self.assertEqual(command, kaleid.VENDOR_CHANNEL)
        self.assertEqual(body[:8], bytes((0x03, 0x20, 0x00, 0x81, 0x03,
                                          0xFF, 0x00, 0x00)))

    def test_a_queued_read_uses_the_channel_that_answers_on_this_pad(self):
        control.request_regs([(0x20, 0x0001, 0x37)])
        control.pump_reads()
        command, body = envelope(self.dev.writes[0])
        self.assertEqual(command, kaleid.VENDOR_CHANNEL)   # 0x3c, not the G7's 0x05
        self.assertEqual(body[:5], bytes((0x04, 0x20, 0x00, 0x01, 0x37)))

    def test_a_whole_record_splits_into_chunks_the_pad_accepts(self):
        self.assertTrue(control.write_reg(0x20, led.record_addr(0), [0x11] * led.LED_REC))
        lengths, addrs = [], []
        for report in self.dev.writes:
            _cmd, body = envelope(report)
            addrs.append((body[2] << 8) | body[3])
            lengths.append(body[4])
            self.assertLessEqual(body[4], kaleid.READ_CHUNK)
        self.assertEqual(lengths, [0x37, 0x37, 0x7C - 2 * 0x37])
        self.assertEqual(addrs, [0x0001, 0x0001 + 0x37, 0x0001 + 2 * 0x37])

    def test_telemetry_is_not_mistaken_for_register_data(self):
        telemetry = bytes((0x10, 0x00, 0x05, 0x3C, kaleid.INPUT_MARKER,
                           0x80, 0x80, 0x80, 0x80, 0x0F)) + bytes(54)
        self.assertTrue(kaleid.is_telemetry(telemetry))
        self.assertIsNone(kaleid.register_reply(telemetry))

    def test_a_register_reply_decodes_to_bank_address_and_data(self):
        reply = bytes((0x10, 0x00, 0x05, 0x3C, kaleid.READ_MARKER,
                       0x20, 0x00, 0x81, 0x03, 0xFF, 0x00, 0x00)) + bytes(52)
        self.assertEqual(kaleid.register_reply(reply), (0x20, 0x0081, [0xFF, 0x00, 0x00]))
        self.assertFalse(kaleid.is_telemetry(reply))


class LightingLayoutTests(unittest.TestCase):
    """The Kaleid's bank 0x20 is the Cyclone's lighting layout.

    Settled by the pad's own contents: its four populated records hold palettes
    IDENTICAL to this project's captured Cyclone presets, matching on keyframe
    count and speed too. These are the headers read off the pad (firmware 1.65)
    at the addresses the Cyclone's record maths predicts -- the figures that
    corrected an earlier reading which had the record boundary three bytes late
    and so mistook each record's [count, marker, speed] header for a trailing
    field of the record before it.
    """

    OBSERVED = (
        # slot, address,  count, marker, speed, preset the palette matched
        (0, 0x0001, 5, 0x05, 3, 'Flow'),
        (1, 0x007D, 8, 0x05, 10, 'Rainbow'),
        (2, 0x00F9, 2, 0x05, 15, 'Pulse'),
        (3, 0x0175, 1, 0x05, 10, 'Standoff'),
    )

    def test_record_addresses_match_the_pad(self):
        for slot, addr, _c, _m, _s, _p in self.OBSERVED:
            self.assertEqual(led.record_addr(slot), addr)

    def test_the_captured_presets_decode_to_the_observed_headers(self):
        for _slot, _addr, count, marker, speed, preset in self.OBSERVED:
            record = list(led.PATTERNS[preset])
            self.assertEqual(record[0], count, preset)
            self.assertEqual(record[1], marker, preset)
            self.assertEqual(record[led.REC_SPEED_OFF], speed, preset)
            self.assertEqual(led.decode_record(record)['count'], count, preset)

    def test_the_palette_engine_marker_is_where_the_header_says(self):
        self.assertEqual(led.KEYFRAME_TYPE, 0x05)
        for _slot, _addr, _c, _m, _s, preset in self.OBSERVED:
            self.assertEqual(led.decode_record(list(led.PATTERNS[preset]))['type'],
                             led.KEYFRAME_TYPE)

    def test_the_record_is_read_in_chunks_the_gip_body_can_carry(self):
        # The Cyclone asks for 56 bytes a chunk; GIP carries 55. The pad answers
        # SHORT rather than refusing, so the plan has to come from the transport.
        self.assertEqual(profiles.KALEID.read_chunk, kaleid.READ_CHUNK)
        fields = led.record_read_fields(2, profiles.KALEID.read_chunk)
        self.assertEqual([ln for _b, _a, ln in fields], [55, 55, 14])
        for _bank, _addr, ln in fields:
            self.assertLessEqual(ln, kaleid.READ_CHUNK)

    def test_a_record_read_over_gip_reassembles_byte_for_byte(self):
        original = list(led.PATTERNS['Pulse'])
        fields = led.record_read_fields(2, kaleid.READ_CHUNK)
        base = led.record_addr(2)
        replies = {addr: original[addr - base:addr - base + ln]
                   for _b, addr, ln in fields}
        self.assertEqual(led.stitch_record(2, replies, kaleid.READ_CHUNK), original)

    def test_a_short_reply_fails_instead_of_shifting_the_record(self):
        # The live bug: a 56-byte plan answered with 55-byte replies used to
        # stitch a misaligned record that decoded into a plausible wrong palette.
        original = list(led.PATTERNS['Pulse'])
        base = led.record_addr(2)
        short = {addr: original[addr - base:addr - base + ln][:55]
                 for _b, addr, ln in led.record_read_fields(2, 56)}
        self.assertIsNone(led.stitch_record(2, short, 56))

    def test_four_records_fit_inside_the_span_the_pad_answers_for(self):
        # 0x0001 + 5*0x7c = 0x026d, where the Cyclone keeps its power block; the
        # pad answers reads past there, which is how the fifth record was found.
        self.assertEqual(led.record_addr(4) + led.LED_REC, led.AUDIO_REACTIVE)


if __name__ == '__main__':
    unittest.main()


class LightMapTests(unittest.TestCase):
    """The per-model light map: which render-frame positions each light drives."""

    def tearDown(self):
        profiles.set_active(None)

    def test_the_kaleid_exposes_two_sides_the_cyclone_four_lights(self):
        profiles.set_active(profiles.KALEID)
        self.assertEqual(led.light_names(), ['Left', 'Right'])
        profiles.set_active(profiles.CYCLONE)
        self.assertEqual(led.light_names(), ['Left grip', 'Right grip', 'Profile', 'Home'])

    def test_a_kaleid_side_paints_both_of_its_positions(self):
        """Each zone floods a whole side, so one colour has to land on the pair."""
        profiles.set_active(profiles.KALEID)
        frame = led._render_frame([(1, 1, 1), (2, 2, 2)])
        self.assertEqual(frame[0], (1, 1, 1))
        self.assertEqual(frame[2], (1, 1, 1))
        self.assertEqual(frame[1], (2, 2, 2))
        self.assertEqual(frame[4], (2, 2, 2))

    def test_the_dead_position_is_filled_not_zeroed(self):
        """A zeroed hole breaks the frame; the Kaleid's hole is 3, the Cyclone's 2."""
        profiles.set_active(profiles.KALEID)
        self.assertEqual(led._render_frame([(9, 9, 9), (2, 2, 2)])[3], (9, 9, 9))
        profiles.set_active(profiles.CYCLONE)
        cyc = led._render_frame([(9, 9, 9), (2, 2, 2), (3, 3, 3), (4, 4, 4)])
        self.assertEqual(cyc[2], (9, 9, 9))
        self.assertEqual(cyc, [(9, 9, 9), (2, 2, 2), (9, 9, 9), (3, 3, 3), (4, 4, 4)])

    def test_no_render_position_is_ever_left_black_by_the_map(self):
        for prof in profiles.ALL:
            if prof.lighting_style != 'cyclone_keyframe':
                continue
            profiles.set_active(prof)
            cols = [(i + 1,) * 3 for i in range(len(led.lights()))]
            self.assertNotIn((0, 0, 0), led._render_frame(cols), prof.name)

    def test_every_mapped_position_fits_the_render_frame_and_is_unclaimed_twice(self):
        """Drift guard: two lights sharing a position would make one unwritable."""
        for prof in profiles.ALL:
            spec = prof.lighting_lights
            if not spec:
                continue
            seen = []
            for name, default, positions in spec:
                self.assertTrue(positions, f'{prof.name}/{name} drives nothing')
                self.assertEqual(len(default), 3, f'{prof.name}/{name} default')
                for pos in positions:
                    self.assertIn(pos, range(led.FRAME_TRIPLETS), f'{prof.name}/{name}')
                    self.assertNotIn(pos, seen, f'{prof.name}: position {pos} claimed twice')
                    seen.append(pos)

    def test_a_kaleid_keyframe_decodes_back_to_the_colours_written(self):
        profiles.set_active(profiles.KALEID)
        want = [[(255, 0, 0), (0, 0, 255)], [(0, 255, 0), (255, 255, 0)]]
        flat = []
        for cols in want:
            for r, g, b in led._render_frame(cols):
                flat += [r, g, b]
        flat += [0] * ((led.NUM_FRAMES - len(want)) * led.FRAME_TRIPLETS * 3)
        rec = [len(want), led.KEYFRAME_TYPE, 10, 0x64] + flat
        got = led.decode_record(rec[:led.LED_REC])
        self.assertEqual(got['count'], len(want))
        for i, cols in enumerate(want):
            self.assertEqual(got['frames'][i], [list(c) for c in cols])


class AnimationKeepaliveTests(unittest.TestCase):
    """The pad idles its animation when the claimed interface goes quiet, so the
    session's slot poll doubles as a keepalive. These guard the margin: raising the
    poll interval past the idle timeout would freeze the animation while the owner
    edits, with nothing in the UI to explain it."""

    def test_the_poll_interval_stays_well_inside_the_idle_timeout(self):
        self.assertLess(kaleid.KEEPALIVE_SECS, kaleid.ANIM_IDLE_TIMEOUT / 2,
                        'the slot poll is the animation keepalive; keep a wide margin')

    def test_the_session_polls_on_the_keepalive_constant_not_a_literal(self):
        """A bare 1.0 here reads like a UI refresh rate and invites tuning it."""
        import inspect
        import reader
        src = inspect.getsource(reader.read_session_kaleid)
        self.assertIn('kaleid.KEEPALIVE_SECS', src)

    def test_no_profile_claims_lighting_pauses_on_write(self):
        """That flag described a write effect that turned out not to exist -- the
        stop is an idle timeout. If it comes back, it needs new evidence."""
        for prof in profiles.ALL:
            self.assertFalse(hasattr(prof, 'lighting_pauses_on_write'), prof.name)
