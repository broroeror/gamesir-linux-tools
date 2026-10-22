"""Recovery files must preserve T4N2 setting boundaries through Backup & Restore."""
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import backup
import controller_profile as profiles
import register_transaction as transaction
from gs_state import state
from vendors.gamesir import config, control
from vendors.gamesir.models.nova2lite import protocol as n2l


class T4N2Pad:
    """Emulate the wire settings, including composite stick/hair/vibration packets."""

    def __init__(self):
        self.sticks = {side: [5, 0, 16, 16, 50, 50, 84, 84, 100, 100, 0, 100]
                       for side in (1, 2)}
        self.hair = [2, 2]
        self.vibration = [75, 100]
        self.remaps = {0xCB: 0xC0, 0xCD: 0xC1}  # L4 -> LS, R4 -> RS
        self.options = {}
        self.replies, self.writes = [], []

    def write(self, packet):
        data = list(packet[1:])
        op = data[0]
        reply = None
        if op == 0xF0:
            side = data[3]
            if data[1] == 0:
                reply = n2l.frame_packet([op, 0, 17, side, *self.sticks[side]], 17)
            else:
                self.sticks[side] = data[4:16]
        elif op == 0xF1:
            source = data[3]
            if data[1] == 0:
                target = self.remaps.get(source, 0)
                reply = n2l.frame_packet([op, 0, 9, source, int(bool(target)), target, 0, 0], 9)
            else:
                self.remaps[source] = data[5] if data[1] == 1 else 0
        elif op == 0x21:
            if data[1] == 0:
                reply = n2l.frame_packet([op, 0, *self.hair], 5)
            else:
                self.hair[:] = data[2:4]
        elif op == 0x25:
            if data[3] == 0:
                left, right = self.vibration
                reply = n2l.frame_packet([op, 1, 13, 0, left, 3, 0, 0, right, 3, 0, 0], 13)
            else:
                self.vibration[:] = [data[4], data[8]]
        elif op in (0x23, 0x07):
            key = (op, data[1])
            if data[3] == 0:
                reply = n2l.frame_packet([op, data[1], 6, 0, self.options.get(key, 0)], 6)
            else:
                self.options[key] = data[4]
        else:
            raise AssertionError(f'unexpected T4N2 command 0x{op:02x}')
        if reply is not None:
            self.replies.append(list(reply[1:]))
        else:
            self.writes.append(data)
        return len(packet)


