"""
Onboard macro engine (HID++ 2.0 "macro format 1", feature 0x8100)
=================================================================
A macro is a stream of opcodes stored in a free sector (6..15); a button points
at it with a 4-byte binding [0x00, sector, addr_hi, addr_lo] (see
onboard.Button.macro_ptr). The firmware runs the stream from the pointed offset
until an END (0xFF) opcode.

This module is the SERIALIZER + DECODER: it builds macro bytecode from a friendly
`Macro` builder and decodes/describes it back. It does not touch the device — the
write path (allocator + CLI) lives in macro.py, on top of hidpp.write_full_sector_no_crc.

Opcode set (from cvuchener/hidpp MacroFormat.cpp, cross-checked vs libratbag
hidpp20.h; the ones marked ✓ are additionally VERIFIED on our G502 X). Operand
length is encoded in the top 3 bits: (op>>5)&3 -> 0,1,2,4 payload bytes, so
0x00-family=1B, 0x20-family=2B, 0x40-family=3B, 0x60-family=5B; END (0xFF) is a
1-byte terminator.

    0x00 NOOP                 (1B)
    0x01 WAIT_RELEASE         (1B)  wait until the trigger button is released
    0x02 REPEAT_UNTIL_RELEASE (1B)  loop the macro while the button is held
    0x03 REPEAT_FOREVER       (1B)
    0x20 MOUSE_WHEEL   [i8]         (2B)
    0x21 MOUSE_HWHEEL  [i8]         (2B)
    0x40 DELAY         [BE u16 ms]  (3B) ✓
    0x41 MOUSE_PRESS   [BE u16 mask](3B)  mask bit (n-1) = button n
    0x42 MOUSE_RELEASE [BE u16 mask](3B)
    0x43 KEY_PRESS     [mod][key]   (3B) ✓  key = HID usage (page 0x07)
    0x44 KEY_RELEASE   [mod][key]   (3B) ✓
    0x45 CONSUMER_PRESS   [BE u16]  (3B)  consumer-page usage
    0x46 CONSUMER_RELEASE [BE u16]  (3B)
    0x60 JUMP  [mem_type][page][BE u16 offset]  (5B)  chain across sectors
    0x61 MOUSE_MOVE [BE i16 x][BE i16 y]        (5B)
    0xFF END                  (1B) ✓

A bare press/release stream is a clean ONE-SHOT per button press (verified live on
the G502 X). REPEAT_* / WAIT_RELEASE are opt-in for hold-to-repeat behaviour.
"""

import onboard      # for crc16_ccitt (used by to_sector's optional crc path)

# --- opcodes -----------------------------------------------------------------
OP_NOOP = 0x00
OP_WAIT_RELEASE = 0x01
OP_REPEAT_UNTIL_RELEASE = 0x02
OP_REPEAT_FOREVER = 0x03
OP_MOUSE_WHEEL = 0x20
OP_MOUSE_HWHEEL = 0x21
OP_DELAY = 0x40
OP_MOUSE_PRESS = 0x41
OP_MOUSE_RELEASE = 0x42
OP_KEY_PRESS = 0x43
OP_KEY_RELEASE = 0x44
OP_CONSUMER_PRESS = 0x45
OP_CONSUMER_RELEASE = 0x46
OP_JUMP = 0x60
OP_MOUSE_MOVE = 0x61
OP_END = 0xFF

END = bytes([OP_END])
LINE = 16      # kept for callers that still probe fits_one_line (not a real limit)

# modifier bitmask (byte on KEY_PRESS/RELEASE)
MOD = {'ctrl': 0x01, 'shift': 0x02, 'alt': 0x04, 'meta': 0x08, 'gui': 0x08,
       'super': 0x08, 'win': 0x08,
       'rctrl': 0x10, 'rshift': 0x20, 'ralt': 0x40, 'rmeta': 0x80}

