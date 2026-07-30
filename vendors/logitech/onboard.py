"""
Logitech onboard-profile codec (feature 0x8100)
===============================================
Decode of the 256-byte onboard-profile memory sector for the G502-family
(profile_format 0x05). READ path only for now — the write path (with
read-modify-write to preserve the bytes libratbag blows away, plus a real macro
engine) comes next. Offsets verified against libratbag `union
hidpp20_internal_profile` and Solaar `OnboardProfile.from_bytes`.

256-byte layout:
   0      report-rate interval in ms      (Hz = 1000 / interval)
   1      default-resolution INDEX into resolutions[5]
   2      shift-resolution INDEX  (the sniper / DPI-shift stage)
   3..12  resolutions[5]  uint16 LITTLE-ENDIAN
  13..15  profile RGB
  16      power mode      17  angle snapping
  18..19  write_count (LE)                 20..27 reserved
  28..29  powersave timeout (LE)           30..31 poweroff timeout (LE)
  32..95  buttons[16]           primary action table (4 bytes each)
  96..159 gbuttons[16]          G-SHIFT / second layer (4 bytes each)
 160..207 name                  48 bytes, UTF-16LE, 0xFF-filled = unnamed
 208..251 lighting[4]           4 x 11-byte LED effect blocks
 252      custom-animation index (X-PLUS/G705 only)   253 free
 254..255 CRC-16/CCITT-FALSE over bytes 0..253, big-endian trailer

A 4-byte button binding, discriminated by the HIGH NIBBLE of byte0 (behavior):
  0x0/0x1/0x2  MACRO exec/stop/stop-all  -> pointer {sector, address} into macro memory
  0x8          SEND (a HID output)       -> byte1 = mapping type:
                 0x1 mouse button (BE mask)  0x2 modifier+key  0x3 consumer key  0x0 none
  0x9          FUNCTION (built-in action) -> byte1 = ButtonFunction (SHIFT_DPI=0x7, G_SHIFT=0xB, ...)
  0xF          unset (ff ff ff ff)
"""

from dataclasses import dataclass, field

PROFILE_SIZE = 256
N_BUTTONS = 16
N_RESOLUTIONS = 5

# button behavior = byte0 >> 4
BEHAVIOR_MACRO_EXECUTE = 0x0
BEHAVIOR_MACRO_STOP = 0x1
BEHAVIOR_MACRO_STOP_ALL = 0x2
BEHAVIOR_SEND = 0x8
BEHAVIOR_FUNCTION = 0x9
BEHAVIOR_UNSET = 0xF

# SEND mapping types (byte1)
MAP_NO_ACTION = 0x0
MAP_BUTTON = 0x1
MAP_MODIFIER_AND_KEY = 0x2
MAP_CONSUMER_KEY = 0x3

