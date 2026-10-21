"""Export and Restore switch the pad through its profiles, and a profile bank
only takes reads/writes while that profile is active. These tests check the
switch is CONFIRMED before a bank is touched, so a dropped switch can't read or
write the wrong profile. No hardware: a fake pad behind patched control calls."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import backup
import controller_profile as profiles
from gs_state import state
from vendors.gamesir import control


class FakePad:
    """Profile banks answer only while active; `stuck` profiles ignore switches."""

    def __init__(self):
        self.mem, self.results, self.stuck = {}, {}, set()
        self.written_while = []          # (bank, active profile) per write

    def set_profile(self, n, gen=None):
        if n not in self.stuck:
            state['profile'] = n         # what the reader would publish...
            state['profile_seq'] = state.get('profile_seq', 0) + 1   # ...as a fresh reply
        return True

    def write_reg(self, bank, addr, data, write_style=None, gen=None):
        self.written_while.append((bank, state.get('profile')))
        if bank in (1, 2, 3, 4) and bank != state.get('profile'):
            return True                  # dropped: bank isn't the active profile
        for i, v in enumerate(data):
            self.mem[(bank, addr + i)] = v
        return True

    def request_regs(self, reqs):
        for bank, addr, ln in reqs:
            if bank in (1, 2, 3, 4) and bank != state.get('profile'):
                continue                 # no reply for an inactive profile
            self.results[(bank, addr)] = [self.mem.get((bank, addr + i), bank) for i in range(ln)]

    def reg_result(self, bank, addr):
        return self.results.get((bank, addr))

    def clear(self, *_a, **_k):
        self.results.clear()


class BackupProfileSwitchTests(unittest.TestCase):
    def setUp(self):
        self.old = profiles.active()
        profiles.set_active(profiles.CYCLONE)
        self.real_set_profile = control.set_profile
        self.pad = FakePad()
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.dict(state, profile=1, profile_seq=0, connected=True),
            patch.object(control, '_switch_sent_seq', None),
            patch.object(control, '_switch_target', None),
            patch.object(control, 'set_profile', self.pad.set_profile),
            patch.object(control, 'write_reg', self.pad.write_reg),
            patch.object(control, 'request_regs', self.pad.request_regs),
            patch.object(control, 'reg_result', self.pad.reg_result),
            patch.object(backup, 'PROFILE_CONFIRM', 0.05),
            patch.object(backup, 'PROFILE_SETTLE', 0.0),
            patch.object(backup, 'READ_TIMEOUT', 0.3),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        profiles.set_active(self.old)
        self.tmp.cleanup()

    def run_and_wait(self, fn, *args):
        done, out = threading.Event(), {}
        def fin(ok, msg):
            out.update(ok=ok, msg=msg)
            done.set()
        with patch.object(threading.Thread, 'start', lambda t: t.run()):
            fn(*args, on_done=fin)
        self.assertTrue(done.wait(5))
        return out

    def test_switch_is_confirmed_and_resent(self):
        self.assertTrue(backup._switch_profile(3))
        self.assertEqual(state['profile'], 3)
        self.pad.stuck.add(2)
        self.assertFalse(backup._switch_profile(2))
        self.assertEqual(state['profile'], 3)

    def test_export_refuses_when_a_profile_wont_switch(self):
        self.pad.stuck.add(3)
        path = os.path.join(self.tmp.name, 'b.json')
        out = self.run_and_wait(backup.export_async, path)
        self.assertFalse(out['ok'])
        self.assertIn("didn't switch to profile 3", out['msg'])
        self.assertFalse(os.path.exists(path))
        self.assertEqual(state['profile'], 1)              # put back where it was

    def test_restore_never_writes_a_profile_it_couldnt_select(self):
        path = os.path.join(self.tmp.name, 'b.json')
        self.assertTrue(self.run_and_wait(backup.export_async, path)['ok'])
        data = backup.load(path)
        self.pad.stuck.add(2)
        self.pad.written_while.clear()
        out = self.run_and_wait(backup.apply_backup, data)
        self.assertFalse(out['ok'])
        self.assertIn("didn't switch to profile 2", out['msg'])
        for bank, active in self.pad.written_while:
            if bank in (1, 2, 3, 4):
                self.assertEqual(bank, active, 'a profile bank was written while another was active')
        self.assertNotIn(2, {b for b, _a in self.pad.written_while})
        self.assertEqual(state['profile'], 1)

    def test_restore_succeeds_when_every_switch_lands(self):
        path = os.path.join(self.tmp.name, 'b.json')
        self.assertTrue(self.run_and_wait(backup.export_async, path)['ok'])
        out = self.run_and_wait(backup.apply_backup, backup.load(path))
        self.assertTrue(out['ok'], out['msg'])
        self.assertEqual(state['profile'], 1)

    # --- schema: a raw export must be restorable (it was stamped 4, the G7 Pro's
    # number, from Sept 3 to Oct 14 2026 and restore then refused it) ----------
    def test_export_is_a_raw_schema_3_backup(self):
        path = os.path.join(self.tmp.name, 'b.json')
        self.assertTrue(self.run_and_wait(backup.export_async, path)['ok'])
        self.assertEqual(backup.load(path)['schema'], 3)

    def test_a_mislabelled_schema_4_raw_backup_still_restores(self):
        path = os.path.join(self.tmp.name, 'b.json')
        self.assertTrue(self.run_and_wait(backup.export_async, path)['ok'])
        data = backup.load(path)
        data['schema'] = 4                       # as exported Sept 3 - Oct 14
        self.assertFalse(backup._is_g7_semantic(data))
        out = self.run_and_wait(backup.apply_backup, data)
        self.assertTrue(out['ok'], out['msg'])

    def test_a_real_g7_backup_still_goes_to_the_g7_path(self):
        g7 = {'schema': 4, 'device': profiles.G7_PRO.name,
              'profiles': {'1': {'vib_l': 50, 'poll': 2}}, 'lighting': {}}
        self.assertTrue(backup._is_g7_semantic(g7))
        with self.assertRaisesRegex(ValueError, 'G7 Pro'):
            backup.apply_backup(g7)               # a Cyclone is connected

    def test_a_g7_se_refuses_every_backup_but_its_own(self):
        cyclone = {'schema': 3, 'device': profiles.CYCLONE.name,
                   'profiles': {'1': {'0x0020': {'addr': '0x0020', 'bytes': [7]}}},
                   'lighting': {'fields': {}}}
        g7 = {'schema': 4, 'device': profiles.G7_PRO.name,
              'profiles': {'1': {'vib_l': 50}}, 'lighting': {}}
        profiles.set_active(profiles.G7_SE)
        try:
            for data in (cyclone, g7):
                with patch.object(backup, '_expand_units') as generic, \
                        self.assertRaisesRegex(ValueError, 'g7se-banks'):
                    backup.apply_backup(data)
                generic.assert_not_called()
        finally:
            profiles.set_active(profiles.CYCLONE)

    # --- core-pass review (C1-C9) -------------------------------------------
    def test_a_refused_switch_fails_at_once(self):
        with patch.object(control, 'set_profile', lambda n, gen=None: False):
            t = time.monotonic()
            self.assertFalse(control.switch_profile(3, confirm=1.0))
            self.assertLess(time.monotonic() - t, 0.5)

    def test_a_controller_swap_stops_the_switch(self):
        self.assertFalse(control.switch_profile(3, gen=control.generation() + 1))
        self.assertEqual(state['profile'], 1)            # nothing was sent

    def test_a_profile_change_during_an_export_read_is_caught(self):
        real = self.pad.request_regs
        def flip(reqs):
            real(reqs)
            if any(b == 2 for b, _a, _l in reqs):
                state['profile'] = 3                       # an on-pad chord mid-read
        self.pad.request_regs = flip
        with patch.object(control, 'request_regs', flip):
            path = os.path.join(self.tmp.name, 'b.json')
            out = self.run_and_wait(backup.export_async, path)
        self.assertFalse(out['ok'])
        self.assertIn('changed profile while profile 2', out['msg'])
        self.assertFalse(os.path.exists(path))

    def test_export_reports_a_failed_switch_back(self):
        path = os.path.join(self.tmp.name, 'b.json')
        real = self.pad.set_profile
        def stuck_after(n, gen=None):
            return real(n) if n != 1 else True           # the way back is dropped
        with patch.object(control, 'set_profile', stuck_after):
            out = self.run_and_wait(backup.export_async, path)
        self.assertTrue(out['ok'])
        self.assertIn('switch it back to profile 1', out['msg'])

    def test_kaleid_backup_never_switches_and_its_old_label_restores(self):
        profiles.set_active(profiles.KALEID)
        sent = []
        with patch.object(control, 'set_profile', lambda n, gen=None: sent.append(n) or False):
            path = os.path.join(self.tmp.name, 'k.json')
            t = time.monotonic()
            out = self.run_and_wait(backup.export_async, path)
            self.assertTrue(out['ok'], out['msg'])
            self.assertNotIn('switch it back', out['msg'])
            data = backup.load(path)
            self.assertEqual(data['profiles'], {})
            data['schema'] = 4                           # as exported Sept 3 - Oct 14
            self.assertFalse(backup._is_g7_semantic(data))
            out = self.run_and_wait(backup.apply_backup, data)
            self.assertTrue(out['ok'], out['msg'])
            self.assertNotIn('switch it back', out['msg'])
            self.assertLess(time.monotonic() - t, 2.0)    # no 3 x confirm stall
        self.assertEqual(sent, [])

    # --- bridge + reader pass (B1, B4): only a reply AFTER a switch counts ---
    def test_a_stale_answer_does_not_confirm_a_switch(self):
        sent = []
        with patch.object(control, 'send_cmd', lambda *a, **k: sent.append(a) or True), \
             patch.object(control, 'set_profile', self.real_set_profile):
            state.update(profile=2, profile_seq=5)
            self.assertTrue(control.set_profile(1))
            self.assertFalse(control.profile_confirmed(2))     # the old answer, not current
            self.assertFalse(control.profile_confirmed(1))     # not answered yet
            self.assertEqual(control.expected_profile(), 1)    # but it's where we're headed
            state.update(profile=1, profile_seq=6)             # the pad answers
            self.assertTrue(control.profile_confirmed(1))
            self.assertEqual(control.expected_profile(), 1)

    def test_switch_asks_the_pad_instead_of_waiting_for_its_poll(self):
        asked = []
        def send(*a, **k):
            if a[:2] == (0x0F, 0x0B):
                asked.append(a)
                state.update(profile=3, profile_seq=state.get('profile_seq', 0) + 1)
            return True
        with patch.object(control, 'send_cmd', send), \
             patch.object(control, 'set_profile', self.real_set_profile):
            t = time.monotonic()
            self.assertTrue(control.switch_profile(3, confirm=2.5, settle=0))
            self.assertLess(time.monotonic() - t, 1.0)
        self.assertTrue(asked)


class _BridgeCase(BackupProfileSwitchTests.__base__):
    """The bridge's own profile walks, on the same fake pad."""

    def setUp(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QGuiApplication
        self.app = QGuiApplication.instance() or QGuiApplication([])
        BackupProfileSwitchTests.setUp(self)
        # factory.py imports write_reg BY NAME, so patching control alone
        # wouldn't reach it (the first import would pin one test's fake)
        import vendors.gamesir.models.cyclone2.factory as factory
        self.patches.append(patch.object(factory, 'write_reg', self.pad.write_reg))
        self.patches[-1].start()
        # the bridge calls switch_profile with its real 2.5 s window; shorten it
        real = control.switch_profile
        def quick(n, gen=None, check=None, **k):
            k.setdefault('confirm', 0.05)
            k.setdefault('settle', 0)
            return real(n, gen=gen, check=check, **k)
        self.patches.append(patch.object(control, 'switch_profile', quick))
        self.patches[-1].start()
        from bridge import GamesirBridge
        self.bridge = GamesirBridge()
        self.bridge._prof = profiles.CYCLONE
        self.results = []
        self.bridge.backupStatus.connect(lambda ok, msg: self.results.append((ok, msg)))

    def tearDown(self):
        BackupProfileSwitchTests.tearDown(self)


class ResetAllProfilesTests(_BridgeCase):
    """Reset-all walks every profile too (finding C6): same confirmed switch."""

    def reset_all(self):
        with patch.object(threading.Thread, 'start', lambda t: t.run()):
            self.bridge.resetAllProfiles()
        self.app.processEvents()
        return self.results[-1]

    def test_reset_all_stops_at_a_profile_that_wont_switch(self):
        self.pad.stuck.add(3)
        ok, msg = self.reset_all()
        self.assertFalse(ok)
        self.assertIn("didn't switch to profile 3", msg)
        for bank, active in self.pad.written_while:
            if bank in (1, 2, 3, 4):
                self.assertEqual(bank, active)
        self.assertNotIn(3, {b for b, _a in self.pad.written_while})
        self.assertEqual(state['profile'], 1)

    def test_reset_all_switches_back_when_done(self):
        ok, msg = self.reset_all()
        self.assertTrue(ok, msg)
        self.assertEqual(state['profile'], 1)
        self.assertEqual({b for b, _a in self.pad.written_while if b < 5}, {1, 2, 3, 4})
        # the lighting record is shared by every profile: written once, not 4x
        import vendors.gamesir.models.cyclone2.factory as factory
        self.assertEqual(sum(1 for b, _a in self.pad.written_while if b == 0x20),
                         len(factory.DEFAULT_LIGHTING))



class SaveProfileSwitchTests(_BridgeCase):
    """Save switches to the edited profile and back (findings B1, B2)."""

    def save(self):
        with patch.object(threading.Thread, 'start', lambda t: t.run()):
            self.bridge.applyConfig()
        self.app.processEvents()
        return self.bridge._apply_status

    def stage(self, bank, value):
        addr, ln, _name = backup._profile_fields()[0]
        self.bridge._pending[(bank, addr)] = {'addr': addr, 'bank': bank, 'data': [value] * ln,
                                              'label': 'x', 'display': 'y'}

    def test_two_quick_saves_both_land_on_the_edited_profile(self):
        state.update(selected='x', driving='x', edit_profile=2)
        self.bridge._driving = 'x'
        for value in (7, 9):
            self.stage(2, value)
            self.assertIn('Applied', self.save())
            self.assertEqual(state['profile'], 1)          # back on the user's profile
        for bank, active in self.pad.written_while:
            if bank in (1, 2, 3, 4):
                self.assertEqual(bank, active, 'a profile bank was written while another was active')

    def test_a_save_that_never_switched_doesnt_switch_back(self):
        state.update(selected='x', driving='x', edit_profile=1)
        self.bridge._driving = 'x'
        sent = []
        real = self.pad.set_profile
        with patch.object(control, 'set_profile', lambda n, gen=None: sent.append(n) or real(n)):
            self.stage(1, 5)
            self.assertIn('Applied', self.save())
        self.assertEqual(sent, [])



class ProfileLoadTests(_BridgeCase):
    """Clicking a profile sends the switch; its settings must not be read until
    the pad confirms it, or the previous profile's values show under the new
    name (the 'my remap went to P1' scare, 2026-10-13)."""

    def test_settings_load_only_after_the_switch_is_confirmed(self):
        state.update(selected='x', driving='x', edit_profile=1)
        sent, reads = [], []
        with patch.object(control, 'send_cmd', lambda *a, **k: sent.append(a) or True), \
             patch.object(control, 'set_profile', self.real_set_profile), \
             patch.object(control, 'request_regs', lambda reqs: reads.extend(reqs)):
            self.bridge._loaded_profile = 1
            self.bridge.setProfile(2)                      # sends 0x07, edit_profile = 2
            self.bridge._poll_config()
            self.assertEqual(reads, [], 'read profile 2 before the pad switched')
            state.update(profile=2, profile_seq=state['profile_seq'] + 1)   # pad answers
            self.bridge._poll_config()
            self.assertTrue(reads)
            self.assertEqual({b for b, _a, _l in reads}, {2})


if __name__ == '__main__':
    unittest.main()
