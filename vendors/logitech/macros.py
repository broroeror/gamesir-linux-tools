"""
Onboard macro serializer (G402 macro format, feature 0x8100).
=============================================================
libratbag only READS macros (and degrades any macro to one keystroke on write),
so we author the encoder ourselves by inverting its reader. A macro is a stream
of mostly-3-byte opcodes living in a free sector (6..15); a button points at it
with a 4-byte binding [0x00, sector, 0x00, offset] (see onboard.Button.macro_ptr).

Opcodes we emit (only these are known-good from libratbag's reader):
    DELAY        [0x40][hi][lo]   time = big-endian u16 milliseconds
    KEY_PRESS    [0x43][mod][key] key = HID usage (page 0x07); mod = modifier bitmask
    KEY_RELEASE  [0x44][mod][key]
    JUMP         [0x60][offset][page]   (offset before page) — not used yet
    NOOP         [0x00]           1 byte
    END          [0xFF]           1 byte, terminator

The reader pins the byte index to a 16-byte "line" (a 3-byte record may only start
at offset%16 in {0,3,6,9,12}). Whether that's real firmware behaviour or a reader
simplification is unverified, so v1 keeps a macro to a SINGLE 16-byte line and
resolves multi-line/JUMP chaining empirically later. `fits_one_line()` guards it.
"""

import onboard      # for crc16_ccitt

OP_DELAY = 0x40
OP_KEY_PRESS = 0x43
OP_KEY_RELEASE = 0x44
OP_JUMP = 0x60
OP_NOOP = 0x00
OP_END = 0xFF
LINE = 16

MOD = {'ctrl': 0x01, 'shift': 0x02, 'alt': 0x04, 'meta': 0x08}
_NAMED = {'space': 0x2C, 'enter': 0x28, 'return': 0x28, 'tab': 0x2B,
          'esc': 0x29, 'backspace': 0x2A}


def key_usage(ch):
    """Single character / key name -> HID usage (page 0x07). Lowercase only for
    letters in v1 (no auto-shift)."""
    ch = ch.lower()
    if ch in _NAMED:
        return _NAMED[ch]
    if len(ch) == 1 and 'a' <= ch <= 'z':
        return 0x04 + (ord(ch) - ord('a'))
    if len(ch) == 1 and '1' <= ch <= '9':
        return 0x1E + (ord(ch) - ord('1'))
    if ch == '0':
        return 0x27
    if ch == ' ':
        return 0x2C
    raise ValueError(f'unsupported macro key: {ch!r}')


def press(key, mod=0):
    return bytes([OP_KEY_PRESS, mod, key])


def release(key, mod=0):
    return bytes([OP_KEY_RELEASE, mod, key])


def delay(ms):
    ms = max(0, min(0xFFFF, int(ms)))
    return bytes([OP_DELAY, (ms >> 8) & 0xFF, ms & 0xFF])


END = bytes([OP_END])


def type_text(text, per_key_delay_ms=0):
    """Serialize 'type this text' into a macro body (press+release per char)."""
    body = bytearray()
    for ch in text:
        u = key_usage(ch)
        body += press(u)
        body += release(u)
        if per_key_delay_ms:
            body += delay(per_key_delay_ms)
    body += END
    return bytes(body)


def fits_one_line(body):
    return len(body) <= LINE


def to_sector(body, sector_size, crc=False, offset=0):
    """Full sector image: macro at `offset`, 0xFF fill everywhere else. G HUB does
    NOT put a CRC on macro sectors (they end in 0xFF, unlike profile sectors) — and
    a valid CRC may even make the firmware read the sector as a (corrupt) profile —
    so CRC defaults OFF. crc=True only to experiment. `offset` places the macro
    body partway into the sector: G HUB points buttons at offset 0x74, never 0, so
    offset is the lever for the "does offset 0 matter?" experiment."""
    if offset < 0 or offset + len(body) > sector_size:
        raise ValueError('macro does not fit at that offset in one sector')
    sect = bytearray(b'\xff' * sector_size)
    sect[offset:offset + len(body)] = body
    if crc:
        c = onboard.crc16_ccitt(bytes(sect[:sector_size - 2]))
        sect[sector_size - 2:sector_size] = c.to_bytes(2, 'big')
    return bytes(sect)


def walk(data):
    """Linear single-line decoder (valid for fits_one_line bodies): press /
    release / delay / jump = 3 bytes, noop = 1, stop at END. Does NOT model the
    16-byte line-boundary drop or JUMP page-follow the firmware reader does — it
    only round-trip-verifies what we emit for a one-line macro."""
    out = []
    i = 0
    names = {OP_DELAY: 'delay', OP_KEY_PRESS: 'press', OP_KEY_RELEASE: 'release', OP_JUMP: 'jump'}
    while i < len(data):
        op = data[i]
        if op == OP_END:
            out.append(('end',))
            break
        if op == OP_NOOP:
            out.append(('noop',))
            i += 1
            continue
        if op in names:
            if i + 2 >= len(data):
                out.append(('truncated', op))
                break
            out.append((names[op], data[i + 1], data[i + 2]))
            i += 3
            continue
        out.append(('unknown', op))
        break
    return out


def describe(body):
    """Human-readable one-liner for a macro body."""
    parts = []
    for rec in walk(body):
        if rec[0] == 'press':
            parts.append(f'↓0x{rec[2]:02x}' + (f'+m{rec[1]:02x}' if rec[1] else ''))
        elif rec[0] == 'release':
            parts.append(f'↑0x{rec[2]:02x}')
        elif rec[0] == 'delay':
            parts.append(f'wait {(rec[1] << 8) | rec[2]}ms')
        elif rec[0] == 'end':
            parts.append('END')
        else:
            parts.append(str(rec))
    return ' '.join(parts)