# named non-printable keys -> HID usage (page 0x07)
_NAMED = {
    'space': 0x2C, 'enter': 0x28, 'return': 0x28, 'tab': 0x2B, 'esc': 0x29,
    'escape': 0x29, 'backspace': 0x2A, 'bksp': 0x2A, 'delete': 0x4C, 'del': 0x4C,
    'insert': 0x49, 'ins': 0x49, 'home': 0x4A, 'end': 0x4D,
    'pageup': 0x4B, 'pgup': 0x4B, 'pagedown': 0x4E, 'pgdn': 0x4E,
    'up': 0x52, 'down': 0x51, 'left': 0x50, 'right': 0x4F, 'capslock': 0x39,
    'printscreen': 0x46, 'prtsc': 0x46, 'scrolllock': 0x47, 'pause': 0x48,
    'menu': 0x65, 'app': 0x65,
    # function keys — F13..F24 (0x68..0x73) for MMO / macro keybinds
    'f1': 0x3A, 'f2': 0x3B, 'f3': 0x3C, 'f4': 0x3D, 'f5': 0x3E, 'f6': 0x3F,
    'f7': 0x40, 'f8': 0x41, 'f9': 0x42, 'f10': 0x43, 'f11': 0x44, 'f12': 0x45,
    'f13': 0x68, 'f14': 0x69, 'f15': 0x6A, 'f16': 0x6B, 'f17': 0x6C, 'f18': 0x6D,
    'f19': 0x6E, 'f20': 0x6F, 'f21': 0x70, 'f22': 0x71, 'f23': 0x72, 'f24': 0x73,
    # numpad (numlock-on usages)
    'numlock': 0x53, 'numdivide': 0x54, 'nummultiply': 0x55, 'numminus': 0x56,
    'numplus': 0x57, 'numenter': 0x58, 'numdot': 0x63,
    'num0': 0x62, 'num1': 0x59, 'num2': 0x5A, 'num3': 0x5B, 'num4': 0x5C,
    'num5': 0x5D, 'num6': 0x5E, 'num7': 0x5F, 'num8': 0x60, 'num9': 0x61,
}

# consumer-control (media) usages (page 0x0C) -> name, for the Media popout
CONSUMER = {
    0xCD: 'Play/Pause', 0xB5: 'Next', 0xB6: 'Previous', 0xB7: 'Stop',
    0xE9: 'Vol +', 0xEA: 'Vol -', 0xE2: 'Mute',
    0x192: 'Calculator', 0x223: 'Browser Home', 0x221: 'Search',
}

# US-layout printable char -> (HID usage, needs_shift). Built once below.
_UNSHIFTED = {
    '`': 0x35, '-': 0x2D, '=': 0x2E, '[': 0x2F, ']': 0x30, '\\': 0x31,
    ';': 0x33, "'": 0x34, ',': 0x36, '.': 0x37, '/': 0x38, ' ': 0x2C,
    '\n': 0x28, '\t': 0x2B,
}
# shifted char -> the unshifted char that shares its physical key
_SHIFTED_PAIR = {
    '~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6',
    '&': '7', '*': '8', '(': '9', ')': '0', '_': '-', '+': '=', '{': '[',
    '}': ']', '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
}


def _digit_usage(d):
    return 0x27 if d == '0' else 0x1E + (ord(d) - ord('1'))


def char_to_key(ch):
    """A single printable character -> (HID usage, needs_shift). Raises
    ValueError for anything we can't type. US layout."""
    if 'a' <= ch <= 'z':
        return 0x04 + (ord(ch) - ord('a')), False
    if 'A' <= ch <= 'Z':
        return 0x04 + (ord(ch.lower()) - ord('a')), True
    if '0' <= ch <= '9':
        return _digit_usage(ch), False
    if ch in _UNSHIFTED:
        return _UNSHIFTED[ch], False
    if ch in _SHIFTED_PAIR:
        base = _SHIFTED_PAIR[ch]
        u, _ = char_to_key(base)
        return u, True
    raise ValueError(f'unsupported macro character: {ch!r}')


def key_usage(name):
    """A key NAME or single char -> HID usage (page 0x07), ignoring shift.
    Accepts named keys ('enter', 'f5', 'left'), single letters/digits/symbols."""
    low = name.lower()
    if low in _NAMED:
        return _NAMED[low]
    if len(name) == 1:
        return char_to_key(name)[0]
    raise ValueError(f'unsupported macro key: {name!r}')


def parse_combo(combo):
    """'ctrl+shift+c' / 'alt+f4' / 'meta+left' -> (modifier_mask, key_usage).
    The last token is the key; earlier tokens are modifiers."""
    parts = [p.strip() for p in combo.split('+') if p.strip()]
    if not parts:
        raise ValueError('empty key combo')
    mods = 0
    for p in parts[:-1]:
        if p.lower() not in MOD:
            raise ValueError(f'unknown modifier: {p!r}')
        mods |= MOD[p.lower()]
    return mods, key_usage(parts[-1])


# --- low-level opcode emitters ----------------------------------------------
def noop():
    return bytes([OP_NOOP])


def wait_release():
    return bytes([OP_WAIT_RELEASE])


def repeat_until_release():
    return bytes([OP_REPEAT_UNTIL_RELEASE])


def repeat_forever():
    return bytes([OP_REPEAT_FOREVER])


def delay(ms):
    ms = max(0, min(0xFFFF, int(ms)))
    return bytes([OP_DELAY, (ms >> 8) & 0xFF, ms & 0xFF])


def press(key, mod=0):
    return bytes([OP_KEY_PRESS, mod & 0xFF, key & 0xFF])


def release(key, mod=0):
    return bytes([OP_KEY_RELEASE, mod & 0xFF, key & 0xFF])


