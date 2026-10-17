#!/usr/bin/env python3
"""G7 SE 6.64 (3537:1069): do plain short-form writes land byte-exact?

Each test, on bank 3 only: snapshot the whole bank -> one plain write
(0f 00 seq 3c 03 bank hi lo len data) -> re-read the whole bank and diff ->
write the original bytes back -> re-read and compare with the snapshot.
The snapshot is saved to the --output JSON before anything is written.
Deadband must be closed (it claims the same interface).
Usage: python3 -I write_test_664.py --output FILE [--only NAME]
"""
import argparse, json, sys, time
from pathlib import Path

REPO = '/home/herbert/src/gamesir-linux-tools'
sys.path.insert(0, REPO)
from vendors.gamesir.models.g7se import protocol as se  # noqa: E402
se.select(0x0664)
from tools.g7se_probe import ProbeHandle  # noqa: E402
from vendors.gamesir.models.g7se.startup import Startup  # noqa: E402

BANK = 3
TESTS = [  # name, address, new bytes (the original is read from the pad)
    ('ls_deadzone_min', 0x013f, [20]),
    ('vibration_left', 0x0020, [50]),
    ('ls_sensitivity', 0x0153, [60]),
    ('ls_invert_y', 0x0152, [1]),
    ('lt_deadzone_min', 0x00cf, [15]),
    ('ls_curve_block', 0x0144, [0, 100, 0, 0, 0x39, 0x40, 0x80, 0x80, 0xc6, 0xbf]),
]


def find_sysfs():
    for dev in Path('/sys/bus/usb/devices').iterdir():
        try:
            if ((dev / 'idVendor').read_text().strip(), (dev / 'idProduct').read_text().strip()) \
                    == ('3537', '1069'):
                return dev.resolve()
        except OSError:
            continue
    sys.exit('G7 SE 3537:1069 not found (boot with the pad plugged in at the F12 menu)')


class Pad:
    def __init__(self, root, log):
        self.root, self.log, self.seq = root, log, 0
        bus, addr = int((root / 'busnum').read_text()), int((root / 'devnum').read_text())
        self.h = ProbeHandle.open(se.VID, (se.PID,), bus, addr, str(root), 0, 2, 0x82)
        st = Startup(self.h, bus, addr, root, log=log)
        log.append({'startup': st.run()})
        self.startup = st

    def _send(self, wire):
        if self.h.write(wire) != len(wire):
            raise OSError('short transfer')
        self.log.append({'out': wire.hex()})

    def heartbeat(self):
        self.seq = self.seq % 255 + 1
        self._send(se.nexus_request(self.seq, 2, b'\xf2\x00'))

    def read(self, bank, address, length):
        for attempt in range(3):
            self.seq = self.seq % 255 + 1
            self._send(se.nexus_request(self.seq, 5, bytes((4, bank, address >> 8,
                                                             address & 0xff, length))))
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                r = self.h.read(64, timeout_ms=100)
                if r:
                    v = se.match_read(r, bank, address, length)
                    if v is not None:
                        return bytes(v)
        raise OSError(f'no reply for read {bank}:{address:#x}+{length}')

    def bank(self, bank):
        return b''.join(self.read(bank, off, ln) for _b, off, ln in se.view_requests(bank))

    def write(self, bank, address, data):
        self.seq = self.seq % 255 + 1
        body = bytes((3, bank)) + address.to_bytes(2, 'big') + bytes((len(data),)) + bytes(data)
        wire = bytes((15, 0, self.seq, 60)) + body.ljust(60, b'\0')
        self._send(wire)
        acks = []
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            r = self.h.read(64, timeout_ms=100)
            if r and r[0] == 0x10 and r[3:5] == b'\x3c\x06':
                acks.append(bytes(r[:16]).hex())
                break
        time.sleep(0.05)
        return acks

    def close(self):
        try:
            self.startup.restore_input()
        finally:
            self.h.close()


def diff(a, b):
    return [f'{i:#05x}: {a[i]:02x}->{b[i]:02x}' for i in range(len(a)) if a[i] != b[i]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--only')
    args = ap.parse_args()
    out = {'bank': BANK, 'tests': [], 'log': []}
    pad = Pad(find_sysfs(), out['log'])
    try:
        pad.heartbeat()
        snap = pad.bank(BANK)
        out['snapshot'] = snap.hex()
        Path(args.output).write_text(json.dumps(out, indent=1))   # durable before any write
        if pad.bank(BANK) != snap:
            raise OSError('bank 3 reads are not repeatable; nothing written')
        for name, address, new in TESTS:
            if args.only and name != args.only:
                continue
            orig = list(snap[address:address + len(new)])
            t = {'name': name, 'address': hex(address), 'original': bytes(orig).hex(),
                 'written': bytes(new).hex()}
            out['tests'].append(t)
            pad.heartbeat()
            t['ack_write'] = pad.write(BANK, address, new)
            after = pad.bank(BANK)
            t['changed'] = diff(snap, after)
            t['exact'] = (after[address:address + len(new)] == bytes(new)
                          and len(t['changed']) == sum(o != n for o, n in zip(orig, new)))
            t['ack_restore'] = pad.write(BANK, address, orig)
            back = pad.bank(BANK)
            t['restored'] = back == snap
            if not t['restored']:
                t['left_changed'] = diff(snap, back)
                print(f'{name}: NOT RESTORED {t["left_changed"]} — stopping')
                break
            print(f'{name:16} exact={t["exact"]} changed={t["changed"]} restored={t["restored"]}')
    finally:
        try:
            out['final_matches_snapshot'] = pad.bank(BANK).hex() == out.get('snapshot')
        except Exception as exc:
            out['final_error'] = str(exc)
        pad.close()
        Path(args.output).write_text(json.dumps(out, indent=1))
    print('final bank 3 == snapshot:', out.get('final_matches_snapshot'))


if __name__ == '__main__':
    main()
