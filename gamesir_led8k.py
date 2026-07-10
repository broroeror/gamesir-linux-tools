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
HOME_Q = (0x000d, 0x0011, 0x0015, 0x0019)   # 4 quadrants; each = [hue 0..255, intensity]
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


def read_fields():
    """(bank, addr, length) reads that populate the whole lighting/device view."""
    return ([(BANK, MODE, 1), (BANK, BRIGHT, 1)]
            + [(BANK, a, 2) for a in HOME_Q]
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
