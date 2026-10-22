"""One interface over the two Python HID libraries that both install as `hid`.

Deadband is written against **cython-hidapi** (PyPI `hidapi`, Arch
`python-hidapi`): ``hid.device()`` + ``open_path()``, ``read()`` returning a list
of ints, ``set_nonblocking()``.

**pyhidapi** (PyPI `hid`, Arch `python-hid`) is a different, ctypes-based library
with a different API -- ``hid.Device(path=...)``, ``read()`` returning bytes, a
``nonblocking`` property, ``HIDException`` -- and it ALSO installs as ``import
hid``. The two conflict at the package level, and SteamOS ships pyhidapi because
``jupiter-hw-support`` (the Steam Deck's own hardware support) depends on it. So
on a Steam Deck the cython one cannot be installed without removing the Deck's
hardware support, and building it from source needs a compiler and headers that
SteamOS doesn't have (issues #13, #19).

Rather than fight that, the app imports this module instead of ``hid``. When
cython-hidapi is installed it is passed straight through, untouched. When only
pyhidapi is, a thin adapter gives it the cython-hidapi shape. pyhidapi loads the
system ``libhidapi-hidraw`` first, so it gets the hidraw backend the app needs.
"""
import gc as _gc

try:
    # cython-hidapi built with BOTH backends (some distro packages) installs the
    # hidraw one as `hidraw` and keeps `hid` for libusb, which can't open
    # /dev/hidraw paths -- so prefer `hidraw` when it's there (#36, thanks
    # @Barracuda72). Same API as `hid`; absent on single-backend builds.
    import hidraw as _hid
except ImportError:
    import hid as _hid

if hasattr(_hid, 'device'):
    # cython-hidapi: the API the app is written against. Disable atexit on its
    # internal weakref.finalize so interpreter shutdown never calls hid_close()
    # on the main thread while a daemon reader thread is inside hid_read_timeout().
    IMPL = 'hidapi (cython)'
    enumerate = _hid.enumerate
    __version__ = getattr(_hid, '__version__', '?')

    class device(_hid.device):
        def open_path(self, path):
            super().open_path(path)
            for ref in _gc.get_referents(self):
                if hasattr(ref, 'atexit'):
                    ref.atexit = False

        def open(self, vendor_id=0, product_id=0, serial_number=None):
            super().open(vendor_id, product_id, serial_number)
            for ref in _gc.get_referents(self):
                if hasattr(ref, 'atexit'):
                    ref.atexit = False

else:
    IMPL = 'python-hid (ctypes)'
    __version__ = getattr(_hid, '__version__', '?')

    def enumerate(vendor_id=0, product_id=0):
        # Same dict keys as cython-hidapi (path, vendor_id, product_id,
        # usage_page, interface_number, ...), and path is bytes in both.
        return _hid.enumerate(vendor_id, product_id)

    class device:
        """cython-hidapi's ``hid.device`` interface over a pyhidapi Device.

        Errors are raised as OSError, as cython-hidapi does, so callers that
        catch OSError (or Exception) behave the same on either library."""

        def __init__(self):
            self._d = None
            self._nonblocking = False

        def _opened(self, **kw):
            try:
                self._d = _hid.Device(**kw)
            except _hid.HIDException as e:
                raise OSError(str(e) or 'open failed') from e
            if self._nonblocking:
                self._d.nonblocking = True

        def open_path(self, path):
            if isinstance(path, str):
                path = path.encode()
            self._opened(path=path)

        def open(self, vendor_id=0, product_id=0, serial_number=None):
            self._opened(vid=vendor_id, pid=product_id, serial=serial_number)

        def set_nonblocking(self, v):
            self._nonblocking = bool(v)
            if self._d is not None:
                self._d.nonblocking = bool(v)
            return 0

        def read(self, max_length, timeout_ms=0):
            # cython-hidapi: timeout_ms == 0 means plain hid_read (which honours
            # the non-blocking flag); otherwise hid_read_timeout. pyhidapi maps
            # timeout=None to hid_read the same way.
            try:
                data = self._d.read(max_length, timeout_ms if timeout_ms else None)
            except _hid.HIDException as e:
                raise OSError(str(e) or 'read error') from e
            return list(data or b'')        # cython-hidapi returns a list of ints

        def write(self, buff):
            try:
                return self._d.write(bytes(bytearray(buff)))
            except _hid.HIDException as e:
                raise OSError(str(e) or 'write error') from e

        def get_feature_report(self, report_id, max_length):
            try:
                return list(self._d.get_feature_report(report_id, max_length))
            except _hid.HIDException as e:
                raise OSError(str(e) or 'get_feature_report error') from e

        def send_feature_report(self, buff):
            try:
                return self._d.send_feature_report(bytes(bytearray(buff)))
            except _hid.HIDException as e:
                raise OSError(str(e) or 'send_feature_report error') from e

        def get_product_string(self):
            return self._d.product

        def get_manufacturer_string(self):
            return self._d.manufacturer

        def get_serial_number_string(self):
            return self._d.serial

        def close(self):
            if self._d is not None:
                try:
                    self._d.close()
                finally:
                    self._d = None