# FUNCTION ids (byte1) — the built-in behaviours; the two that matter most are
# SHIFT_DPI (the sniper button) and G_SHIFT (the second-layer trigger).
FUNCTION_NAMES = {
    0x0: 'no-action', 0x1: 'tilt-left', 0x2: 'tilt-right', 0x3: 'next-dpi',
    0x4: 'prev-dpi', 0x5: 'cycle-dpi', 0x6: 'default-dpi', 0x7: 'shift-dpi(sniper)',
    0x8: 'next-profile', 0x9: 'prev-profile', 0xA: 'cycle-profile', 0xB: 'G-SHIFT',
    0xC: 'battery-status', 0xD: 'profile-select', 0xE: 'mode-switch',
    0xF: 'host-button', 0x10: 'scroll-down', 0x11: 'scroll-up',
}


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). Matches Solaar/device;
    check value for b'123456789' is 0x29B1."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Button:
    """One decoded button binding (primary or G-Shift bank). Carries structured
    operands so encode() can rebuild the 4 bytes from fields (not just copy raw),
    which is what makes the decode->encode round-trip a real correctness test."""
    raw: bytes
    behavior: int
    kind: str = 'unset'          # macro | send-button | send-key | send-consumer | send-none | function | unset | unknown
    detail: str = ''
    # structured operands, set per kind; consumed by encode()
    mouse_mask: int = 0
    modifiers: int = 0
    key: int = 0
    consumer: int = 0
    function: int = 0
    data: int = 0
    param: int = 0xFF        # FUNCTION byte2 (0xFF tilt/cycle, 0x00 shift-dpi, ...)
    macro_sector: int = 0
    macro_address: int = 0

    @classmethod
    def decode(cls, b):
        b = bytes(b)
        beh = b[0] >> 4
        if beh == BEHAVIOR_UNSET and b == b'\xff\xff\xff\xff':
            return cls(b, beh, 'unset', '(empty)')
        if beh in (BEHAVIOR_MACRO_EXECUTE, BEHAVIOR_MACRO_STOP):
            # only exec/stop carry a {sector, address} pointer into macro memory
            sector = ((b[0] & 0x0F) << 8) | b[1]
            address = (b[2] << 8) | b[3]
            verb = 'exec' if beh == BEHAVIOR_MACRO_EXECUTE else 'stop'
            return cls(b, beh, 'macro', f'macro {verb} @sector 0x{sector:04x}+0x{address:04x}',
                       macro_sector=sector, macro_address=address)
        if beh == BEHAVIOR_MACRO_STOP_ALL:
            # stop-all takes no operand; rare — encode() reproduces raw for it
            return cls(b, beh, 'unknown', 'macro stop-all')
        if beh == BEHAVIOR_SEND:
            mtype = b[1]
            if mtype == MAP_BUTTON:
                mask = (b[2] << 8) | b[3]
                return cls(b, beh, 'send-button', f'mouse button mask 0x{mask:04x}', mouse_mask=mask)
            if mtype == MAP_MODIFIER_AND_KEY:
                return cls(b, beh, 'send-key', f'key 0x{b[3]:02x} mods 0x{b[2]:02x}',
                           modifiers=b[2], key=b[3])
            if mtype == MAP_CONSUMER_KEY:
                c = (b[2] << 8) | b[3]
                return cls(b, beh, 'send-consumer', f'consumer 0x{c:04x}', consumer=c)
            if mtype == MAP_NO_ACTION:
                return cls(b, beh, 'send-none', 'no-action')
            return cls(b, beh, 'unknown', f'send mtype 0x{mtype:02x}')
        if beh == BEHAVIOR_FUNCTION:
            name = FUNCTION_NAMES.get(b[1], f'fn 0x{b[1]:02x}')
            data = f' data 0x{b[3]:02x}' if b[3] else ''
            return cls(b, beh, 'function', f'{name}{data}', function=b[1], data=b[3], param=b[2])
        return cls(b, beh, 'unknown', b.hex())

    # --- constructors (build a NEW binding to write, vs decode an existing one) ---
    @classmethod
    def disabled(cls):
        return cls(b'\xff\xff\xff\xff', 0xF, 'unset', '(empty)')

    @classmethod
    def mouse(cls, mask):
        return cls(b'', BEHAVIOR_SEND, 'send-button',
                   f'mouse button mask 0x{mask:04x}', mouse_mask=mask)

    @classmethod
    def key(cls, key, modifiers=0):
        return cls(b'', BEHAVIOR_SEND, 'send-key',
                   f'key 0x{key:02x} mods 0x{modifiers:02x}', modifiers=modifiers, key=key)

    @classmethod
    def function_(cls, func, data=0, param=0xFF):
        return cls(b'', BEHAVIOR_FUNCTION, 'function',
                   FUNCTION_NAMES.get(func, f'fn 0x{func:02x}'),
                   function=func, data=data, param=param)

    @classmethod
    def sniper(cls):
        # shift-dpi; byte2=0x00 is what this device stores (observed on profiles 3-5)
        return cls.function_(0x07, param=0x00)

    @classmethod
    def gshift_trigger(cls):
        # G-Shift activation button; param 0xFF matches tilt/cycle — VERIFY on device
        return cls.function_(0x0B, param=0xFF)

    @classmethod
    def macro_ptr(cls, sector, address=0):
        # MACRO_EXECUTE button: 4-byte pointer [0x00, sector, 0x00, offset] into
        # macro memory. behavior 0x0 -> encode() emits the pointer form.
        return cls(b'', BEHAVIOR_MACRO_EXECUTE, 'macro',
                   f'macro @sector 0x{sector:04x}+0x{address:04x}',
                   macro_sector=sector, macro_address=address)

    def encode(self):
        """Rebuild the 4-byte binding from structured fields. Kinds we don't fully
        model (unset, unknown, macro stop-all) reproduce the original bytes, so a
        decode->encode round-trip stays byte-exact."""
        k = self.kind
        if k == 'send-button':
            return bytes([0x80, MAP_BUTTON, (self.mouse_mask >> 8) & 0xFF, self.mouse_mask & 0xFF])
        if k == 'send-key':
            return bytes([0x80, MAP_MODIFIER_AND_KEY, self.modifiers & 0xFF, self.key & 0xFF])
        if k == 'send-consumer':
            return bytes([0x80, MAP_CONSUMER_KEY, (self.consumer >> 8) & 0xFF, self.consumer & 0xFF])
        if k == 'send-none':
            return bytes([0x80, MAP_NO_ACTION, 0xFF, 0xFF])
        if k == 'function':
            # byte2 is a per-function parameter (0xFF for tilt/cycle-profile, 0x00
            # for shift-dpi) carried in `param` — from raw on decode, or the
            # constructor on a freshly-built binding.
            return bytes([0x90, self.function & 0xFF, self.param & 0xFF, self.data & 0xFF])
        if k == 'macro':
            return bytes([((self.behavior & 0x0F) << 4) | ((self.macro_sector >> 8) & 0x0F),
                          self.macro_sector & 0xFF,
                          (self.macro_address >> 8) & 0xFF, self.macro_address & 0xFF])
        return bytes(self.raw)     # unset / unknown / stop-all


