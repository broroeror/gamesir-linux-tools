#!/usr/bin/env python3
"""Bounded discovery and opt-in remap validation for one G7 SE, descriptor 6.30.

Run with the app closed. Default discovery never writes settings; explicit remap
validation modes preserve originals and verify restoration. Physical preparation
leaves a temporary L4=A/R4=B mapping until --restore-physical-check is run.
No resets, profile switches or dock requests are allowed.
Standard GIP identification/ACK is opt-in.
Bulk support lives here until discovery verifies
that it is needed in the production transport.
"""
import argparse
import ctypes
import datetime
import errno
import json
from pathlib import Path
import sys
import time

# Allow direct execution as `python3 tests/g7se_probe.py` from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vendors.gamesir.models.g7se import protocol as se, gip
from vendors.gamesir.usb_transport import InterruptHandle, UsbTransportError, _check


class ProbeHandle(InterruptHandle):
    """Diagnostic alternate-setting/bulk extension of the native transport."""
    def __init__(self, *args):
        super().__init__(*args)
        self.original_alt = None
        self.restore_alt = False
        self.cleanup = []

    def _claim(self):
        try:
            self._claim_probe()
        except Exception as exc:
            self.close()
            exc.cleanup = self.cleanup
            raise

    def _claim_probe(self):
        # Bind only the extra native operations needed by this probe.
        lib = self._lib
        lib.libusb_bulk_transfer.argtypes = lib.libusb_interrupt_transfer.argtypes
        lib.libusb_bulk_transfer.restype = ctypes.c_int
        lib.libusb_set_interface_alt_setting.argtypes = [ctypes.c_void_p,
                                                       ctypes.c_int, ctypes.c_int]
        lib.libusb_set_interface_alt_setting.restype = ctypes.c_int
        lib.libusb_control_transfer.argtypes = [ctypes.c_void_p, ctypes.c_uint8,
            ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16,
            ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint16, ctypes.c_uint]
        lib.libusb_control_transfer.restype = ctypes.c_int
        super()._claim()
        if self._interface == 2:
            alt = (ctypes.c_ubyte * 1)()
            result = _check(lib, lib.libusb_control_transfer(
                self._handle, 0x81, 0x0a, 0, 2, alt, 1, 1000),
                'GET_INTERFACE before bulk probe')
            if result != 1:
                raise UsbTransportError('GET_INTERFACE returned no alternate setting')
            self.original_alt = alt[0]
            self.restore_alt = True  # even SET_INTERFACE failure needs cleanup
            _check(lib, lib.libusb_set_interface_alt_setting(self._handle, 2, 1),
                   'select bulk alternate setting 1')
            self.transfer_name = 'libusb_bulk_transfer'

    def close(self):
        with self._io_lock:
            if self._closed:
                return
            if self.restore_alt:
                result = self._lib.libusb_set_interface_alt_setting(
                    self._handle, self._interface, self.original_alt)
                self.cleanup.append({'action': 'restore_alt', 'alt': self.original_alt,
                                     'result': result})
                self.restore_alt = False
            # Record cleanup results; do not skip later cleanup after an error.
            if self._claimed:
                result = self._lib.libusb_release_interface(self._handle, self._interface)
                self.cleanup.append({'action': 'release', 'result': result})
                self._claimed = False
            if self._detached:
                result = self._lib.libusb_attach_kernel_driver(self._handle, self._interface)
                self.cleanup.append({'action': 'reattach', 'result': result})
                self._detached = False
            super().close()


def topology(root):
    """Capture descriptors and bound drivers without claiming an interface."""
    root = Path(root).resolve()
    attrs = ('idVendor', 'idProduct', 'bcdDevice', 'busnum', 'devnum', 'devpath',
             'product', 'manufacturer', 'serial', 'bConfigurationValue')
    out = {'sysfs': str(root)}
    for attr in attrs:
        try:
            out[attr] = (root / attr).read_text().strip()
        except OSError:
            pass
    out['descriptors_hex'] = (root / 'descriptors').read_bytes().hex()
    out['interfaces'] = []
    for iface in sorted(root.glob(root.name + ':*')):
        entry = {'name': iface.name, 'driver': None, 'endpoints': []}
        if (iface / 'driver').exists():
            entry['driver'] = (iface / 'driver').resolve().name
        for attr in ('bInterfaceNumber', 'bAlternateSetting', 'bInterfaceClass'):
            entry[attr] = (iface / attr).read_text().strip()
        for ep in sorted(iface.glob('ep_*')):
            entry['endpoints'].append({attr: (ep / attr).read_text().strip()
                for attr in ('bEndpointAddress', 'bmAttributes', 'wMaxPacketSize')})
        out['interfaces'].append(entry)
    return out