class Nova2LiteRecoveryTests(unittest.TestCase):
    def setUp(self):
        old_profile = profiles.active()
        self.addCleanup(profiles.set_active, old_profile)
        patch_state = patch.dict(state, connected=True, profile=1, edit_profile=1)
        patch_state.start()
        self.addCleanup(patch_state.stop)
        for name in ('_switch_sent_seq', '_switch_target'):
            patch_switch = patch.object(control, name, None)
            patch_switch.start()
            self.addCleanup(patch_switch.stop)
        profiles.set_active(profiles.NOVA_2_LITE)
        self.pad = T4N2Pad()
        control.set_device(self.pad)
        self.addCleanup(control.clear_device)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        request_regs = control.request_regs

        def request_and_pump(reqs):
            request_regs(reqs)
            while not control.reads_idle():
                control.pump_reads()
                self.assertTrue(self.pad.replies, 'a complete setting must have a read reply')
                self.assertTrue(control.store_t4n2_reply(self.pad.replies.pop(0)))

        for mock in (patch.object(control, 'request_regs', request_and_pump),
                     patch.object(control.time, 'sleep'),
                     patch.object(threading.Thread, 'start', lambda thread: thread.run())):
            mock.start()
            self.addCleanup(mock.stop)

    def read(self, bank, addr, length):
        control.request_regs([(bank, addr, length)])
        return control.reg_result(bank, addr)

    def snapshot(self):
        return {(bank, addr): self.read(bank, addr, length)
                for bank, addr, length in backup._all_requests()}

    def save(self, changes, **kwargs):
        ok, message = transaction.apply(changes, self.read, control.write_reg,
                                         self.tmp.name, profiles.NOVA_2_LITE.name, **kwargs)
        self.assertTrue(ok, message)
        path, = Path(self.tmp.name).glob('before_apply_*.json')
        return backup.load(path)

    def test_generated_recovery_restores_curves_remaps_hair_and_composite_settings(self):
        before = self.snapshot()
        remaps = dict(n2l.REMAP_SLOTS)
        changes = [
            (1, n2l.ST_DZ_MIN, [12]),
            (1, n2l.ST_CURVE, list(config.CURVE_BLOCKS[1][1])),
            (1, n2l.RS_CURVE, list(config.CURVE_BLOCKS[2][1])),
            (1, remaps['L4'], [1, 9]),
            (1, remaps['R4'], [1, 0xFF]),
            (1, n2l.LT_HAIR, [0x81]),
            (1, n2l.RT_HAIR, [0x82, 0x0A, 0x5A]),
            (1, n2l.VIB_L, [25]),
            (1, n2l.DPAD_LOCK, [1]),
        ]
        recovery = self.save(changes, recovery_blocks=True)
        fields = recovery['profiles']['1']
        self.assertEqual(len(fields), len(changes))
        for bank, addr, data in changes:
            self.assertEqual(fields[f'0x{addr:04x}']['bytes'], before[(bank, addr)][:len(data)])
        self.assertEqual(fields[f'0x{remaps["L4"]:04x}']['bytes'], [1, 7])
        self.assertNotEqual(self.snapshot(), before)
        self.pad.writes.clear()
        result = []
        backup.apply_backup(recovery, on_done=lambda ok, msg: result.append((ok, msg)))
        self.assertTrue(result[0][0], result[0][1])
        self.assertEqual(self.snapshot(), before)
        l4_write, = [data for data in self.pad.writes if data[0] == 0xF1 and data[3] == 0xCB]
        self.assertEqual(l4_write[1:6], [1, 9, 0xCB, 1, 0xC0])  # assignment, never reset

    def test_old_byte_split_recovery_is_rejected_before_worker_or_any_write(self):
        remap = dict(n2l.REMAP_SLOTS)['L4']
        for addr, data in ((remap, [1, 9]),
                           (n2l.ST_CURVE, list(config.CURVE_BLOCKS[1][1])),
                           (n2l.LT_HAIR, [0x82, 0x0A, 0x5A])):
            with self.subTest(addr=f'0x{addr:04x}'), tempfile.TemporaryDirectory() as directory:
                # Reproduce the old writer, with a valid scalar before the
                # fragmented setting: validation must refuse the WHOLE batch.
                ok, message = transaction.apply([(1, n2l.VIB_L, [50]), (1, addr, data)],
                                                  self.read, control.write_reg, directory,
                                                  profiles.NOVA_2_LITE.name)
                self.assertTrue(ok, message)
                path, = Path(directory).glob('before_apply_*.json')
                recovery = backup.load(path)
                self.pad.writes.clear()
                with patch.object(threading.Thread, 'start') as start:
                    with self.assertRaisesRegex(ValueError, 'complete setting blocks.*byte-split'):
                        backup.apply_backup(recovery)
                start.assert_not_called()
                self.assertEqual(self.pad.writes, [])

    def test_validation_accepts_full_settings_and_both_staged_hair_lengths(self):
        writes = [(bank, addr, self.read(bank, addr, length))
                  for bank, addr, length in backup._all_requests()]
        writes += [(1, n2l.LT_HAIR, [0x81]), (1, n2l.RT_HAIR, [0x81])]
        backup._validate_writes(writes)
        for addr, data in ((n2l.ST_CURVE, [0]),
                           (dict(n2l.REMAP_SLOTS)['L4'], [1]),
                           (n2l.LT_HAIR + 1, [10]),
                           (n2l.VIB_L, [75, 100])):
            with self.subTest(addr=addr, length=len(data)):
                with self.assertRaisesRegex(ValueError, 'complete setting blocks'):
                    backup._validate_writes([(1, addr, data)])

    def test_repeated_setting_keeps_longest_pre_write_snapshot(self):
        recovery = self.save([(1, n2l.LT_HAIR, [0x81]),
                              (1, n2l.LT_HAIR, [0x82, 0x0A, 0x5A])], recovery_blocks=True)
        fields = recovery['profiles']['1']
        self.assertEqual(fields, {'0x01fa': {'addr': '0x01fa', 'bytes': [0, 10, 90]}})

    def test_raw_register_recovery_still_preserves_partial_and_overlapping_edits(self):
        profiles.set_active(profiles.CYCLONE)
        addr = profiles.CYCLONE.LT_HAIR
        original = {(1, addr + i): byte for i, byte in enumerate([0, 10, 90])}
        memory = copy.copy(original)

        def read(bank, address, length):
            return [memory[(bank, address + i)] for i in range(length)]

        def write(bank, address, data):
            memory.update({(bank, address + i): byte for i, byte in enumerate(data)})
            return True

        ok, message = transaction.apply([(1, addr, [0x81, 10, 90]), (1, addr + 1, [11])],
                                          read, write, self.tmp.name, profiles.CYCLONE.name)
        self.assertTrue(ok, message)
        path, = Path(self.tmp.name).glob('before_apply_*.json')
        writes = backup._writes_from(backup.load(path))
        self.assertEqual(writes, [(1, addr, [0]), (1, addr + 1, [10]), (1, addr + 2, [90])])
        backup._validate_writes(writes)
        for bank, address, data in writes:
            write(bank, address, data)
        self.assertEqual(memory, original)


if __name__ == '__main__':
    unittest.main()
