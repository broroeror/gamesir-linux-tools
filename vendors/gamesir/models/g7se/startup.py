"""Selected-device startup: warm read probe, or fresh GIP authentication.

No persistent settings writes. Only interrupt endpoints 02/82 are needed.
The caller owns the handle and releases it, including on startup failure.
"""
from pathlib import Path
import time

from . import auth, gip, protocol as se


class Startup:
    def __init__(self, handle, bus, address, sysfs, active=lambda: True, log=None):
        self.handle = handle
        self.root = Path(sysfs).resolve()
        self.bus, self.address = bus, address
        self.active = active
        self.log = [] if log is None else log
        self.sequence = 0
        self.deadline = time.monotonic() + 25
        self.identity = self._identity()
        if (self.identity['idVendor'], self.identity['idProduct'],
                self.identity['bcdDevice'], int(self.identity['busnum']),
                int(self.identity['devnum'])) != ('3537', '1010', '0630', bus, address):
            raise OSError('G7 SE startup device identity does not match selection')

    def _identity(self):
        names = ('idVendor', 'idProduct', 'bcdDevice', 'busnum', 'devnum', 'serial')
        return {name: (self.root/name).read_text().strip()
                for name in names if name != 'serial' or (self.root/name).exists()}

    def check_identity(self):
        if self._identity() != self.identity:
            raise OSError('Selected G7 SE USB session changed')

    def check(self):
        self.check_identity()
        if not self.active():
            raise OSError('G7 SE configuration selection changed or was released')
        if time.monotonic() >= self.deadline:
            raise OSError('G7 SE startup time budget exhausted')

    def receive(self, handle, log, match, seconds=2):
        deadline = min(self.deadline, time.monotonic() + seconds)
        for _ in range(4096):
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            reply = handle.read(64, timeout_ms=min(100, max(1, int(remaining*1000))))
            if reply:
                value = match(reply)
                log.append({'response': bytes(reply).hex(), 'matched': value is not None,
                            'interface': 0})
                if value is not None:
                    return value
        raise OSError('G7 SE startup input packet budget exhausted')

    def read_probe(self, exchange):
        values = []
        for _ in range(2):
            sequence = exchange.next_sequence()
            request = se.nexus_request(sequence, 5, bytes((4, 1, 0, 0, 55)))
            exchange.raw(request, 'startup-profile-read')
            value = self.receive(self.handle, self.log, lambda reply:
                se.match_read(reply, 1, 0, 55) if len(reply) > 2
                and reply[2] == sequence else None, seconds=.6)
            if value is None:
                return False
            values.append(value)
        return values[0] == values[1]

    def run(self):
        exchange = auth.Exchange(self, self.handle, self.log)
        # Reopening a successfully authenticated connection needs no new
        # handshake. Trying HostHello in an existing session can be rejected.
        if self.read_probe(exchange):
            return {'already_ready': True}
        sequence = exchange.next_sequence()
        exchange.raw(gip.identify(sequence), 'startup-identification')
        transfer = gip.IdentificationTransfer(expected_sequence=sequence)
        def match(reply):
            if reply[0] != 4:
                return None
            value, ack = transfer.accept(reply)
            if ack is not None:
                exchange.raw(ack, 'validated-identification-ack')
            return value
        if self.receive(self.handle, self.log, match, seconds=4) is None:
            raise OSError('G7 SE identification timed out')
        exchange.raw(se.gip_power_on(exchange.next_sequence()), 'startup-input-power')
        result = exchange.run()
        if not self.read_probe(exchange):
            raise OSError('G7 SE profile replies unavailable after verified authentication')
        return result

    def restore_input(self):
        # Release is allowed even when active() is false; still pin the USB
        # identity so cleanup cannot initialize a replacement controller.
        self.check_identity()
        wire = se.gip_power_on(self.sequence % 255 + 1)
        if self.handle.write(wire) != len(wire):
            raise OSError('Short G7 SE input restoration transfer')