def mouse_press(mask):
    return bytes([OP_MOUSE_PRESS, (mask >> 8) & 0xFF, mask & 0xFF])


def mouse_release(mask):
    return bytes([OP_MOUSE_RELEASE, (mask >> 8) & 0xFF, mask & 0xFF])


def consumer_press(code):
    return bytes([OP_CONSUMER_PRESS, (code >> 8) & 0xFF, code & 0xFF])


def consumer_release(code):
    return bytes([OP_CONSUMER_RELEASE, (code >> 8) & 0xFF, code & 0xFF])


def wheel(delta):
    return bytes([OP_MOUSE_WHEEL, delta & 0xFF])          # i8 two's-complement


def hwheel(delta):
    return bytes([OP_MOUSE_HWHEEL, delta & 0xFF])


def jump(sector, offset=0):
    """JUMP (0x60): continue execution at (sector, offset) — how a macro chains
    across sectors when its bytecode outgrows one. The 4 operand bytes use the
    SAME addressing as the button macro pointer ([sector BE, offset BE]; the high
    byte doubles as the mem_type field, 0x00 = writeable onboard flash)."""
    return bytes([OP_JUMP, (sector >> 8) & 0xFF, sector & 0xFF,
                  (offset >> 8) & 0xFF, offset & 0xFF])


def split_body(body, sector_size, max_sectors):
    """Split macro bytecode at OPCODE boundaries into chunks that each fit one
    sector with 5 bytes reserved for the chaining JUMP appended to every chunk
    but the last (which keeps the stream's own END). Returns [chunk, ...];
    raises ValueError on malformed bytecode or > max_sectors chunks."""
    budget = sector_size - 5
    chunks, cur, i = [], bytearray(), 0
    while i < len(body):
        n = opcode_len(body[i])
        if n is None or i + n > len(body):
            raise ValueError('malformed macro bytecode (bad opcode boundary)')
        if len(cur) + n > budget:
            chunks.append(bytes(cur))
            cur = bytearray()
        cur += body[i:i + n]
        i += n
    if cur:
        chunks.append(bytes(cur))
    if len(chunks) > max_sectors:
        raise ValueError(f'macro needs {len(chunks)} sectors (max {max_sectors})')
    return chunks


# --- Macro builder -----------------------------------------------------------
class Macro:
    """Fluent builder for a macro body. Every method returns self so calls chain.
    `.build()` appends END and returns the bytecode. Example:
        Macro().combo('ctrl+c').pause(50).combo('ctrl+v').build()
        Macro().type('Hello!').build()
    """

    def __init__(self):
        self.ops = bytearray()

    def _add(self, b):
        self.ops += b
        return self

    # keyboard
    def tap(self, key, mod=0):
        """Press then release a key usage (with optional modifier mask)."""
        return self._add(press(key, mod) + release(key, mod))

    def tap_name(self, name, mod=0):
        return self.tap(key_usage(name), mod)

    def combo(self, spec):
        """'ctrl+shift+c' -> press mods+key, release key+mods."""
        mods, key = parse_combo(spec)
        return self._add(press(key, mods) + release(key, mods))

    def press_key(self, key, mod=0):
        return self._add(press(key, mod))

    def release_key(self, key, mod=0):
        return self._add(release(key, mod))

    def type(self, text):
        """Type a string, auto-shifting for uppercase and shifted symbols.
        Each char is a discrete press+release (shift wraps the char when needed)."""
        for ch in text:
            u, shift = char_to_key(ch)
            mod = MOD['shift'] if shift else 0
            self._add(press(u, mod) + release(u, mod))
        return self

    # timing / control
    def pause(self, ms):
        return self._add(delay(ms))

    def wait_release(self):
        return self._add(wait_release())

    def repeat_until_release(self):
        return self._add(repeat_until_release())

    def repeat_forever(self):
        return self._add(repeat_forever())

    # mouse
    @staticmethod
    def _btn_mask(button):
        if button < 1:
            raise ValueError(f'mouse button must be >= 1 (got {button})')
        return 1 << (button - 1)

    def click(self, button):
        """Press+release a mouse button (1=left,2=right,3=middle,...)."""
        mask = self._btn_mask(button)
        return self._add(mouse_press(mask) + mouse_release(mask))

    def mouse_down(self, button):
        return self._add(mouse_press(self._btn_mask(button)))

    def mouse_up(self, button):
        return self._add(mouse_release(self._btn_mask(button)))

    def scroll(self, delta):
        return self._add(wheel(delta))

    def consumer(self, code):
        return self._add(consumer_press(code) + consumer_release(code))

    def build(self, terminate=True):
        body = bytes(self.ops)
        return body + END if terminate else body


