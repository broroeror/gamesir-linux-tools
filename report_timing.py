"""Observe game-input update spacing on a separate, non-grabbing evdev fd."""
import math
import os
import select
import statistics
import struct
import sys
import threading
import time

from gs_common import parse_devices, evdev_port, VENDOR_VID
from gs_state import state

_EVENT = struct.Struct('llHHi')


def summarize(stamps):
    if len(stamps) < 3 or stamps[-1] <= stamps[0]:
        raise ValueError('Not enough input changes. Rotate a stick continuously and repeat.')
    intervals = [(b - a) / 1_000_000 for a, b in zip(stamps, stamps[1:])]
    ordered = sorted(intervals)
    step = max(1, math.ceil(len(intervals) / 200))
    return dict(hz=(len(stamps) - 1) * 1e9 / (stamps[-1] - stamps[0]),
                median=statistics.median(ordered), p95=ordered[math.ceil(len(ordered) * .95) - 1],
                maximum=ordered[-1], minimum=ordered[0], jitter=statistics.pstdev(intervals),
                trace=[max(intervals[i:i + step]) for i in range(0, len(intervals), step)])


def _open_node(port):
    from fcntl import ioctl
    for device in parse_devices():
        if device['vendor'] != VENDOR_VID:
            continue
        for path in device['events']:
            if evdev_port(path) != port:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError:
                continue
            try:
                # Select the gamepad node with both stick axes, not its keyboard.
                for code in (0, 1):
                    ioctl(fd, (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code), bytearray(24), True)
                ioctl(fd, (1 << 30) | (4 << 16) | (ord('E') << 8) | 0xa0,
                      struct.pack('i', time.CLOCK_MONOTONIC))  # EVIOCSCLOCKID, this fd only
                return fd, path
            except OSError:
                os.close(fd)
    raise OSError('No game-input node found. Release the controller to games, then retry.')


class TimingTest:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._result = dict(running=False, samples=0, elapsed=0, source='', message='')

    def snapshot(self):
        with self._lock:
            return dict(self._result)

    def _update(self, **values):
        with self._lock:
            self._result.update(values)

    def stop(self):
        self._stop.set()

    def start(self, port):
        if self.snapshot()['running']:
            return
        self._stop = threading.Event()
        with self._lock:
            self._result = dict(running=True, samples=0, elapsed=0, source='', message='Opening game input…')
        threading.Thread(target=self._run, args=(port,), daemon=True).start()

    def _run(self, port):
        fd = None
        stamps = []
        try:
            if not sys.platform.startswith('linux') or not port or state.get('demo'):
                raise OSError('This test requires a physical controller and Linux evdev.')
            fd, path = _open_node(port)
            start = time.monotonic_ns()
            deadline = start + 10_000_000_000
            self._update(source=path + ' · game-input changes', message='Rotate a stick continuously for 10 seconds.')
            changed = False
            while not self._stop.is_set() and time.monotonic_ns() < deadline:
                if state.get('selected') != port or not state.get('connected') or state.get('demo'):
                    raise OSError('The selected controller changed or disconnected. Repeat the test.')
                ready, _, _ = select.select([fd], [], [], .1)
                if ready:
                    try:
                        data = os.read(fd, _EVENT.size * 1024)
                    except BlockingIOError:
                        continue
                    if not data:
                        raise OSError('Game-input stream ended. Repeat the test.')
                    for sec, usec, kind, code, value in _EVENT.iter_unpack(data):
                        if kind == 0 and code == 3:  # SYN_DROPPED
                            raise OSError('The kernel dropped input events. Results invalid; repeat.')
                        if kind in (1, 3):  # EV_KEY / EV_ABS
                            changed = True
                        elif kind == 0 and code == 0:  # count one SYN_REPORT, not each axis
                            stamp = sec * 1_000_000_000 + usec * 1000
                            if changed and start <= stamp <= deadline:
                                if stamps and stamp < stamps[-1]:
                                    raise OSError('Input timestamps went backwards. Results invalid; repeat.')
                                if len(stamps) >= 200_000:
                                    raise OSError('Capture limit reached. Results invalid; repeat.')
                                stamps.append(stamp)
                            changed = False
                self._update(samples=len(stamps), elapsed=min(10, (time.monotonic_ns() - start) / 1e9))
            if self._stop.is_set():
                self._update(message='Stopped. Start again for a complete 10-second test.')
            else:
                if len(stamps) < 3 or stamps[-1] - stamps[0] < 8_000_000_000:
                    raise ValueError('Not enough continuous input. Rotate a stick for the full 10 seconds and repeat.')
                self._update(**summarize(stamps), message='Complete · observed input-update rate, not physical latency.')
        except (OSError, ValueError) as error:
            self._update(message=str(error))
        finally:
            if fd is not None:
                os.close(fd)
            self._update(running=False)