@dataclass
class OnboardProfile:
    """A decoded 256-byte onboard profile."""
    raw: bytes
    sector: int = 0
    enabled: int = 1
    report_rate_ms: int = 0
    default_dpi_index: int = 0
    shift_dpi_index: int = 0
    resolutions: list = field(default_factory=list)
    rgb: tuple = (0, 0, 0)
    write_count: int = 0
    name: str = ''
    buttons: list = field(default_factory=list)
    gbuttons: list = field(default_factory=list)   # the G-Shift second layer
    crc_stored: int = 0
    crc_computed: int = 0

    @property
    def report_rate_hz(self):
        return round(1000 / self.report_rate_ms) if self.report_rate_ms else 0

    @property
    def crc_ok(self):
        return self.crc_stored == self.crc_computed

    @property
    def gshift_configured(self):
        """True if the G-Shift bank holds any real binding (not all-empty).
        All-unset here means either never used OR wiped by a libratbag/Piper
        write (which blanks the sector and never rewrites this bank)."""
        return any(g.kind != 'unset' for g in self.gbuttons)

    @classmethod
    def decode(cls, raw, sector=0, enabled=1):
        raw = bytes(raw)
        size = len(raw)
        # CRC-16/CCITT trailer = the LAST 2 bytes of the sector, over the rest.
        # This device's sector is 255 bytes (getInfo says 255 AND the firmware
        # rejects any read past offset 239), so the CRC is at [253:255] over
        # [:253] — NOT the 256-byte [254:256] we first assumed. The device
        # refusing byte 255, plus the CCITT residue math (feeding the CRC's own
        # high byte yields (CRC_low<<8) because table[0]==0), both settled it.
        # Field offsets (0..207) are identical either way, so size-agnostic CRC
        # is the only change needed.
        crc_stored = int.from_bytes(raw[-2:], 'big') if size >= 2 else 0
        crc_computed = crc16_ccitt(raw[:-2]) if size >= 2 else 0
        resolutions = [int.from_bytes(raw[3 + i * 2:5 + i * 2], 'little')
                       for i in range(N_RESOLUTIONS)]
        try:
            name = raw[160:208].decode('utf-16le').rstrip('\x00').rstrip('￿')
        except Exception:
            name = ''
        buttons = [Button.decode(raw[32 + i * 4:36 + i * 4]) for i in range(N_BUTTONS)]
        gbuttons = [Button.decode(raw[96 + i * 4:100 + i * 4]) for i in range(N_BUTTONS)]
        return cls(
            raw=raw, sector=sector, enabled=enabled,
            report_rate_ms=raw[0],
            default_dpi_index=raw[1], shift_dpi_index=raw[2],
            resolutions=resolutions,
            rgb=(raw[13], raw[14], raw[15]),
            write_count=int.from_bytes(raw[18:20], 'little'),
            name=name, buttons=buttons, gbuttons=gbuttons,
            crc_stored=crc_stored, crc_computed=crc_computed,
        )

    def to_bytes(self):
        """Re-encode to the sector bytes via READ-MODIFY-WRITE: start from the
        original `raw` and overlay only the fields we model, so unmodeled regions
        (power mode, angle-snap, reserved, timeouts, lighting) are PRESERVED —
        the opposite of libratbag's blank-the-whole-sector approach, which is what
        wipes G-Shift. The CRC is recomputed over everything but the trailing 2
        bytes. `to_bytes(decode(raw)) == raw` iff our field encoders are exact."""
        buf = bytearray(self.raw)
        if len(buf) < 32 + N_BUTTONS * 4:
            return bytes(buf)
        buf[0] = self.report_rate_ms & 0xFF
        buf[1] = self.default_dpi_index & 0xFF
        buf[2] = self.shift_dpi_index & 0xFF
        for i in range(N_RESOLUTIONS):
            buf[3 + i * 2:5 + i * 2] = int(self.resolutions[i]).to_bytes(2, 'little')
        buf[13:16] = bytes(self.rgb)
        buf[18:20] = int(self.write_count).to_bytes(2, 'little')
        for i in range(N_BUTTONS):
            buf[32 + i * 4:36 + i * 4] = self.buttons[i].encode()
        for i in range(N_BUTTONS):
            buf[96 + i * 4:100 + i * 4] = self.gbuttons[i].encode()
        # Only overwrite the name region when a name is actually set. An empty
        # name is preserved from raw — this device fills it with 0x00 (not the
        # 0xFF Solaar assumes), so preserving raw sidesteps the convention.
        if self.name:
            buf[160:208] = self._encode_name()
        crc = crc16_ccitt(bytes(buf[:-2]))
        buf[-2:] = crc.to_bytes(2, 'big')
        return bytes(buf)

    def _encode_name(self):
        # 48 bytes: UTF-16LE, up to 24 chars, NUL-padded. Only called for a
        # non-empty name (empty names are preserved from raw by to_bytes).
        return self.name[:24].ljust(24, '\x00').encode('utf-16le')

    # --- editing API: mutate fields; to_bytes() serializes via read-modify-write ---
    def set_button(self, i, btn):
        self.buttons[i] = btn

    def set_gshift(self, i, btn):
        self.gbuttons[i] = btn

    def set_report_rate_hz(self, hz):
        self.report_rate_ms = max(1, round(1000 / hz))

    def set_dpi(self, index, value):
        self.resolutions[index] = int(value)

    def dump(self):
        lines = [
            f'Profile @sector 0x{self.sector:04x} '
            f'{"(enabled)" if self.enabled else "(disabled)"}'
            f'{"  name=" + repr(self.name) if self.name else ""}',
            f'  report rate : {self.report_rate_hz} Hz ({self.report_rate_ms} ms)',
            f'  DPI stages  : {self.resolutions}  '
            f'(default idx {self.default_dpi_index}, shift/sniper idx {self.shift_dpi_index})',
            f'  RGB         : {self.rgb}   write_count: {self.write_count}',
            f'  CRC         : stored 0x{self.crc_stored:04x} '
            f'{"== OK" if self.crc_ok else "!= computed 0x%04x  ** MISMATCH **" % self.crc_computed}',
            '  buttons (primary):',
        ]
        for i, b in enumerate(self.buttons):
            if b.kind != 'unset':
                lines.append(f'    #{i:<2} {b.kind:<13} {b.detail}')
        lines.append(f'  G-Shift layer: '
                     f'{"CONFIGURED" if self.gshift_configured else "EMPTY (never set, or wiped by a Piper write)"}')
        for i, g in enumerate(self.gbuttons):
            if g.kind != 'unset':
                lines.append(f'    G#{i:<2} {g.kind:<13} {g.detail}')
        return '\n'.join(lines)
