"""Timing uses kernel packets and timestamps, independently of GUI refresh."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_state import state
import report_timing as timing


class TimingTests(unittest.TestCase):
    def capture(self, data):
        clock = [1_000_000_000]
        test = timing.TimingTest()

        def read(*args):
            clock[0] = 11_000_000_000
            return data

        with patch.dict(state, selected='test', connected=True, demo=False), \
             patch.object(timing, '_open_node', return_value=(7, '/dev/input/test')), \
             patch.object(timing.time, 'monotonic_ns', side_effect=lambda: clock[0]), \
             patch.object(timing.select, 'select', return_value=([7], [], [])), \
             patch.object(timing.os, 'read', side_effect=read), \
             patch.object(timing.os, 'close') as close:
            test._run('test')
            close.assert_called_once_with(7)
        return test.snapshot()

    def test_one_sample_per_changed_packet_uses_kernel_time_despite_batched_delivery(self):
        data = b''.join(timing._EVENT.pack(1 + i // 10, i % 10 * 100_000, kind, code, value)
                        for i in range(100)
                        for kind, code, value in ((3, 0, i), (3, 1, i), (0, 0, 0)))
        result = self.capture(data)
        self.assertFalse(result['running'])
        self.assertEqual((result['samples'], result['hz']), (100, 10))
        self.assertEqual((result['median'], result['p95'], result['maximum']), (100, 100, 100))
        self.assertEqual(result['jitter'], 0)

    def test_jitter_and_gap_statistics(self):
        result = timing.summarize([0, 2_000_000, 4_000_000, 20_000_000])
        self.assertEqual((result['hz'], result['median'], result['p95'], result['maximum']), (150, 2, 16, 16))
        self.assertGreater(result['jitter'], 0)
        self.assertLessEqual(len(timing.summarize([i * 1000 for i in range(10000)])['trace']), 200)

    def test_kernel_overflow_and_sparse_motion_do_not_produce_a_rate(self):
        for data in (timing._EVENT.pack(1, 0, 0, 3, 0),
                     b''.join(timing._EVENT.pack(1, i * 1000, kind, code, value)
                              for i in range(5) for kind, code, value in ((3, 0, i), (0, 0, 0)))):
            result = self.capture(data)
            self.assertNotIn('hz', result)
            self.assertFalse(result['running'])
            self.assertTrue(result['message'])


if __name__ == '__main__':
    unittest.main()
