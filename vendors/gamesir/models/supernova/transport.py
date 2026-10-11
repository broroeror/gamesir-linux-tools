"""Super Nova HID transport over Linux hidraw (no hidapi needed).

Requests go out as 32-byte output reports (report id 0x07) and replies come
back as 64-byte input reports (0x06) on the pad's HID interface 1 -- the one
whose report descriptor declares vendor usage page 0xffa0. That interface also
carries the keyboard/mouse/consumer collections, but hidraw exposes one node
per interface, so this is a single /dev/hidrawN.
"""

import glob
import os
import select
import time

from vendors.gamesir.models.supernova import protocol as sn

OUT_REPORT_LEN = 32
REPLY_TIMEOUT = 1.0
# A read is resent this many times if its reply goes missing. Reads change
# nothing, so a resend is harmless; writes are never resent (a timed-out write
# is reported, and write_block's read-back decides what actually happened).
# Seen once on Linux: the re-read straight after a save_config_page got no
# reply, and every read after it was fine.
READ_RETRIES = 2


def declares_usage_page(desc, page):
    """Does a HID report descriptor declare `page` as a Usage Page?"""
    i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:                              # long item
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        size = (b & 0x03) if (b & 0x03) != 3 else 4
        if (b & 0xFC) == 0x04 and int.from_bytes(desc[i + 1:i + 1 + size], 'little') == page:
            return True
        i += 1 + size
    return False


def config_node(nodes):
    """Of one device's /dev/hidrawN nodes, the one carrying the config channel
    (its report descriptor declares the 0xffa0 vendor page), else None."""
    for node in nodes:
        sysfs = os.path.join('/sys/class/hidraw', os.path.basename(node),
                             'device', 'report_descriptor')
        try:
            with open(sysfs, 'rb') as f:
                if declares_usage_page(f.read(), sn.LIVE_USAGE_PAGE):
                    return node
        except OSError:
            continue
    return None


def find_nodes():
    """[(hidraw node, pid)] for every Super Nova identity's config channel."""
    out = []
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
            with open(os.path.join(path, 'device', 'report_descriptor'), 'rb') as f:
                desc = f.read()
        except OSError:
            continue
        hid_id = next((ln.split('=', 1)[1] for ln in uevent.splitlines()
                       if ln.startswith('HID_ID=')), '')
        parts = hid_id.split(':')
        if len(parts) != 3:
            continue
        try:
            vid, pid = int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            continue
        if vid == sn.VID and pid in sn.ALL_PIDS and declares_usage_page(desc, sn.LIVE_USAGE_PAGE):
            out.append(('/dev/' + os.path.basename(path), pid))
    return out


class SuperNovaLink:
    """One open config channel. request() sends a command and returns the
    matching reply body, skipping notifications and stale replies."""

    def __init__(self, node, log=None):
        self.node = node
        self.log = log
        self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _drain(self):
        while select.select([self.fd], [], [], 0)[0]:
            try:
                os.read(self.fd, 64)
            except BlockingIOError:
                return

    def request(self, name, payload=b''):
        tries = 1 + (READ_RETRIES if name in sn.READ_ONLY else 0)
        for attempt in range(tries):
            try:
                return self._request_once(name, payload)
            except TimeoutError:
                if attempt + 1 == tries:
                    raise
                if self.log:
                    self.log(f'   no reply to {name}; resending (read only)')

    def _request_once(self, name, payload):
        group, op = sn.COMMANDS[name]
        frame = sn.encode_request(group, op, payload)     # refuses FORBIDDEN
        self._drain()
        os.write(self.fd, frame.ljust(OUT_REPORT_LEN, b'\0'))
        if self.log:
            self.log(f'-> {name:28} {frame.hex(" ")}')
        deadline = time.monotonic() + REPLY_TIMEOUT
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f'no reply to {name} within {REPLY_TIMEOUT}s')
            if not select.select([self.fd], [], [], left)[0]:
                continue
            try:
                report = os.read(self.fd, 64)
            except BlockingIOError:
                continue
            reply = sn.decode_reply(report)
            if reply and reply[:2] == (group, op):
                if self.log:
                    self.log(f'<- {name:28} {report[:1 + report[1]].hex(" ")}')
                return reply[2]