class Session:
    def __init__(self, root, evidence):
        self.root = Path(root).resolve()
        self.evidence = evidence
        self.identity = topology(root)
        self.inode = self.root.stat().st_ino
        self.bus = int(self.identity['busnum'])
        self.address = int(self.identity['devnum'])
        self.sequence = 0
        self.started = time.monotonic()

    def check(self):
        if self.root.stat().st_ino != self.inode:
            raise UsbTransportError('Selected USB session was replaced')
        current = {}
        for key in ('idVendor', 'idProduct', 'bcdDevice', 'busnum', 'devnum', 'serial'):
            try:
                current[key] = (self.root / key).read_text().strip()
            except FileNotFoundError:
                if key != 'serial':
                    raise
        for key in ('idVendor', 'idProduct', 'bcdDevice', 'busnum', 'devnum', 'serial'):
            if current.get(key) != self.identity.get(key):
                raise UsbTransportError('Selected device/session changed; stopping probe')
        if time.monotonic() - self.started > 55:
            raise UsbTransportError('Total diagnostic time budget exhausted')

    def send(self, handle, command, payload, log, short=False):
        self.check()
        self.sequence = (self.sequence + 1) & 255
        request = (se.nexus_request if short else se.packet)(self.sequence, command, payload)
        event = {'request': request.hex()}
        if isinstance(getattr(handle, '_interface', None), int):
            event['interface'] = handle._interface
        log.append(event)
        if handle.write(request) != len(request):
            raise UsbTransportError('Short diagnostic request transfer')

    def receive(self, handle, log, match, seconds=2, heartbeat=None):
        deadline = time.monotonic() + seconds
        next_heartbeat = deadline - seconds + 0.25
        # Both time and packet count are bounded even for a busy input stream.
        for _ in range(4096):
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if heartbeat is not None and time.monotonic() >= next_heartbeat:
                heartbeat()
                next_heartbeat = time.monotonic() + 0.25
            reply = handle.read(64, timeout_ms=min(200, max(1, int(remaining * 1000))))
            if not reply:
                continue
            try:
                result = match(reply)
            except Exception as exc:
                log.append({'response': reply.hex(), 'matched': False,
                            'interface': getattr(handle, '_interface', None),
                            'match_error': str(exc)})
                raise
            event = {'response': reply.hex(), 'matched': result is not None}
            if isinstance(getattr(handle, '_interface', None), int):
                event['interface'] = handle._interface
            log.append(event)
            if result is not None:
                return result
        else:
            log.append({'packet_limit': 4096})
            return None
        log.append({'timeout': True})
        return None

    def channel(self, interface, out_ep, in_ep):
        log = []
        evidence = {'interface': interface, 'out': out_ep, 'in': in_ep,
                    'transfer': 'interrupt' if interface == 0 else 'bulk',
                    'events': log, 'reads': []}
        self.evidence['channels'].append(evidence)
        handle = None
        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), interface, out_ep, in_ep)
            evidence['original_alt'] = handle.original_alt
            if interface == 2:
                time.sleep(1)
            firmware = None
            if interface == 0:
                for _ in range(24):
                    self.send(handle, 2, b'\xf2\x00', log)
                    time.sleep(0.25)
                self.send(handle, 1, b'\x09', log)
                firmware = self.receive(handle, log, lambda r:
                    r[5:] if len(r) >= 7 and r[0] == 0x10 and r[3:5] == b'\x3c\x0a'
                    else None)
            if firmware is not None:
                evidence['firmware_payload'] = firmware.hex()
                evidence['firmware_text'] = firmware.decode('utf-16-le', 'replace').split('\0')[0]
            # Repeat the first chunk to establish reproducibility, not merely recognition.
            for attempt in range(2):
                profile, offset, length = 1, 0, 55
                read = {'profile': profile, 'offset': offset, 'length': length,
                        'attempt': attempt + 1, 'data': None}
                evidence['reads'].append(read)
                try:
                    self.send(handle, 5, bytes((4, profile, 0, 0, length)), log)
                    value = self.receive(handle, log, lambda r:
                        se.match_read(r, profile, offset, length), seconds=4)
                    read['data'] = None if value is None else value.hex()
                except OSError as exc:
                    read['error'] = str(exc)
                    if getattr(exc, 'errno', None) == errno.ENODEV:
                        raise
                    self.check()  # disconnected or replaced sessions must stop
                time.sleep(0.25)
            evidence['repeatable'] = (evidence['reads'][0]['data'] is not None
                and evidence['reads'][0]['data'] == evidence['reads'][1]['data'])
            return evidence['repeatable']
        except Exception as exc:
            evidence['error'] = str(exc)
            if hasattr(exc, 'cleanup'):
                evidence['cleanup'] = exc.cleanup
            return False
        finally:
            if handle is not None:
                handle.close()
                evidence['cleanup'] = handle.cleanup

    def app_startup_reads(self):
        from vendors.gamesir.models.g7se.startup import Startup
        result = {'interface': 0, 'events': []}
        self.evidence['channels'].append(result)
        handle = startup = None
        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            startup = Startup(handle, self.bus, self.address, self.root,
                              active=lambda: (self.check() is None), log=result['events'])
            result.update(startup.run())
        except Exception as exc:
            result['error'] = str(exc)
            return False
        finally:
            if handle is not None:
                try:
                    if startup is not None:
                        startup.restore_input()
                except Exception as exc:
                    result['input_state_restore_error'] = str(exc)
                handle.close()
                result['cleanup'] = handle.cleanup
        return self.nexus_reads()

    def authenticate_reads(self):
        from vendors.gamesir.models.g7se.auth import Exchange
        result = {'interface': 0, 'events': []}
        self.evidence['channels'].append(result)
        handle = None
        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            exchange = Exchange(self, handle, result['events'])
            sequence = exchange.next_sequence()
            exchange.raw(gip.identify(sequence), 'read-identification-before-fresh-authentication')
            transfer = gip.IdentificationTransfer(expected_sequence=sequence)
            def match(reply):
                if not reply or reply[0] != 4:
                    return None
                value, ack = transfer.accept(reply)
                if ack is not None:
                    exchange.raw(ack, 'validated-identification-ack')
                return value
            identity = self.receive(handle, result['events'], match, seconds=4)
            if identity is None:
                raise UsbTransportError('Identification timed out before authentication')
            result['identification_sha256'] = __import__('hashlib').sha256(identity).hexdigest()
            exchange.raw(se.gip_power_on(exchange.next_sequence()), 'standard-input-power-on')
            result.update(exchange.run())
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            if handle is not None:
                try:
                    self.check()
                    self.sequence = self.sequence % 255 + 1
                    request = se.gip_power_on(self.sequence)
                    result['events'].append({'request': request.hex(), 'stage': 'restore-linux-input-state'})
                    handle.write(request)
                except Exception as exc:
                    result['input_state_restore_error'] = str(exc)
                handle.close()
                result['cleanup'] = handle.cleanup
        if result.get('fresh_transcript_verified'):
            return self.nexus_reads()
        return False

    def nexus_reads(self, initialize=False, silent_rumble=False, auth_status=False):
        """Replay captured short framing only; preserve repeat full snapshots."""
        log, reads = [], []
        evidence = {'interface': 0, 'out': 2, 'in': 0x82, 'events': log,
                    'reads': reads, 'transfer': 'interrupt',
                    'source': 'g7 se/persistence-20261008-163059.decoded.json'}
        self.evidence['channels'].append(evidence)
        handle = None

        def keepalive():
            self.send(handle, 2, b'\xf2\x00', log, short=True)

        def read(profile, offset, length):
            self.send(handle, 5, bytes((4, profile)) + offset.to_bytes(2, 'big')
                      + bytes((length,)), log, short=True)
            sequence = self.sequence
            value = self.receive(handle, log, lambda r:
                se.match_read(r, profile, offset, length) if len(r) > 2
                and r[2] == sequence else None, heartbeat=keepalive)
            reads.append({'profile': profile, 'offset': offset, 'length': length,
                          'sequence': sequence, 'data': None if value is None else value.hex()})
            time.sleep(0.05)
            return value

        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            if auth_status:
                self.sequence = self.sequence % 255 + 1
                # Fixed status notification from raw persistence frame 1147.
                # No certificates, challenges or session cryptograms are replayed.
                request = bytes((6, 0x20, self.sequence, 2, 1, 0))
                log.append({'request': request.hex(), 'interface': 0,
                            'stage': 'captured-final-authentication-status-candidate'})
                if handle.write(request) != len(request):
                    raise UsbTransportError('Short status candidate transfer')
                time.sleep(.05)
            if initialize:
                self.sequence = self.sequence % 255 + 1
                # Raw Windows startup/reconnect captures repeatedly contain this
                # transient GIP command. Do not infer or replay authentication.
                request = se.nexus_initialize(self.sequence)
                log.append({'request': request.hex(), 'interface': 0,
                            'stage': 'captured-nexus-startup-candidate'})
                if handle.write(request) != len(request):
                    raise UsbTransportError('Short startup candidate transfer')
                time.sleep(.05)
                if silent_rumble:
                    for _ in range(3):
                        self.check()
                        self.sequence = self.sequence % 255 + 1
                        request = se.nexus_silent_rumble(self.sequence)
                        log.append({'request': request.hex(), 'interface': 0,
                                    'stage': 'captured-zero-amplitude-startup-companion'})
                        if handle.write(request) != len(request):
                            raise UsbTransportError('Short startup companion transfer')
                        time.sleep(.05)
            for _ in range(6):
                keepalive()
                time.sleep(0.05)
            self.send(handle, 1, b'\x0b', log, short=True)
            sequence = self.sequence
            value = self.receive(handle, log, lambda r: r[5:] if len(r) >= 7
                and r[:2] == b'\x10\x00' and r[2] == sequence
                and r[3:5] == b'\x3c\x0c' else None, heartbeat=keepalive)
            evidence['active_profile_payload'] = None if value is None else value.hex()
            # The captured cold reconnect starts at profile offset zero.
            values = [read(1, 0, 55) for _ in range(2)]
            evidence['repeatable'] = values[0] is not None and values[0] == values[1]
            if evidence['repeatable']:
                snapshots = []
                for _ in range(2):
                    banks = {}
                    for bank in (1, 2, 3, 4):
                        chunks = []
                        # Nexus reads 421 bytes per bank: seven 55-byte chunks,
                        # then 36 bytes at 0181. Do not extend that range.
                        for offset in range(0, 421, 55):
                            data = read(bank, offset, min(55, 421 - offset))
                            if data is None:
                                raise UsbTransportError('Incomplete profile snapshot; stopping')
                            chunks.append(data)
                        banks[str(bank)] = b''.join(chunks).hex()
                    snapshots.append(banks)
                evidence['snapshots'] = snapshots
                evidence['repeatable_full_profiles'] = snapshots[0] == snapshots[1]
        except Exception as exc:
            evidence['error'] = str(exc)
            if hasattr(exc, 'cleanup'):
                evidence['cleanup'] = exc.cleanup
        finally:
            if handle is not None:
                if initialize:
                    try:
                        self.check()
                        self.sequence = self.sequence % 255 + 1
                        request = se.gip_power_on(self.sequence)
                        log.append({'request': request.hex(), 'interface': 0,
                                    'stage': 'restore-linux-input-state'})
                        handle.write(request)
                    except Exception as exc:
                        evidence['input_state_restore_error'] = str(exc)
                handle.close()
                evidence['cleanup'] = handle.cleanup
        return evidence.get('repeatable', False)

    def nexus_roundtrip(self, recovery_directory='docs/diagnostics/g7se-recovery'):
        """Authorized temporary rear remaps, durable originals, then restoration."""
        import register_transaction
        if not self.nexus_reads():
            return False
        baseline = self.evidence['channels'][-1]
        if not baseline.get('repeatable_full_profiles'):
            return False
        log = []
        result = {'interface': 0, 'events': log, 'operations': [], 'repeatable': False}
        self.evidence['channels'].append(result)
        handle = None
        records = [(bank, address, bytes.fromhex(baseline['snapshots'][0][str(bank)])[address:address + 8])
                   for bank in se.PROFILE_BANKS for _, address in se.REMAP_SLOTS]
        for _, _, record in records:
            se.decode_remap(record)
        attempted = False

        def heartbeat():
            self.send(handle, 2, b'\xf2\x00', log, short=True)

        def read(bank, address, length):
            self.send(handle, 5, bytes((4, bank)) + address.to_bytes(2, 'big')
                      + bytes((length,)), log, short=True)
            sequence = self.sequence
            value = self.receive(handle, log, lambda r: se.match_read(r, bank, address, length)
                if len(r) > 2 and r[2] == sequence else None, heartbeat=heartbeat)
            if value is None:
                raise UsbTransportError('Remap readback timed out')
            return value

        def write(bank, address, data):
            self.check()
            self.sequence = self.sequence % 255 + 1
            request = se.remap_write(self.sequence, bank, address, data)
            log.append({'request': request.hex(), 'interface': 0, 'stage': 'temporary-remap-or-restore'})
            if handle.write(request) != 64:
                raise UsbTransportError('Short remap write')
            time.sleep(0.05)
            return True

        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            heartbeat()
            temporary = [(bank, address, se.remap_record(15)) for bank, address, _ in records]
            attempted = True
            ok, message = register_transaction.apply(temporary, read, write,
                recovery_directory, 'GameSir G7 SE 3537:1010 descriptor 6.30')
            result['operations'].append({'temporary_A': ok, 'message': message})
            if not ok:
                raise UsbTransportError(message)
            # Verify complete clear/default on both rear records, then restore.
            clear = [(bank, address, se.remap_record(-1)) for bank, address, _ in records]
            ok, message = register_transaction.apply(clear, read, write,
                recovery_directory, 'GameSir G7 SE 3537:1010 descriptor 6.30')
            result['operations'].append({'temporary_clear': ok, 'message': message})
            if not ok:
                raise UsbTransportError(message)
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            if handle is not None:
                if attempted:
                    restored = True
                    for bank, address, record in records:
                        try:
                            write(bank, address, record)
                            restored &= read(bank, address, 8) == record
                        except Exception as exc:
                            restored = False
                            result.setdefault('restore_errors', []).append(str(exc))
                    result['original_records_restored'] = restored
                    if restored:
                        try:
                            after = {}
                            for bank in (1, 2, 3, 4):
                                after[str(bank)] = b''.join(read(bank, offset, min(55, 421 - offset))
                                    for offset in range(0, 421, 55)).hex()
                            result['restored_profiles'] = after
                            result['all_readable_settings_unchanged'] = after == baseline['snapshots'][0]
                        except Exception as exc:
                            result['comparison_error'] = str(exc)
                handle.close()
                result['cleanup'] = handle.cleanup
        result['repeatable'] = (not result.get('error') and result.get('original_records_restored')
                                and result.get('all_readable_settings_unchanged', False))
        return result['repeatable']

    def restore_physical(self, preparation, recovery_directory='docs/diagnostics/g7se-recovery'):
        """Restore durable pre-test records after a deliberate physical reconnect."""
        import register_transaction
        saved = json.loads(Path(preparation).read_text())
        for key in ('sysfs', 'idVendor', 'idProduct', 'bcdDevice', 'serial', 'devpath', 'busnum'):
            if self.identity.get(key) != saved['before'].get(key):
                raise UsbTransportError('Restore device does not match original physical device')
        baseline = saved['channels'][0]['snapshots'][0]
        records = [(bank, address, bytes.fromhex(baseline[str(bank)])[address:address+8])
                   for bank in se.PROFILE_BANKS for _, address in se.REMAP_SLOTS]
        for _, _, record in records:
            se.decode_remap(record)
        # A freshly reconnected unit needs the same bounded warmup and active
        # query as the confirmed read replay before rear-record requests.
        if not self.nexus_reads():
            return False
        current = self.evidence['channels'][-1]
        if not current.get('repeatable_full_profiles'):
            return False
        log = []
        result = {'interface': 0, 'events': log}
        self.evidence['channels'].append(result)
        handle = None

        def heartbeat():
            self.send(handle, 2, b'\xf2\x00', log, short=True)

        def read(bank, address, length):
            self.send(handle, 5, bytes((4, bank)) + address.to_bytes(2, 'big')
                      + bytes((length,)), log, short=True)
            sequence = self.sequence
            value = self.receive(handle, log, lambda r: se.match_read(r, bank, address, length)
                if len(r) > 2 and r[2] == sequence else None, heartbeat=heartbeat)
            if value is None:
                raise UsbTransportError('Restore readback timed out')
            return value

        def write(bank, address, data):
            self.check()
            self.sequence = self.sequence % 255 + 1
            request = se.remap_write(self.sequence, bank, address, data)
            log.append({'request': request.hex(), 'interface': 0, 'stage': 'restore-original'})
            if handle.write(request) != len(request):
                raise UsbTransportError('Short restore transfer')
            time.sleep(.05)
            return True

        try:
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            heartbeat()
            changes = [(bank, address, record) for bank, address, record in records
                       if read(bank, address, 8) != record]
            ok, message = register_transaction.apply(changes, read, write,
                recovery_directory, 'G7 SE physical-check restoration')
            result['original_records_restored'] = ok
            result['message'] = message
            if not ok:
                raise UsbTransportError(message)
        finally:
            if handle is not None:
                handle.close()
                result['cleanup'] = handle.cleanup
        if not self.nexus_reads():
            return False
        after = self.evidence['channels'][-1]
        result['all_readable_settings_unchanged'] = (
            after.get('repeatable_full_profiles') and after['snapshots'][0] == baseline)
        return result['all_readable_settings_unchanged']

    def restore_captured_originals(self, preparation):
        """Recovery only: restore exactly the records changed in the saved test.

        Originals and the temporary records were durably captured before release.
        This path cannot save new mappings or write unrelated records. An ACK is
        recorded, but does not substitute for verified register readback.
        """
        saved = json.loads(Path(preparation).read_text())
        for key in ('sysfs', 'idVendor', 'idProduct', 'bcdDevice', 'serial', 'devpath', 'busnum'):
            if self.identity.get(key) != saved['before'].get(key):
                raise UsbTransportError('Recovery device identity changed')
        operation = saved['channels'][1]
        if not operation.get('only_expected_records_changed'):
            raise UsbTransportError('Preparation did not confirm only expected edits')
        before, temporary = saved['channels'][0]['snapshots'][0], saved['channels'][-1]['snapshots'][0]
        records = []
        for bank in (1, 2, 3, 4):
            original, changed = bytes.fromhex(before[str(bank)]), bytes.fromhex(temporary[str(bank)])
            for _, address in se.REMAP_SLOTS:
                record = original[address:address+8]
                if record != changed[address:address+8]:
                    se.decode_remap(record)
                    records.append((bank, address, record))
        if len(records) != 2:
            raise UsbTransportError('Expected exactly two temporary records')
        log = []
        result = {'interface': 0, 'events': log, 'originals_source': str(preparation), 'records': []}
        self.evidence['channels'].append(result)
        handle = None
        try:
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            for bank, address, record in records:
                self.check()
                self.sequence = self.sequence % 255 + 1
                sequence = self.sequence
                request = se.remap_write(sequence, bank, address, record)
                log.append({'request': request.hex(), 'stage': 'restore-durable-original'})
                if handle.write(request) != len(request):
                    raise UsbTransportError('Short recovery write')
                ack = self.receive(handle, log, lambda r: r if len(r) == 64
                    and r[:3] == bytes((16, 0, sequence)) and r[3:5] == b'\x3c\x06' else None)
                item = {'bank': bank, 'address': address, 'original': record.hex(), 'ack': ack is not None}
                result['records'].append(item)
                self.send(handle, 5, bytes((4, bank)) + address.to_bytes(2, 'big') + bytes((8,)), log, short=True)
                read_sequence = self.sequence
                readback = self.receive(handle, log, lambda r: se.match_read(r, bank, address, 8)
                    if len(r) > 2 and r[2] == read_sequence else None)
                item['readback_verified'] = readback == record
        finally:
            if handle is not None:
                handle.close()
                result['cleanup'] = handle.cleanup
        result['all_original_records_verified'] = all(r['readback_verified'] for r in result['records'])
        return result['all_original_records_verified']

    def app_roundtrip(self, keep_temporary=False):
        """Exercise actual reader/Qt Rebinds staging and Save against hardware."""
        import os
        import threading
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ['XDG_DATA_HOME'] = str(Path('docs/diagnostics/g7se-app-recovery').resolve())
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QTimer
        from bridge import GamesirBridge
        import reader
        import controller_profile as profiles
        from gs_common import find_controllers
        from gs_state import state
        if not self.nexus_reads():
            return False
        before = self.evidence['channels'][-1]
        if not before.get('repeatable_full_profiles'):
            return False
        ctrl = next(c for c in find_controllers() if c.get('usb')
                    and Path(c['usb']['sysfs']).resolve() == self.root)
        log = []
        result = {'interface': 0, 'events': log, 'operations': [], 'repeatable': False}
        self.evidence['channels'].append(result)
        app = QGuiApplication.instance() or QGuiApplication([])
        profiles.set_active(profiles.G7_SE)
        state.update(selected=ctrl['id'], connected=True, config_wanted=True, demo=False,
                     usb_bcd=ctrl.get('bcd'))
        bridge = GamesirBridge()
        bridge._apply_profile(profiles.G7_SE)
        open_device = se.open_device
        originals = None
        attempted = False

        def recorded_open(*args):
            handle = open_device(*args)
            native_write = handle.write
            def write(request):
                self.check()
                log.append({'request': bytes(request).hex(), 'interface': 0})
                return native_write(request)
            handle.write = write
            return handle

        def wait(predicate, seconds=8):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                self.check()
                app.processEvents()
                if predicate():
                    return
                time.sleep(0.02)
            raise UsbTransportError('App validation timed out: ' + state.get('config_status', ''))

        def save(mapping):
            for source, code in mapping.items():
                bridge.setRemapCode(source, code)
            if bridge.pendingCount != len(mapping):
                raise UsbTransportError('App refused to stage remaps')
            bridge.applyConfig()
            wait(lambda: not bridge._backup_busy)
            result['operations'].append({'mapping': mapping, 'status': bridge._apply_status})
            if not bridge._apply_status.startswith('Applied') or bridge.pendingCount:
                raise UsbTransportError('App Save failed: ' + bridge._apply_status)
            wait(lambda: bridge._loaded_profile == state.get('edit_profile')
                 and bridge._config_loading is None)

        worker = threading.Thread(target=reader.read_session_seusb, args=(ctrl,), daemon=True)
        se.open_device = recorded_open
        try:
            worker.start()
            wait(lambda: set(bridge.config.get('remap', {})) == {'L4', 'R4'}
                 and bridge._driving == state.get('driving')
                 and bridge._config_generation == __import__('vendors.gamesir.control', fromlist=['generation']).generation()
                 and bridge._config_loading is None)
            originals = dict(bridge.config['remap'])
            result['original_mapping'] = originals
            attempted = True
            save({'L4': 15, 'R4': 16})
            if keep_temporary:
                result['temporary_mapping_left_for_physical_check'] = True
            else:
                save(originals)
                result['app_save_and_restore_verified'] = True
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            if (attempted and not result.get('app_save_and_restore_verified')
                    and not result.get('temporary_mapping_left_for_physical_check') and originals):
                try:
                    save(originals)
                    result['failure_restore_verified'] = True
                except Exception as exc:
                    result['restore_error'] = str(exc)
            state['config_wanted'] = False
            worker.join(2)
            if worker.is_alive():
                reader.release_controller()
                worker.join(2)
            se.open_device = open_device
            for timer in bridge.findChildren(QTimer):
                timer.stop()
            bridge.deleteLater()
        if self.nexus_reads():
            after = self.evidence['channels'][-1]
            result['all_readable_settings_unchanged'] = (
                after.get('repeatable_full_profiles') and after['snapshots'][0] == before['snapshots'][0])
            if keep_temporary:
                expected = dict(before['snapshots'][0])
                bank = bytearray.fromhex(expected[str(state.get('profile') or 1)])
                bank[0xab:0xb3], bank[0xc7:0xcf] = se.remap_record(15), se.remap_record(16)
                expected[str(state.get('profile') or 1)] = bank.hex()
                result['only_expected_records_changed'] = after['snapshots'][0] == expected
        result['repeatable'] = bool((result.get('app_save_and_restore_verified')
                                    and result.get('all_readable_settings_unchanged'))
                                   or (keep_temporary and result.get('only_expected_records_changed')))
        return result['repeatable']

    def identify_gip(self):
        """Two GIP identifications, then strict read candidates on 0 and 2."""
        log, reads, identities = [], [], []
        evidence = {'interface': 0, 'out': 2, 'in': 0x82, 'events': log,
                    'reads': reads, 'identifications': identities,
                    'source': 'https://github.com/medusalix/xone/blob/master/bus/protocol.c'}
        self.evidence['channels'].append(evidence)
        handle = bulk = None

        def raw(request, stage):
            self.check()
            log.append({'request': request.hex(), 'interface': 0, 'stage': stage})
            if handle.write(request) != len(request):
                raise UsbTransportError('Short GIP diagnostic transfer')

        def identify(stage):
            self.sequence = self.sequence % 255 + 1
            raw(gip.identify(self.sequence), stage)
            transfer = gip.IdentificationTransfer()

            def match(reply):
                try:
                    value, ack = transfer.accept(reply)
                except ValueError as exc:
                    log.append({'gip_rejected': str(exc), 'response': reply.hex()})
                    return None
                if ack is not None:
                    raw(ack, 'identification-ack')
                return value

            value = self.receive(handle, log, match, seconds=6)
            item = {'stage': stage, 'payload': None if value is None else value.hex(),
                    'partial_bytes': len(transfer.data), 'expected_bytes': transfer.total}
            if value is not None:
                try:
                    item['decoded'] = gip.describe(value)
                except ValueError as exc:
                    item['decode_error'] = str(exc)
            identities.append(item)

        def keepalive():
            self.send(handle, 2, b'\xf2\x00', log)

        def read(target, length, fixed=False):
            for _ in range(2):
                item = {'profile': 1, 'offset': 0, 'length': length,
                        'interface': target._interface, 'data': None,
                        'framing': 'fixed-60' if fixed else 'length-5'}
                reads.append(item)
                try:
                    if fixed:
                        self.check()
                        self.sequence = self.sequence % 255 + 1
                        request = se.fixed_length_read_request(self.sequence, 1, 0, length)
                        log.append({'request': request.hex(), 'interface': target._interface,
                                    'stage': 'advertised-fixed-length-read'})
                        if target.write(request) != len(request):
                            raise UsbTransportError('Short fixed-length read transfer')
                    else:
                        self.send(target, 5, bytes((4, 1, 0, 0, length)), log)
                    value = self.receive(target, log, lambda r: se.match_read(r, 1, 0, length),
                                         heartbeat=keepalive)
                    item['data'] = None if value is None else value.hex()
                except OSError as exc:
                    item['error'] = str(exc)
                    if getattr(exc, 'errno', None) == errno.ENODEV:
                        raise
                    self.check()

        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            identify('before-power-on')
            self.sequence = self.sequence % 255 + 1
            raw(se.gip_power_on(self.sequence), 'standard-power-on')
            identify('after-power-on')
            for _ in range(2):
                keepalive()
                time.sleep(0.25)
            for length in (1, 55):
                read(handle, length)
            # Only exercise this framing when both identification replies agree
            # and their decoded table actually advertises downstream 0f/60.
            verified_metadata = (len(identities) == 2 and identities[0]['payload'] is not None
                and identities[0]['payload'] == identities[1]['payload'])
            commands = identities[0].get('decoded', {}).get('client_commands', []) if identities else []
            if verified_metadata and any(c['command'] == 15 and c['length'] == 60
                                         and c['options'] & 8 for c in commands):
                for length in (1, 55):
                    read(handle, length, fixed=True)
            matched = [item for item in reads if item['data'] is not None]
            if not matched:
                try:
                    self.check()
                    bulk = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                           str(self.root), 2, 1, 0x81)
                    evidence['bulk_original_alt'] = bulk.original_alt
                    for length in (1, 55):
                        read(bulk, length)
                finally:
                    if bulk is not None:
                        bulk.close()
                        evidence['bulk_cleanup'] = bulk.cleanup
                        bulk = None
            self.send(handle, 1, b'\x09', log)
            value = self.receive(handle, log, lambda r: r[5:] if len(r) >= 6
                                 and r[0] == 0x10 and r[3:5] == b'\x3c\x0a' else None)
            evidence['final_firmware_payload'] = None if value is None else value.hex()
        except Exception as exc:
            evidence['error'] = str(exc)
            if hasattr(exc, 'cleanup'):
                evidence['claim_cleanup'] = exc.cleanup
        finally:
            if bulk is not None:
                bulk.close()
                evidence['bulk_cleanup'] = bulk.cleanup
            if handle is not None:
                handle.close()
                evidence['cleanup'] = handle.cleanup
        evidence['repeatable_identification'] = (len(identities) == 2
            and identities[0]['payload'] is not None
            and identities[0]['payload'] == identities[1]['payload'])
        pairs = {}
        for item in reads:
            if item['data'] is not None:
                pairs.setdefault((item['interface'], item['framing'], item['length']), []).append(item['data'])
        evidence['repeatable'] = any(len(values) == 2 and values[0] == values[1]
                                     for values in pairs.values())
        return evidence['repeatable']

    def investigate(self):
        """Fixed, source-backed candidate matrix; no command-space sweeps."""
        log, reads, info = [], [], []
        evidence = {'interface': 0, 'out': 2, 'in': 0x82, 'events': log,
                    'reads': reads, 'info': info,
                    'sources': ['pyg7/session.py EARLY_PROBE_HEARTBEATS / settle / read_chunk',
                                'vendors/gamesir/control.py pump_reads',
                                'reader.py maintenance_loop / read_session',
                                'Linux drivers/input/joystick/xpad.c xboxone_power_on'],
                    'heartbeat_interval_seconds': 0.25}
        self.evidence['channels'].append(evidence)
        handle = bulk = None

        def keepalive():
            self.send(handle, 2, b'\xf2\x00', log)

        def warm(count):
            for _ in range(count):
                keepalive()
                time.sleep(0.25)

        def query(selector, stage):
            self.send(handle, 1, bytes((selector,)), log)
            value = self.receive(handle, log, lambda r:
                r[5:] if len(r) >= 6 and r[0] == 0x10
                and r[3:5] == bytes((0x3c, selector + 1)) else None,
                heartbeat=keepalive)
            item = {'stage': stage, 'selector': selector,
                    'payload': None if value is None else value.hex()}
            if value is not None and selector == 9:
                item['text'] = value[:len(value) & ~1].decode('utf-16-le', 'replace').split('\0')[0]
            info.append(item)
            time.sleep(0.1)

        def read(stage, profile, offset, length, target=None, legacy=False):
            target = target or handle
            item = {'stage': stage, 'profile': profile, 'offset': offset,
                    'length': length, 'framing': 'legacy' if legacy else 'enveloped',
                    'interface': 2 if target is bulk and bulk is not None else 0,
                    'data': None}
            reads.append(item)
            try:
                self.check()
                if legacy:
                    request = se.legacy_packet(4, bytes((profile,)) + offset.to_bytes(2, 'big')
                                              + bytes((length,)))
                    log.append({'request': request.hex(), 'interface': 0, 'stage': stage})
                    if target.write(request) != 64:
                        raise UsbTransportError('Short legacy read request')
                else:
                    self.send(target, 5, bytes((4, profile)) + offset.to_bytes(2, 'big')
                              + bytes((length,)), log)
                    log[-1]['stage'] = stage
                matcher = se.match_legacy_read if legacy else se.match_read
                value = self.receive(target, log, lambda r: matcher(r, profile, offset, length),
                                     seconds=2, heartbeat=keepalive)
                item['data'] = None if value is None else value.hex()
            except OSError as exc:
                item['error'] = str(exc)
                if getattr(exc, 'errno', None) == errno.ENODEV:
                    raise
                self.check()
            time.sleep(0.1)
            return item['data']

        try:
            self.check()
            handle = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                     str(self.root), 0, 2, 0x82)
            warm(2)
            # Attempt the early minimal read before any info query or long warm-up.
            early = read('early-two-heartbeats', 1, 0, 1)
            if early is not None:
                read('early-repeat', 1, 0, 1)
            query(9, 'early-firmware')
            query(0x0b, 'active-profile-candidate')
            warm(24)
            for profile, offset, length in ((1, 0, 1), (1, 0, 55), (2, 0, 1),
                                           (3, 0, 1), (4, 0, 1),
                                           (1, 0xb2, 7), (1, 0xc0, 7)):
                value = read('maintained-heartbeats', profile, offset, length)
                if value is not None:
                    read('matched-read-repeat', profile, offset, length)
            query(9, 'firmware-after-interrupt-reads')
            # Upstream holds interface 0 while testing interface 2. Keep it alive
            # here, rather than rebinding xpad between the two channel tests.
            try:
                self.check()
                bulk = ProbeHandle.open(se.VID, (se.PID,), self.bus, self.address,
                                       str(self.root), 2, 1, 0x81)
                evidence['bulk_original_alt'] = bulk.original_alt
                warm(4)
                for length in (1, 55):
                    value = read('bulk-with-interface-zero-held', 1, 0, length, target=bulk)
                    if value is not None:
                        read('bulk-repeat', 1, 0, length, target=bulk)
            except OSError as exc:
                evidence['bulk_error'] = str(exc)
                if hasattr(exc, 'cleanup'):
                    evidence['bulk_cleanup'] = exc.cleanup
                if getattr(exc, 'errno', None) == errno.ENODEV:
                    raise
                self.check()
            finally:
                if bulk is not None:
                    bulk.close()
                    evidence['bulk_cleanup'] = bulk.cleanup
                    bulk = None
            # Legacy frames are the app's established read and maintenance
            # commands on older GameSir products, not new guessed command IDs.
            for _ in range(2):
                self.check()
                request = se.legacy_packet(0xf2)
                log.append({'request': request.hex(), 'stage': 'legacy-heartbeat'})
                if handle.write(request) != 64:
                    raise UsbTransportError('Short legacy heartbeat')
                time.sleep(0.25)
            for length in (1, 55):
                value = read('legacy-read-framing', 1, 0, length, legacy=True)
                if value is not None:
                    read('legacy-repeat', 1, 0, length, legacy=True)
            # The standard initialization xpad already sends to this Xbox One
            # identity. Exact five-byte packet, with no persistent settings.
            self.check()
            self.sequence = (self.sequence + 1) & 255
            request = se.gip_power_on(self.sequence)
            log.append({'request': request.hex(), 'interface': 0, 'stage': 'xpad-input-init'})
            if handle.write(request) != len(request):
                raise UsbTransportError('Short GIP input initialization transfer')
            warm(2)
            for length in (1, 55):
                value = read('after-xpad-input-init', 1, 0, length)
                if value is not None:
                    read('after-xpad-input-init-repeat', 1, 0, length)
            query(9, 'final-firmware-health-check')
        except Exception as exc:
            evidence['error'] = str(exc)
            if hasattr(exc, 'cleanup'):
                evidence['cleanup'] = exc.cleanup
        finally:
            if bulk is not None:
                bulk.close()
                evidence['bulk_cleanup'] = bulk.cleanup
            if handle is not None:
                handle.close()
                evidence['cleanup'] = handle.cleanup
        pairs = {}
        for item in reads:
            if item['data'] is not None:
                key = (item['framing'], item['interface'], item['profile'], item['offset'], item['length'])
                pairs.setdefault(key, []).append(item['data'])
        evidence['repeatable'] = any(len(values) >= 2 and len(set(values)) == 1
                                     for values in pairs.values())
        return evidence['repeatable']


