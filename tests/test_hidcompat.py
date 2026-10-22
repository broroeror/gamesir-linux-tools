"""hidcompat picks the hidraw-backed module when a distro ships both (#36)."""
import importlib
import sys
import types
import unittest
import weakref


class HidcompatTests(unittest.TestCase):
    def _load(self, modules):
        saved = {k: sys.modules.get(k) for k in ('hid', 'hidraw', 'hidcompat')}
        try:
            for k in ('hid', 'hidraw', 'hidcompat'):
                sys.modules.pop(k, None)
            sys.modules.update(modules)
            return importlib.import_module('hidcompat')
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    @staticmethod
    def _fake(name):
        m = types.ModuleType(name)
        m.device = object
        m.enumerate = lambda *a: [{'path': name.encode()}]
        return m

    def test_prefers_the_hidraw_module_when_both_exist(self):
        hc = self._load({'hid': self._fake('hid'), 'hidraw': self._fake('hidraw')})
        self.assertEqual(hc.enumerate()[0]['path'], b'hidraw')

    def test_uses_hid_when_there_is_no_hidraw_module(self):
        hc = self._load({'hid': self._fake('hid'), 'hidraw': None})
        self.assertEqual(hc.enumerate()[0]['path'], b'hid')

    def test_open_disables_shutdown_finalizer_but_preserves_explicit_close(self):
        closed = []

        class Device:
            __slots__ = ('finalizer', '__weakref__')

            def open_path(self, path):
                self.finalizer = weakref.finalize(self, closed.append, path)

            def open(self, vendor_id, product_id, serial_number):
                self.finalizer = weakref.finalize(self, closed.append, serial_number)

            def close(self):
                self.finalizer()

        module = self._fake('hid')
        module.device = Device
        hc = self._load({'hid': module, 'hidraw': None})
        for method, args, label in (('open_path', (b'/test/hidraw',), b'/test/hidraw'),
                                    ('open', (0x3537, 0x100f, 'serial'), 'serial')):
            with self.subTest(method=method):
                dev = hc.device()
                getattr(dev, method)(*args)
                self.assertFalse(dev.finalizer.atexit)
                self.assertTrue(dev.finalizer.alive)
                dev.close()
                self.assertEqual(closed[-1], label)
                self.assertFalse(dev.finalizer.alive)


if __name__ == '__main__':
    unittest.main()