# --- convenience constructors (backward-compatible module functions) ---------
def type_text(text, per_key_delay_ms=0):
    """Serialize 'type this text' into a macro body (press+release per char,
    auto-shift). Optional inter-key delay. Kept for existing callers."""
    m = Macro()
    for ch in text:
        u, shift = char_to_key(ch)
        mod = MOD['shift'] if shift else 0
        m._add(press(u, mod) + release(u, mod))
        if per_key_delay_ms:
            m.pause(per_key_delay_ms)
    return m.build()


def fits_one_line(body):
    return len(body) <= LINE


def to_sector(body, sector_size, crc=False, offset=0):
    """Full sector image: macro at `offset`, 0xFF fill everywhere else. G HUB does
    NOT put a CRC on macro sectors (they end in 0xFF, unlike profile sectors) — and
    a valid CRC may even make the firmware read the sector as a (corrupt) profile —
    so CRC defaults OFF. crc=True only to experiment. `offset` places the macro
    body partway into the sector (G HUB points buttons at offset 0x74, never 0)."""
    if offset < 0 or offset + len(body) > sector_size:
        raise ValueError('macro does not fit at that offset in one sector')
    sect = bytearray(b'\xff' * sector_size)
    sect[offset:offset + len(body)] = body
    if crc:
        c = onboard.crc16_ccitt(bytes(sect[:sector_size - 2]))
        sect[sector_size - 2:sector_size] = c.to_bytes(2, 'big')
    return bytes(sect)


# --- decoder -----------------------------------------------------------------
def opcode_len(op):
    """Total byte length of an opcode record, from the top-3-bits rule.
    END is a 1-byte terminator; op>=0x80 (other than END) is unknown."""
    if op == OP_END:
        return 1
    if op >= 0x80:
        return None                       # unknown / not decodable
    return 1 + (0, 1, 2, 4)[(op >> 5) & 0x03]


_NAMES = {
    OP_NOOP: 'noop', OP_WAIT_RELEASE: 'wait-release',
    OP_REPEAT_UNTIL_RELEASE: 'repeat-until-release', OP_REPEAT_FOREVER: 'repeat-forever',
    OP_MOUSE_WHEEL: 'wheel', OP_MOUSE_HWHEEL: 'hwheel', OP_DELAY: 'delay',
    OP_MOUSE_PRESS: 'mouse-press', OP_MOUSE_RELEASE: 'mouse-release',
    OP_KEY_PRESS: 'press', OP_KEY_RELEASE: 'release',
    OP_CONSUMER_PRESS: 'consumer-press', OP_CONSUMER_RELEASE: 'consumer-release',
    OP_JUMP: 'jump', OP_MOUSE_MOVE: 'mouse-move', OP_END: 'end',
}


def walk(data, start=0, max_ops=512):
    """Decode a macro stream from `start` until END (or bad/again-truncated data).
    Uses the opcode-length rule so it handles every opcode width correctly.
    Returns a list of tuples: (name, *operand_bytes). Terminates at 'end'."""
    out = []
    i = start
    for _ in range(max_ops):
        if i >= len(data):
            out.append(('truncated',))
            break
        op = data[i]
        n = opcode_len(op)
        if n is None:
            out.append(('unknown', op))
            break
        if i + n > len(data):
            out.append(('truncated', op))
            break
        name = _NAMES.get(op, f'op0x{op:02x}')
        out.append((name, *data[i + 1:i + n]))
        if op == OP_END:
            break
        i += n
    return out


def describe(body, start=0):
    """Human-readable one-liner for a macro body."""
    parts = []
    for rec in walk(body, start):
        n = rec[0]
        if n == 'press':
            parts.append(f'↓0x{rec[2]:02x}' + (f'+m{rec[1]:02x}' if rec[1] else ''))
        elif n == 'release':
            parts.append(f'↑0x{rec[2]:02x}')
        elif n == 'delay':
            parts.append(f'wait {(rec[1] << 8) | rec[2]}ms')
        elif n in ('mouse-press', 'mouse-release'):
            parts.append(f'{"↓" if n == "mouse-press" else "↑"}mouse0x{(rec[1] << 8) | rec[2]:04x}')
        elif n in ('consumer-press', 'consumer-release'):
            parts.append(f'{n} 0x{(rec[1] << 8) | rec[2]:04x}')
        elif n == 'wheel':
            parts.append(f'wheel {rec[1] - 256 if rec[1] > 127 else rec[1]:+d}')
        elif n == 'hwheel':
            parts.append(f'hwheel {rec[1] - 256 if rec[1] > 127 else rec[1]:+d}')
        elif n == 'end':
            parts.append('END')
        elif n in ('noop', 'wait-release', 'repeat-until-release', 'repeat-forever'):
            parts.append(n)
        else:
            parts.append(str(rec))
    return ' '.join(parts)
