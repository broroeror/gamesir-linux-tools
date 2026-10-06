"""Recovery files from Continuous Trigger saves are capped (follow-up to #22)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import register_transaction as rt  # noqa: E402


class PruneTests(unittest.TestCase):
    def test_keeps_newest_and_only_touches_its_own_files(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(25):
                f = os.path.join(d, f'cyclone2_before_apply_{i:02d}.json')
                open(f, 'w').close()
                os.utime(f, (time.time() + i, time.time() + i))
            other = os.path.join(d, 'my_backup.json'); open(other, 'w').close()
            rt.prune(d, keep=20)
            left = sorted(f for f in os.listdir(d) if f.startswith('cyclone2_'))
            self.assertEqual(len(left), 20)
            self.assertEqual(left[0], 'cyclone2_before_apply_05.json')   # oldest 5 gone
            self.assertTrue(os.path.exists(other))

    def test_failed_apply_never_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(25):
                open(os.path.join(d, f'cyclone2_before_apply_{i:02d}.json'), 'w').close()
            ok, _msg = rt.apply([(1, 0x00b6, [1])], read=lambda b, a, n: [0] * n,
                                write=lambda b, a, data: False, directory=d, device='test')
            self.assertFalse(ok)
            self.assertEqual(len([f for f in os.listdir(d) if 'before_apply_' in f]), 26)

    def test_successful_apply_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(25):
                open(os.path.join(d, f'cyclone2_before_apply_{i:02d}.json'), 'w').close()
            store = {}
            ok, _msg = rt.apply([(1, 0x00b6, [1])],
                                read=lambda b, a, n: store.get((b, a), [0] * n),
                                write=lambda b, a, data: store.__setitem__((b, a), list(data)) or True,
                                directory=d, device='test')
            self.assertTrue(ok)
            self.assertEqual(len([f for f in os.listdir(d) if 'before_apply_' in f]), 20)


if __name__ == '__main__':
    unittest.main()


class PollRateReconnectTests(unittest.TestCase):
    """The 8K and Tarantula re-enumerate when their poll rate changes. Once the
    save path became the single path for those pads, a poll-rate write followed
    by a read-back would see the pad vanish and 'roll back' a change that had
    landed. Poll rate is written last and never read back."""

    def test_poll_rate_written_last_and_never_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            store, order, gone = {}, [], [False]

            def read(b, a, n):
                if gone[0]:
                    raise OSError('device session changed')     # pad reconnecting
                return store.get((b, a), [0] * n)

            def write(b, a, data):
                if gone[0]:
                    return False
                order.append(a); store[(b, a)] = list(data)
                if a == 0x002e:
                    gone[0] = True                               # re-enumerates now
                return True

            ok, msg = rt.apply([(1, 0x002e, [5]), (1, 0x007a, [1, 0x0a])], read, write,
                               d, 'test', unverified={(1, 0x002e)})
            self.assertTrue(ok, msg)
            self.assertEqual(order, [0x007a, 0x002e], 'poll rate must be written last')
            self.assertIn('1/1 confirmed', msg)
            self.assertIn('reconnecting', msg)
