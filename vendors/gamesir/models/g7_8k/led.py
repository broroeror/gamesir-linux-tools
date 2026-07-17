"""GameSir G7 Pro 8K lighting + device settings (bank 0x20).

The 8K has NO addressable/keyframe RGB like the Cyclone (see gamesir_led). Its
only light is the power/home indicator — a 4-quadrant ring — plus a global effect
mode and brightness, and a few device settings (auto power, sleep, dock LED). All
are single-register writes in bank 0x20, reverse-engineered from the official
app's USBPcap captures (Controller Testing/G7 Pro 8k/, caps 3/4/5/6/9/10/11).

This module is DATA ONLY (register map + encode/decode). The bridge performs the
reads/writes so it can pin the write-style + session generation like every other
vendor write.
"""

BANK = 0x20

MODE = 0x0000          # ring effect (see MODES)
BRIGHT = 0x0001        # controller light brightness 0..100
# 4 home-ring quadrants, 4 bytes each: [hue_hi, hue_lo, sat, bright] — i.e. the
# official app's H/S/B picker. HUE IS 16-BIT BIG-ENDIAN and holds the angle in
# DEGREES (0..359) directly — there is no scaling or colour correction (verified
# against cap 52, where H=30/60/.../240 wrote byte 30/60/.../240 and H=359 wrote
# 0x0167). The official app writes only the low byte while the high byte is
# unchanged, which is why a naive 8-bit read looks like a 0..255 "hue byte" —
# treating it as 8-bit caps the ring at 255deg (purple) and leaves a stale high
# byte that offsets every later edit by 256deg. Always write hue as both bytes.
HOME_Q = (0x000c, 0x0010, 0x0014, 0x0018)
QUAD_LEN = 4           # bytes per quadrant block
HUE_MAX = 359          # degrees; the ring covers the full wheel
AUTO_ONOFF = 0x00a0    # 0/1
SLEEP_TIMER = 0x00a1   # minutes; 0 = off
DOCK_MODE = 0x00a2     # 0 follow battery / 1 follow animation
DOCK_BRIGHT = 0x00a3   # dock LED brightness 0..100

# (name, code) — confirmed live on the 8K (2026-07-08). The capture guess was
# off-by-one because "static" was already active when cap 3 started.
MODES = [("Off", 0x00), ("Static", 0x01), ("Colorful", 0x04), ("Rainbow", 0x03)]
SLEEP_OPTIONS = [("Off", 0), ("1 min", 1), ("5 min", 5), ("10 min", 10), ("20 min", 20)]
DOCK_MODES = [("Follow battery", 0), ("Follow animation", 1)]

QUAD_INTENSITY = 0x64  # captures always wrote full intensity for a quadrant colour

# "Load defaults" baseline, byte-for-byte as the official app writes it (cap 8,
# 8_default_profile: one bank-0x20 block at 0x0006). Decodes as zone levels, then
# the four quadrant blocks all at hue 60deg (0x3c) / sat 100 / bright 100 — i.e.
# the factory ring is yellow. Restoring lighting = replay this block.
FACTORY_START = 0x0006
FACTORY_DATA = [0x32, 0x32, 0x32, 0x32, 0x00, 0x00,
                0x00, 0x3c, 0x64, 0x64,      # Q1
                0x00, 0x3c, 0x64, 0x64,      # Q2
                0x00, 0x3c, 0x64, 0x64,      # Q3
                0x00, 0x3c, 0x64, 0x64,      # Q4
                0x00, 0x3c, 0x64]


def quad_block(hue, sat):
    """Encode a quadrant colour: hue in DEGREES (0..359) as 16-bit big-endian,
    then saturation. Stops short of the 4th byte (brightness) so we don't clobber
    whatever the ring already has there."""
    hue = max(0, min(HUE_MAX, int(hue)))
    return [(hue >> 8) & 0xFF, hue & 0xFF, max(0, min(100, int(sat)))]


def quad_hue(block):
    """Decode the 16-bit big-endian hue (degrees) from a quadrant block."""
    return ((block[0] << 8) | block[1]) if len(block) >= 2 else 0


def read_fields():
    """(bank, addr, length) reads that populate the whole lighting/device view."""
    return ([(BANK, MODE, 1), (BANK, BRIGHT, 1)]
            + [(BANK, a, QUAD_LEN) for a in HOME_Q]
            + [(BANK, AUTO_ONOFF, 1), (BANK, SLEEP_TIMER, 1),
               (BANK, DOCK_MODE, 1), (BANK, DOCK_BRIGHT, 1)])


def mode_index(code):
    for i, (_n, c) in enumerate(MODES):
        if c == code:
            return i
    return 0


def sleep_index(minutes):
    for i, (_n, m) in enumerate(SLEEP_OPTIONS):
        if m == minutes:
            return i
    return 0
