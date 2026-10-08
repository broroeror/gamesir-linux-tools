"""Bounded diagnostic GIP framing, informed by xone bus/protocol.c.

Identification is the default; the diagnostic authentication caller can reuse
chunk validation. This module does not send packets or configure the device.
Reassembled data is capped at 4096 bytes, below GIP's general 65535 limit.
"""
import uuid


def identify(sequence):
    if not 1 <= sequence <= 255:
        raise ValueError('GIP sequence must be nonzero and fit in a byte')
    return bytes((4, 0x20, sequence, 0))


def decode(packet):
    packet = bytes(packet)
    if not 4 <= len(packet) <= 64:
        raise ValueError('Invalid GIP USB packet size')
    command, options, sequence = packet[:3]
    pos = 3

    def integer():
        nonlocal pos
        value = 0
        for shift in (0, 7, 14):
            if pos >= len(packet):
                raise ValueError('Truncated GIP integer')
            byte = packet[pos]
            pos += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError('Oversized GIP integer')

    length = integer()
    offset = integer() if options & 0x80 else 0
    if length > 58 or pos + length != len(packet):
        raise ValueError('GIP payload size mismatch')
    return {'command': command, 'options': options, 'sequence': sequence,
            'offset': offset, 'payload': packet[pos:]}


class IdentificationTransfer:
    """Bounded client-zero transfer; ACK only validated, contiguous chunks.

    Defaults to identification. Diagnostic authentication supplies command 6
    and pins the expected sequence for each individual exchange.
    """
    def __init__(self, command=4, minimum=32, expected_sequence=None):
        self.command = command
        self.minimum = minimum
        self.expected_sequence = expected_sequence
        self.total = None
        self.sequence = None
        self.data = bytearray()
        self.complete = False

    def accept(self, packet):
        frame = decode(packet)
        options, payload = frame['options'], frame['payload']
        if (frame['command'] != self.command or options & 15 or not options & 0x20
                or self.expected_sequence is not None and frame['sequence'] != self.expected_sequence):
            return None, None
        if self.complete:
            raise ValueError('Identification already complete')
        chunked, start = bool(options & 0x80), bool(options & 0x40)
        if start and not chunked:
            raise ValueError('GIP chunk start without chunk flag')
        if chunked:
            if start:
                if self.total is not None or not self.minimum <= frame['offset'] <= 4096:
                    raise ValueError('Invalid identification total or duplicate start')
                total = frame['offset']
                offset = 0
            else:
                if self.total is None or frame['sequence'] != self.sequence:
                    raise ValueError('Unexpected identification chunk/session')
                total = self.total
                offset = frame['offset']
            if offset != len(self.data) or offset + len(payload) > total:
                raise ValueError('Noncontiguous or oversized identification chunk')
            if not payload and len(self.data) != total:
                raise ValueError('Premature identification completion')
            self.total = total
            self.sequence = frame['sequence']
            self.data.extend(payload)
            self.complete = not payload
        else:
            if self.total is not None or not self.minimum <= len(payload) <= 58:
                raise ValueError('Invalid single identification reply')
            self.data.extend(payload)
            self.complete = True
        ack = None
        if options & 0x10:
            received = len(self.data)
            remaining = self.total - received if chunked else 0
            # struct gip_pkt_acknowledge: unknown, command, options, length,
            # two padding bytes, remaining (all lengths little endian).
            body = bytes((0, self.command, 0x20)) + received.to_bytes(2, 'little')
            body += bytes(2) + remaining.to_bytes(2, 'little')
            ack = bytes((1, 0x20, frame['sequence'], len(body))) + body
        return bytes(self.data) if self.complete else None, ack


def describe(payload):
    """Bounds-checked decoding of xone's identification offset tables."""
    payload = bytes(payload)
    if not 32 <= len(payload) <= 4096:
        raise ValueError('Invalid identification descriptor size')
    data = payload[16:]
    names = ('client_commands', 'firmware_versions', 'audio_formats',
             'capabilities_out', 'capabilities_in', 'classes', 'interfaces',
             'hid_descriptor')
    offsets = {name: int.from_bytes(data[i * 2:i * 2 + 2], 'little')
               for i, name in enumerate(names)}

    def element(name, size):
        offset = offsets[name]
        if offset == 0:
            return []
        if offset < 16 or offset >= len(data):
            raise ValueError('Invalid ' + name + ' offset')
        count = data[offset]
        end = offset + 1 + count * size
        if end > len(data):
            raise ValueError('Truncated ' + name + ' table')
        return [data[i:i + size] for i in range(offset + 1, end, size)]

    result = {'offsets': offsets,
              'client_commands': [{'command': item[2], 'length': item[3],
                                   'options': item[7], 'raw': item.hex()}
                                  for item in element('client_commands', 23)],
              'firmware_versions': [[int.from_bytes(item[:2], 'little'),
                                     int.from_bytes(item[2:], 'little')]
                                    for item in element('firmware_versions', 4)],
              'interfaces': [str(uuid.UUID(bytes_le=item))
                             for item in element('interfaces', 16)]}
    for name in ('audio_formats', 'capabilities_out', 'capabilities_in', 'hid_descriptor'):
        result[name] = b''.join(element(name, 2 if name == 'audio_formats' else 1)).hex()
    result['classes'] = []
    pos = offsets['classes']
    if pos:
        if not 16 <= pos < len(data):
            raise ValueError('Invalid class table offset')
        count = data[pos]
        pos += 1
        for _ in range(count):
            if pos + 2 > len(data):
                raise ValueError('Truncated class length')
            length = int.from_bytes(data[pos:pos + 2], 'little')
            pos += 2
            if not length or pos + length > len(data):
                raise ValueError('Truncated class string')
            result['classes'].append(data[pos:pos + length].decode('utf-8', 'replace').rstrip('\0'))
            pos += length
    return result
