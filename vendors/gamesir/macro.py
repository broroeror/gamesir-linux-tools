"""GameSir per-paddle macro encoding (bank = active profile).

Each back paddle (Cyclone: L4/R4; 8K: L4/R4/L5/R5) can hold a macro — a sequence
of button/key events played when the paddle is pressed. It lives inside the
paddle's 0xa9 register block, relative to the paddle's REMAP_SLOTS base address:
  base+0x05 : enable (01 = macro active, 00 = normal remap)
  base+0x08 : event count
  base+0x09 : events, 5 bytes each = [target_code, hold_ms(BE16), delay_ms(BE16)]
`target_code` reuses the remap target table (A=0x09 ..) plus keyboard codes
(0x28+). hold = how long the input is held; delay = pause after, before the next
event. Reverse-engineered from USBPcap (caps 12_full_macro, 15c_macro_timing).

DATA ONLY (encode/decode). The bridge does the reads/writes so it can pin the
write-style + session generation like every other vendor write. The whole macro
also shares the paddle block with the remap record, so enabling a macro and
remapping the same paddle are mutually exclusive in the UI.
"""
import vendors.gamesir.config as cfg

ENABLE_OFF = 0x05
COUNT_OFF  = 0x08
EVENTS_OFF = 0x09
EVENT_LEN  = 5
DEFAULT_MS = 100          # app default hold/delay per event

# Max steps is paddle-block dependent (8K fits 32, Cyclone 30) — passed in per
# controller. A single read reply only carries ~55 B, so the event region is
# read in chunks. MAX_EVENTS is just a safe default when no max is supplied.
MAX_EVENTS = 32
READ_CHUNK = 50          # bytes per event-region read (< one reply's ~55 B)

# Buttons pickable as macro event targets (gamepad targets, minus the Disabled
# sentinel). Keyboard/mouse targets are a later addition.
TARGETS = [(n, c) for n, c in cfg.REMAP_TARGETS if c != 0xff]


def _event_chunks(base, max_events):
    """(addr, length) reads covering the event region, split to fit one reply."""
    out, off, total = [], 0, max_events * EVENT_LEN
    while off < total:
        ln = min(READ_CHUNK, total - off)
        out.append((base + EVENTS_OFF + off, ln))
        off += ln
    return out


def read_addrs(base, max_events=MAX_EVENTS):
    """(addr, length) reads for one paddle's macro: enable, count, event region."""
    return [(base + ENABLE_OFF, 1), (base + COUNT_OFF, 1)] + _event_chunks(base, max_events)


def target_index(code):
    for i, (_n, c) in enumerate(TARGETS):
        if c == code:
            return i
    return 0


def decode(vals, base, max_events=MAX_EVENTS):
    """Build a paddle's macro state {enable, events:[{target,hold,delay}]}."""
    enable = bool(vals[base + ENABLE_OFF][0])
    count = min(vals[base + COUNT_OFF][0], max_events)
    raw = []
    for addr, _ln in _event_chunks(base, max_events):
        raw += list(vals[addr])
    events = []
    for i in range(count):
        o = i * EVENT_LEN
        if o + EVENT_LEN > len(raw):
            break
        events.append({'target': raw[o],
                       'hold':  (raw[o + 1] << 8) | raw[o + 2],
                       'delay': (raw[o + 3] << 8) | raw[o + 4]})
    return {'enable': enable, 'events': events}


def _event_bytes(ev):
    tgt = int(ev.get('target', TARGETS[0][1])) & 0xff
    hold = max(0, min(0xffff, int(ev.get('hold', DEFAULT_MS))))
    delay = max(0, min(0xffff, int(ev.get('delay', DEFAULT_MS))))
    return [tgt, (hold >> 8) & 0xff, hold & 0xff, (delay >> 8) & 0xff, delay & 0xff]


def block_bytes(events, max_events=MAX_EVENTS):
    """[count, event0, event1, ...] to write at base+COUNT_OFF."""
    evs = list(events)[:max_events]
    out = [len(evs)]
    for ev in evs:
        out += _event_bytes(ev)
    return out
