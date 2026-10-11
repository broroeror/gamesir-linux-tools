"""Super Nova snapshot / restore / verified-write logic against a simulated pad
whose every reply comes from a real capture (fixtures/supernova_capture01.json).
No USB access required."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vendors.gamesir.models.supernova import config as nova
from vendors.gamesir.models.supernova import protocol as sn
from vendors.gamesir.models.supernova import transport

FIXTURE = json.loads((ROOT / 'tests' / 'fixtures' / 'supernova_capture01.json').read_text())


class FakePad:
    """Answers like the real pad: gets from the capture, sets stored when the
    layout matches (set payload == get data), save recorded."""

    def __init__(self, ignore_writes=False, device_type=None):
        self.store = {k: bytes.fromhex(v) for k, v in FIXTURE['replies'].items()}
        if device_type is not None:
            info = bytearray(self.store['get_device_info/'])
            info[0] = device_type
            self.store['get_device_info/'] = bytes(info)
        self.ignore_writes = ignore_writes
        self.sent = []
        self.saves = 0

    def _get_key_for_set(self, kind, payload):
        for b in nova.BLOCKS.values():
            if b.kind == kind and all(payload[o] == v for o, v in b.id_at):
                return f'get_{kind}/{bytes(b.args).hex()}'
        raise KeyError(kind)

    def request(self, name, payload=b''):
        sn.encode_request(*sn.COMMANDS[name], payload)   # same refusal as the wire
        self.sent.append((name, bytes(payload)))
        if name.startswith('get_'):
            return self.store[f'{name}/{bytes(payload).hex()}']
        if name == 'save_config_page':
            self.saves += 1
            return b'\x00'
        if name == 'set_vibrate_test':
            return b'\x00'              # a pulse; stores nothing (real pad, 2026-10-10)
        kind = name[4:]
        key = self._get_key_for_set(kind, payload)
        if len(payload) != len(self.store[key]):
            return b'\x01'
        if not self.ignore_writes:
            self.store[key] = bytes(payload)
        return b'\x00'

    def writes(self):
        return [n for n, _ in self.sent if not n.startswith('get_')]


class SnapshotTests(unittest.TestCase):
    def test_a_snapshot_reads_every_block_the_app_reads(self):
        snap = nova.snapshot(FakePad())
        self.assertEqual(len(snap['blocks']), len(nova.BLOCKS))
        self.assertEqual(snap['device_type'], sn.DEVICE_TYPE_ID)
        self.assertEqual(snap['blocks']['vibrate_param'], '4b4b00004b4b')

    def test_a_snapshot_never_writes(self):
        pad = FakePad()
        nova.snapshot(pad)
        self.assertEqual(pad.writes(), [])

    def test_a_t3_pro_behind_the_shared_dongle_is_refused(self):
        with self.assertRaises(nova.PadError):
            nova.snapshot(FakePad(device_type=0))

    def test_the_fixture_has_every_block_and_no_device_address(self):
        for b in nova.BLOCKS.values():
            self.assertIn(f'get_{b.kind}/{bytes(b.args).hex()}', FIXTURE['replies'])
        self.assertEqual(FIXTURE['replies']['get_device_info/'][6:18], '0' * 12)


class WriteTests(unittest.TestCase):
    def test_a_verified_write_changes_one_block_only(self):
        pad = FakePad()
        before = nova.snapshot(pad)
        block = nova.BLOCKS['trigger_param/01']
        new = sn.with_begin_deadzone(nova.read_block(pad, block), sn.TRIG_POINTS, 10)
        nova.write_block(pad, block, new)
        nova.save(pad)
        changed = nova.diff(before, nova.snapshot(pad))
        self.assertEqual(list(changed), ['trigger_param/01'])
        self.assertEqual(pad.writes(), ['set_trigger_param', 'save_config_page'])

    def test_a_write_the_pad_does_not_keep_is_undone_and_never_saved(self):
        pad = FakePad(ignore_writes=True)
        block = nova.BLOCKS['vibrate_param']
        with self.assertRaises(nova.PadError):
            nova.write_block(pad, block, bytes.fromhex('324b00004b4b'))
        self.assertEqual(pad.writes(), ['set_vibrate_param', 'set_vibrate_param'])
        self.assertEqual(pad.saves, 0)

    def test_an_unconfirmed_layout_is_never_written(self):
        pad = FakePad()
        with self.assertRaises(nova.PadError):
            nova.write_block(pad, nova.BLOCKS['dpad_param'], bytes(4))
        self.assertEqual(pad.writes(), [])

    def test_data_aimed_at_a_different_button_is_refused(self):
        pad = FakePad()
        a = nova.BLOCKS[f'key_mapping/00/{sn.KEYS["CRO"]:02x}']
        b_data = nova.read_block(pad, nova.BLOCKS[f'key_mapping/00/{sn.KEYS["CIR"]:02x}'])
        with self.assertRaises(nova.PadError):
            nova.write_block(pad, a, b_data)
        self.assertEqual(pad.writes(), [])

    def test_an_unchanged_block_is_not_written(self):
        pad = FakePad()
        block = nova.BLOCKS['light_param']
        nova.write_block(pad, block, nova.read_block(pad, block))
        self.assertEqual(pad.writes(), [])


class RestoreTests(unittest.TestCase):
    def test_restore_undoes_a_change_and_verifies_zero_diff(self):
        pad = FakePad()
        backup = nova.snapshot(pad)
        block = nova.BLOCKS[f'key_mapping/00/{sn.KEYS["CRO"]:02x}']
        nova.write_block(pad, block, sn.with_key_target(nova.read_block(pad, block),
                                                        sn.KEYS['CIR']))
        nova.save(pad)
        self.assertTrue(nova.diff(backup, nova.snapshot(pad)))
        written, skipped, remaining = nova.restore(pad, backup)
        self.assertEqual(written, [block.key])
        self.assertEqual((skipped, remaining), ([], {}))

    def test_restoring_an_identical_backup_writes_nothing(self):
        pad = FakePad()
        backup = nova.snapshot(pad)
        written, _, remaining = nova.restore(pad, backup)
        self.assertEqual((written, remaining), ([], {}))
        self.assertEqual(pad.writes(), [])

    def test_unrestorable_differences_are_reported_not_written(self):
        pad = FakePad()
        backup = nova.snapshot(pad)
        backup['blocks']['dpad_param'] = '01000100'
        written, skipped, remaining = nova.restore(pad, backup)
        self.assertEqual((written, skipped), ([], ['dpad_param']))
        self.assertIn('dpad_param', remaining)

    def test_a_foreign_file_is_refused(self):
        with self.assertRaises(nova.PadError):
            nova.restore_plan({'blocks': {}}, {'format': 'something else', 'blocks': {}})


class RetryTests(unittest.TestCase):
    def _link(self, outcomes):
        link = transport.SuperNovaLink.__new__(transport.SuperNovaLink)
        link.log, link.calls = None, []

        def once(name, payload):
            link.calls.append(name)
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        link._request_once = once
        return link

    def test_a_dropped_read_reply_is_resent(self):
        # The Linux run's one failure: no reply to a re-read right after a save.
        link = self._link([TimeoutError('dropped'), b'\x00' * 16])
        self.assertEqual(link.request('get_key_mapping', b'\x00\x01'), b'\x00' * 16)
        self.assertEqual(link.calls, ['get_key_mapping'] * 2)

    def test_a_read_that_never_answers_still_fails(self):
        link = self._link([TimeoutError()] * (1 + transport.READ_RETRIES))
        with self.assertRaises(TimeoutError):
            link.request('get_vibrate_param')

    def test_a_write_is_never_resent(self):
        link = self._link([TimeoutError('dropped'), b'\x00'])
        with self.assertRaises(TimeoutError):
            link.request('set_vibrate_param', bytes(6))
        self.assertEqual(link.calls, ['set_vibrate_param'])


class DescriptorTests(unittest.TestCase):
    def test_the_vendor_page_is_found_among_the_other_collections(self):
        desc = bytes.fromhex('05010906a101850105078101c0'      # keyboard collection
                             '06a0ff0901a101850609018140c0')  # vendor 0xffa0
        self.assertTrue(transport.declares_usage_page(desc, 0xFFA0))
        self.assertFalse(transport.declares_usage_page(desc, 0xFFF0))


if __name__ == '__main__':
    unittest.main()
