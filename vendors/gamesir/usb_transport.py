"""Native interrupt transport for non-HID GameSir USB interfaces.

Most controllers in Deadband expose hidraw and are opened through hidapi. Some
vendor-class interfaces (currently the G7 Pro's configuration interfaces) have
interrupt endpoints but deliberately do not expose a hidraw node. This module
gives those devices the same ``write/read/close`` handle shape as hidapi.

The binding calls the system libusb-1.0 runtime through Python's standard
``ctypes`` module. It does not use or depend on PyUSB.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import threading


BACKEND = 'native libusb-1.0 (no Python USB package)'


class UsbTransportError(OSError):
    """A libusb load, discovery, claim, or transfer failure."""


class _DeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ('bLength', ctypes.c_uint8), ('bDescriptorType', ctypes.c_uint8),
        ('bcdUSB', ctypes.c_uint16), ('bDeviceClass', ctypes.c_uint8),
        ('bDeviceSubClass', ctypes.c_uint8), ('bDeviceProtocol', ctypes.c_uint8),
        ('bMaxPacketSize0', ctypes.c_uint8), ('idVendor', ctypes.c_uint16),
        ('idProduct', ctypes.c_uint16), ('bcdDevice', ctypes.c_uint16),
        ('iManufacturer', ctypes.c_uint8), ('iProduct', ctypes.c_uint8),
        ('iSerialNumber', ctypes.c_uint8), ('bNumConfigurations', ctypes.c_uint8),
    ]


class _Version(ctypes.Structure):
    _fields_ = [
        ('major', ctypes.c_uint16), ('minor', ctypes.c_uint16),
        ('micro', ctypes.c_uint16), ('nano', ctypes.c_uint16),
        ('rc', ctypes.c_char_p), ('describe', ctypes.c_char_p),
    ]


_device_ptr = ctypes.c_void_p
_device_list_ptr = ctypes.POINTER(_device_ptr)
_handle_ptr = ctypes.c_void_p
_ERROR_TIMEOUT = -7
_ERRNO_BY_LIBUSB = {
    -3: errno.EACCES,   # LIBUSB_ERROR_ACCESS
    -4: errno.ENODEV,   # LIBUSB_ERROR_NO_DEVICE
    -6: errno.EBUSY,    # LIBUSB_ERROR_BUSY
}
_lib = None
_lib_lock = threading.Lock()


def _configure(lib):
    lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.libusb_init.restype = ctypes.c_int
    lib.libusb_exit.argtypes = [ctypes.c_void_p]
    lib.libusb_get_device_list.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(_device_list_ptr)]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_free_device_list.argtypes = [_device_list_ptr, ctypes.c_int]
    lib.libusb_get_bus_number.argtypes = [_device_ptr]
    lib.libusb_get_bus_number.restype = ctypes.c_uint8
    lib.libusb_get_device_address.argtypes = [_device_ptr]
    lib.libusb_get_device_address.restype = ctypes.c_uint8
    lib.libusb_get_device_descriptor.argtypes = [
        _device_ptr, ctypes.POINTER(_DeviceDescriptor)]
    lib.libusb_get_device_descriptor.restype = ctypes.c_int
    lib.libusb_open.argtypes = [_device_ptr, ctypes.POINTER(_handle_ptr)]
    lib.libusb_open.restype = ctypes.c_int
    lib.libusb_close.argtypes = [_handle_ptr]
    lib.libusb_kernel_driver_active.argtypes = [_handle_ptr, ctypes.c_int]
    lib.libusb_kernel_driver_active.restype = ctypes.c_int
    lib.libusb_detach_kernel_driver.argtypes = [_handle_ptr, ctypes.c_int]
    lib.libusb_detach_kernel_driver.restype = ctypes.c_int
    lib.libusb_attach_kernel_driver.argtypes = [_handle_ptr, ctypes.c_int]
    lib.libusb_attach_kernel_driver.restype = ctypes.c_int
    lib.libusb_claim_interface.argtypes = [_handle_ptr, ctypes.c_int]
    lib.libusb_claim_interface.restype = ctypes.c_int
    lib.libusb_release_interface.argtypes = [_handle_ptr, ctypes.c_int]
    lib.libusb_release_interface.restype = ctypes.c_int
    lib.libusb_interrupt_transfer.argtypes = [
        _handle_ptr, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
    ]
    lib.libusb_interrupt_transfer.restype = ctypes.c_int
    lib.libusb_error_name.argtypes = [ctypes.c_int]
    lib.libusb_error_name.restype = ctypes.c_char_p
    lib.libusb_get_version.restype = ctypes.POINTER(_Version)


def _library():
    global _lib
    with _lib_lock:
        if _lib is None:
            name = ctypes.util.find_library('usb-1.0')
            if not name:
                raise UsbTransportError(
                    'libusb-1.0 is not installed (the system runtime is required)')
            try:
                _lib = ctypes.CDLL(name)
                _configure(_lib)
            except (OSError, AttributeError) as exc:
                _lib = None
                raise UsbTransportError(f'could not load libusb-1.0: {exc}') from exc
        return _lib


def library_version():
    """Loaded system libusb version, or ``None`` when unavailable."""
    try:
        version = _library().libusb_get_version().contents
    except (UsbTransportError, ValueError):
        return None
    return '.'.join(str(value) for value in
                    (version.major, version.minor, version.micro, version.nano))


def _check(lib, result, action):
    if result < 0:
        raw = lib.libusb_error_name(result)
        name = raw.decode('ascii', 'replace') if raw else f'error {result}'
        mapped = _ERRNO_BY_LIBUSB.get(result)
        if mapped is not None:
            raise UsbTransportError(mapped, f'{action}: {name}')
        raise UsbTransportError(f'{action}: {name}')
    return result


def _read_number(path, base=10):
    with open(path, encoding='ascii') as stream:
        return int(stream.read().strip(), base)


def _validate_identity(sysfs, vendor, products, bus, address):
    """Confirm that bus/address still names the sysfs device we enumerated."""
    real = os.path.realpath(sysfs)
    try:
        actual = (
            _read_number(os.path.join(real, 'idVendor'), 16),
            _read_number(os.path.join(real, 'idProduct'), 16),
            _read_number(os.path.join(real, 'busnum')),
            _read_number(os.path.join(real, 'devnum')),
        )
    except (OSError, ValueError) as exc:
        raise UsbTransportError('USB device disappeared before it could be opened') from exc
    if actual[0] != int(vendor) or actual[1] not in products \
            or actual[2:] != (int(bus), int(address)):
        raise UsbTransportError('USB device changed identity before it could be opened')


class InterruptHandle:
    """Claimed interrupt interface with a hidapi-compatible handle surface."""

    def __init__(self, lib, context, handle, interface, ep_out, ep_in):
        self._lib = lib
        self._context = context
        self._handle = handle
        self._interface = int(interface)
        self._ep_out = int(ep_out)
        self._ep_in = int(ep_in)
        self._detached = False
        self._claimed = False
        self._closed = False
        self._io_lock = threading.RLock()

    @classmethod
    def open(cls, vendor, products, bus, address, sysfs, interface, ep_out, ep_in):
        """Open one exact bus/address after confirming its VID/PID identity."""
        _validate_identity(sysfs, vendor, products, bus, address)
        lib = _library()
        context = ctypes.c_void_p()
        _check(lib, lib.libusb_init(ctypes.byref(context)), 'initialise libusb')
        devices = _device_list_ptr()
        handle = _handle_ptr()
        try:
            count = _check(lib, lib.libusb_get_device_list(
                context, ctypes.byref(devices)), 'enumerate USB devices')
            try:
                match = None
                for index in range(count):
                    dev = devices[index]
                    if (lib.libusb_get_bus_number(dev) != int(bus)
                            or lib.libusb_get_device_address(dev) != int(address)):
                        continue
                    descriptor = _DeviceDescriptor()
                    _check(lib, lib.libusb_get_device_descriptor(
                        dev, ctypes.byref(descriptor)), 'read USB descriptor')
                    if (descriptor.idVendor == int(vendor)
                            and descriptor.idProduct in products):
                        match = dev
                        break
                if match is None:
                    raise UsbTransportError('USB device disappeared or changed identity')
                _check(lib, lib.libusb_open(match, ctypes.byref(handle)),
                       'open USB device')
            finally:
                lib.libusb_free_device_list(devices, 1)

            obj = cls(lib, context, handle, interface, ep_out, ep_in)
            try:
                obj._claim()
            except Exception:
                obj.close()
                handle = _handle_ptr()
                context = ctypes.c_void_p()
                raise
            return obj
        except Exception:
            if handle:
                lib.libusb_close(handle)
            if context:
                lib.libusb_exit(context)
            raise

    def _claim(self):
        active = self._lib.libusb_kernel_driver_active(
            self._handle, self._interface)
        _check(self._lib, active, 'check kernel USB driver')
        if active == 1:
            _check(self._lib, self._lib.libusb_detach_kernel_driver(
                self._handle, self._interface), 'detach kernel USB driver')
            self._detached = True
        _check(self._lib, self._lib.libusb_claim_interface(
            self._handle, self._interface), 'claim USB interface')
        self._claimed = True

    def write(self, data):
        payload = bytes(data)
        if not payload:
            return 0
        buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        transferred = ctypes.c_int()
        with self._io_lock:
            if self._closed:
                raise UsbTransportError('USB interface is closed')
            result = self._lib.libusb_interrupt_transfer(
                self._handle, self._ep_out, buffer, len(payload),
                ctypes.byref(transferred), 1000)
            _check(self._lib, result, 'USB interrupt write')
            return transferred.value

    def read(self, length=64, timeout_ms=200):
        size = int(length)
        if size <= 0:
            return b''
        buffer = (ctypes.c_ubyte * size)()
        transferred = ctypes.c_int()
        with self._io_lock:
            if self._closed:
                raise UsbTransportError('USB interface is closed')
            result = self._lib.libusb_interrupt_transfer(
                self._handle, self._ep_in, buffer, size,
                ctypes.byref(transferred), max(1, int(timeout_ms)))
            if result == _ERROR_TIMEOUT:
                return b''
            _check(self._lib, result, 'USB interrupt read')
            return bytes(buffer[:transferred.value])

    def close(self):
        with self._io_lock:
            if self._closed:
                return
            self._closed = True
            if self._claimed:
                self._lib.libusb_release_interface(
                    self._handle, self._interface)
                self._claimed = False
            if self._detached:
                self._lib.libusb_attach_kernel_driver(
                    self._handle, self._interface)
                self._detached = False
            if self._handle:
                self._lib.libusb_close(self._handle)
                self._handle = None
            if self._context:
                self._lib.libusb_exit(self._context)
                self._context = None