def physical_inputs(preparation, output, resume=False, restore_check=False):
    """Bounded xpad-only observation; never opens or writes USB."""
    import os
    import select
    import struct
    from gs_common import parse_devices, evdev_port
    original = json.loads(Path(preparation).read_text())['before']
    root = Path(original['sysfs'])
    port = original['busnum'] + '-' + original['devpath']
    report = {'mode': 'xpad-physical-input-and-reconnect', 'identity': original,
              'events': [], 'phases': [], 'configuration_requests': 0}
    if resume:
        report = json.loads(Path(output).read_text())
        if report['identity'] != original or len(report['phases']) != 1:
            raise UsbTransportError('No matching completed pre-reconnect input phase')
        report['previous_error'] = report.pop('error', None)
    fds = {}
    fmt = 'llHHi'
    size = struct.calcsize(fmt)

    def close():
        for fd in fds:
            os.close(fd)
        fds.clear()

    try:
        phases = (('restoration_check',) if restore_check else
                  ('after_reconnect',) if resume else ('before_reconnect', 'after_reconnect'))
        for phase in phases:
            deadline = time.monotonic() + 150
            counts = {code: {0: 0, 1: 0} for code in ((304, 305, 317, 318) if restore_check else (304, 305))}
            while time.monotonic() < deadline:
                if not root.exists():
                    close()
                    report['disconnect_observed'] = True
                    time.sleep(.1)
                    continue
                current = topology(root)
                for key in ('idVendor', 'idProduct', 'bcdDevice', 'serial', 'devpath', 'busnum'):
                    if current.get(key) != original.get(key):
                        raise UsbTransportError('Physical device identity changed')
                if phase == 'after_reconnect' and current['devnum'] == original['devnum']:
                    time.sleep(.1)
                    continue
                if not fds:
                    for device in parse_devices():
                        if (device['vendor'], device['product']) != (se.VID, se.PID):
                            continue
                        for node in device['events']:
                            if evdev_port(node) == port:
                                try:
                                    fds[os.open(node, os.O_RDONLY | os.O_NONBLOCK)] = node
                                except PermissionError:
                                    continue  # Give udev time to grant the recreated input node.
                    if fds:
                        print('Listening:', phase, list(fds.values()), flush=True)
                if not fds:
                    time.sleep(.1)
                    continue
                ready, _, _ = select.select(list(fds), [], [], .1)
                for fd in ready:
                    try:
                        data = os.read(fd, size * 64)
                    except OSError as exc:
                        if exc.errno == errno.ENODEV:
                            close()
                            report['disconnect_observed'] = True
                            break
                        raise
                    for offset in range(0, len(data) - size + 1, size):
                        seconds, micros, kind, code, value = struct.unpack(fmt, data[offset:offset+size])
                        if kind == 1:
                            report['events'].append({'phase': phase, 'code': code, 'value': value,
                                'time': seconds + micros / 1e6, 'node': fds[fd]})
                            if code in counts and value in (0, 1):
                                counts[code][value] += 1
                                print(phase, {304:'A',305:'B',317:'LS',318:'RS'}[code], value, flush=True)
                complete = {code for code, values in counts.items() if min(values.values()) >= 3}
                if (len(complete) >= 2 if restore_check else len(complete) == 2):
                    report['phases'].append({'phase': phase, 'counts': counts, 'usb_address': current['devnum']})
                    print('Completed:', phase, flush=True)
                    close()
                    break
            else:
                raise UsbTransportError('Physical input phase timed out: ' + phase)
        report['success'] = ({317, 318}.issubset(complete) if restore_check else
                             len(report['phases']) == 2 and report.get('disconnect_observed', False))
        report['after'] = topology(root)
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        close()
        Path(output).write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report.get('success') else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sysfs', help='Exact USB sysfs device path (required if multiple units)')
    parser.add_argument('--output', required=True, help='JSON diagnostic artifact')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--physical-inputs', metavar='PREPARATION_JSON',
                       help='Observe released xpad input before/after physical reconnect; no USB requests')
    modes.add_argument('--physical-after-reconnect', metavar='PREPARATION_JSON',
                       help='Resume physical input observation after granting recreated input-node access')
    modes.add_argument('--verify-restored-input', metavar='PREPARATION_JSON',
                       help='Observe whether the original L3/R3 paddle behavior was restored; no USB writes')
    modes.add_argument('--restore-physical-check', metavar='PREPARATION_JSON',
                       help='Restore original rear records on the same physical device after reconnect')
    modes.add_argument('--restore-captured-originals', metavar='PREPARATION_JSON',
                       help='Recovery only: restore the two durable originals if cold-start reads fail')
    modes.add_argument('--prepare-physical-check', action='store_true',
                       help='Save L4=A/R4=B through the app and release for authorized physical validation')
    modes.add_argument('--app-save-roundtrip', action='store_true',
                       help='Validate actual Qt staging/Save and restore original rear records')
    modes.add_argument('--remap-roundtrip', action='store_true',
                       help='Temporary captured rear remap/clear writes, verified readback and restoration')
    modes.add_argument('--nexus-reads', action='store_true',
                       help='Replay exact short reads from supplied Windows captures; no writes')
    modes.add_argument('--nexus-init-reads', action='store_true',
                       help='Test captured transient Nexus startup packet, read profiles, restore Linux input state')
    modes.add_argument('--nexus-init-rumble-reads', action='store_true',
                       help='Also test captured zero-amplitude rumble startup companion; no settings writes')
    modes.add_argument('--nexus-auth-status-reads', action='store_true',
                       help='Test captured fixed final GIP authentication status before startup and reads')
    modes.add_argument('--gip-auth-reads', action='store_true',
                       help='Run fresh, verified GIP v1 authentication then read profiles; no settings writes')
    modes.add_argument('--app-startup-reads', action='store_true',
                       help='Run production SE startup then repeat full profile reads; no settings writes')
    modes.add_argument('--gip-identify', action='store_true',
                       help='Read GIP identification/capabilities, then retry configuration reads')
    modes.add_argument('--candidates', action='store_true',
                        help='Investigate maintained heartbeats, short reads and legacy framing')
    args = parser.parse_args()
    if args.physical_inputs:
        return physical_inputs(args.physical_inputs, args.output)
    if args.physical_after_reconnect:
        return physical_inputs(args.physical_after_reconnect, args.output, resume=True)
    if args.verify_restored_input:
        return physical_inputs(args.verify_restored_input, args.output, restore_check=True)
    report = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'configuration_enabled': False, 'channels': []}
    try:
        roots = [Path(args.sysfs)] if args.sysfs else [p for p in Path('/sys/bus/usb/devices').glob('*')
            if (p / 'idVendor').exists() and (p / 'idVendor').read_text().strip() == '3537'
            and (p / 'idProduct').read_text().strip() == '1010']
        if len(roots) != 1:
            raise UsbTransportError('Select exactly one G7 SE with --sysfs')
        report['before'] = topology(roots[0])
        if (report['before']['idVendor'], report['before']['idProduct'],
                report['before']['bcdDevice']) != ('3537', '1010', '0630'):
            raise UsbTransportError('Probe is limited to 3537:1010 descriptor 6.30')
        session = Session(roots[0], report)
        if args.restore_captured_originals:
            report['mode'] = 'restore-two-durable-original-records'
            success = session.restore_captured_originals(args.restore_captured_originals)
        elif args.restore_physical_check:
            report['mode'] = 'physical-check-original-restoration'
            success = session.restore_physical(args.restore_physical_check)
        elif args.prepare_physical_check:
            report['mode'] = 'temporary-app-mapping-for-physical-check'
            success = session.app_roundtrip(keep_temporary=True)
        elif args.app_save_roundtrip:
            report['mode'] = 'actual-app-staging-save-and-restore'
            success = session.app_roundtrip()
        elif args.remap_roundtrip:
            report['mode'] = 'temporary-remap-clear-and-restore'
            success = session.nexus_roundtrip()
        elif args.app_startup_reads:
            report['mode'] = 'production-startup-and-short-reads'
            success = session.app_startup_reads()
        elif args.gip_auth_reads:
            report['mode'] = 'fresh-gip-v1-authentication-and-short-reads'
            success = session.authenticate_reads()
        elif args.nexus_auth_status_reads:
            report['mode'] = 'captured-final-status-startup-and-short-reads'
            success = session.nexus_reads(initialize=True, silent_rumble=True, auth_status=True)
        elif args.nexus_init_rumble_reads:
            report['mode'] = 'captured-nexus-startup-companion-and-short-reads'
            success = session.nexus_reads(initialize=True, silent_rumble=True)
        elif args.nexus_init_reads:
            report['mode'] = 'captured-nexus-startup-and-short-reads'
            success = session.nexus_reads(initialize=True)
        elif args.nexus_reads:
            report['mode'] = 'captured-nexus-short-reads'
            success = session.nexus_reads()
        elif args.gip_identify:
            report['mode'] = 'gip-identification-and-read-candidates'
            success = session.identify_gip()
        elif args.candidates:
            report['mode'] = 'initialization-and-read-candidates'
            success = session.investigate()
        else:
            success = session.channel(0, 0x02, 0x82)
            if not success:
                success = session.channel(2, 0x01, 0x81)
        report['repeatable_configuration_reads'] = success
        report['after'] = topology(roots[0])
        sent = any('request' in e for c in report['channels'] for e in c['events'])
        verified_mode = args.restore_physical_check or args.prepare_physical_check or args.app_save_roundtrip or args.remap_roundtrip
        report['result'] = ('Verified rear-record operation and profile comparison passed'
            if success and verified_mode else 'Repeatable configuration reads confirmed; no settings changed'
            if success else 'No repeatable configuration reads; remapping disabled'
            if sent else 'USB access failed before requests; protocol discovery blocked')
    except Exception as exc:
        report['error'] = str(exc)
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after', 'channels')}, indent=2))
    print('Evidence:', args.output)
    return 0 if report.get('repeatable_configuration_reads') else 2


if __name__ == '__main__':
    raise SystemExit(main())
