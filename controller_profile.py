"""
GameSir controller PROFILES  (multi-controller abstraction)
===========================================================
A `ControllerProfile` bundles everything that differs between GameSir models:
USB identity, the register-write transport, the config register map, and the
enum/block formats. The app selects the profile for whichever controller is
plugged in, so the rest of the stack (bridge, editor) works against one
controller = one profile of addresses, instead of hard-coded Cyclone constants.

Key reverse-engineering result that makes this tidy: across GameSir's vendor
family the *internal* layout of the trigger and stick config blocks is IDENTICAL
(hair at base+0x09, curve at base+0x0d, stick DZ at base+0x02, RT mirror +0x1c,
RS mirror +0x20). Only the block BASE addresses move between models. Likewise the
curve-block format, hair-trigger modes, trajectory codes and remap TARGET codes
are shared. So a profile is mostly: {USB PID, a handful of base addresses}.

Two profiles are defined:
  * CYCLONE  - GameSir Cyclone 2 (3537:0575 / 3537:100b). Sourced from the
               existing, battle-tested `gamesir_config` so there is a single
               source of truth for the Cyclone and nothing changes for it.
  * G7       - GameSir G7 (3537:10ba). From the G7 USB-capture RE (see the
               `g7-protocol-findings` memory).

Runtime wiring (making the bridge apply/read against the active profile, plus
the G7 write envelope and GIP input parsing) is the next stage; this module is
the data + detection foundation and is safe to import without touching Cyclone.
"""

from dataclasses import dataclass, field
from typing import Optional

import gamesir_config as _cy


# --- shared enums / block formats (identical across the vendor family) -------
# Response curves (shared 10-byte format for triggers and sticks):
#   [type, 0x64, 0x00, 0x00, x0,y0, x1,y1, x2,y2]
# type: 0x00 linear, 0x01 curve/concave, 0x02 s-curve, 0x03 custom (user points)
CURVE_BLOCKS = list(_cy.CURVE_BLOCKS)      # reuse the exact captured presets
CURVE_NAMES = [n for n, _ in CURVE_BLOCKS]
CURVE_ITEMS = CURVE_NAMES + ['Custom']

# Hair-trigger: mode byte + a couple of neighbours the app replays.
HAIR_MODES = list(_cy.HAIR_MODES)          # Off / Adaptive / Fixed

TRAJ = list(_cy.TRAJ)                       # ('Circle',0)/('Raw',1)

# Button remap TARGET codes: confirmed shared between Cyclone and G7 (A=0x09,
# B=0x0a, X=0x0b, Y=0x0c, LB=0x05..RT=0x14). See gamesir_config.REMAP_TARGETS.
REMAP_TARGETS = list(_cy.REMAP_TARGETS)
REMAP_NONE = _cy.REMAP_NONE
REMAP_ITEMS = [REMAP_NONE] + [n for n, _ in REMAP_TARGETS]


@dataclass
class ControllerProfile:
    """One controller model expressed as identity + a register-address map.

    Config addresses are absolute offsets within a profile bank. Fields a model
    lacks are left as None. RT_*/RS_* mirror addresses are derived in
    __post_init__ from the LT_/ST_ bases plus the per-model mirror offset.
    """
    name: str                              # display name
    short: str                             # short label (status line)
    usb_products: tuple                    # USB product ids that identify it
    write_style: str = 'cyclone'           # 'cyclone' bare 0f03 / 'g7' enveloped
    input_style: str = 'cyclone_0x12'      # 'cyclone_0x12' (vendor hidraw) / 'evdev'
    dz_wide: bool = False                   # analog stick/trigger deadzones are
                                           # 16-bit big-endian = percent×10 (0..1000,
                                           # the 8K high-rate block) vs 8-bit % (Cyclone)
    stick_curve_npts: int = 3               # stick response-curve control points
                                           # (8K sticks use 5, everything else 3)
    trigger_curve_npts: int = 3             # trigger response-curve control points
    profile_banks: tuple = (1, 2, 3, 4)    # banks that hold editable profiles
    can_flash: bool = False                # firmware flasher supports this model
                                           # (gamesir_flash is Cyclone/BR23-only)
    factory_reset: bool = False            # a captured factory-default image exists
                                           # (gamesir_factory bytes are Cyclone-only)
    flash_identity: Optional[str] = None   # product-id string in the chip's own
                                           # flash header (raw offset 0x1010). The
                                           # flasher reads it IN the loader and
                                           # refuses to write unless it matches --
                                           # a version-independent, brick-proof
                                           # check that the target really is this
                                           # controller and not a 2.4GHz dongle
                                           # (which reads 'GS_C2_Dongle' there).

    # capability hints for the editor UI (which pages/logic a model supports).
    # The whole `gamesir_led` module assumes the Cyclone keyframe/palette RGB, so
    # only 'cyclone_keyframe' models may be driven through it; others must not.
    lighting_style: str = 'none'    # 'cyclone_keyframe' / 'simple_8k' / 'none'
    has_motion: bool = False        # gyro Aim/Tilt config (8K)
    has_macros: bool = False        # per-paddle macro editor

    # vibration
    VIB_L: Optional[int] = None
    VIB_R: Optional[int] = None

    # poll / report rate (address AND encoding vary; see poll_rates)
    POLL_RATE: Optional[int] = None
    POLL_RATES: tuple = tuple(_cy.POLL_RATES)

    # trigger block: LT base + these fixed intra-block offsets, RT = +RT_OFFSET
    LT_DZ_MIN: Optional[int] = None
    LT_DZ_MAX: Optional[int] = None
    LT_ADZ_MIN: Optional[int] = None
    LT_ADZ_MAX: Optional[int] = None
    LT_HAIR: Optional[int] = None
    LT_CURVE: Optional[int] = None
    RT_OFFSET: int = 0x1c

    # stick block: LS base fields, RS = +RS_OFFSET
    ST_TRAJ: Optional[int] = None
    ST_DZ_MIN: Optional[int] = None
    ST_DZ_MAX: Optional[int] = None
    ST_ADZ_MIN: Optional[int] = None
    ST_ADZ_MAX: Optional[int] = None
    ST_CURVE: Optional[int] = None
    RS_OFFSET: int = 0x20

    # enum/format tables (shared defaults; a model can override)
    TRAJ: tuple = tuple(TRAJ)
    HAIR_MODES: tuple = tuple(HAIR_MODES)
    CURVE_BLOCKS: tuple = tuple(CURVE_BLOCKS)
    REMAP_TARGETS: tuple = tuple(REMAP_TARGETS)
    REMAP_SLOTS: tuple = ()                 # (name, addr) source-button records
    MACRO_SLOTS: tuple = ()                 # (name, addr) paddles that hold macros
    macro_max: int = 32                     # max macro steps (paddle-block dependent)
    motion: dict = field(default_factory=dict)   # per-controller gyro block map

    # model-specific registers not in the common set (name -> addr), e.g. the
    # G7's trigger-vibration, resolution, dpad options and dock settings.
    extras: dict = field(default_factory=dict)

    # RT_*/RS_* derived mirrors (filled by __post_init__)
    RT_DZ_MIN: Optional[int] = field(default=None, init=False)
    RT_DZ_MAX: Optional[int] = field(default=None, init=False)
    RT_ADZ_MIN: Optional[int] = field(default=None, init=False)
    RT_ADZ_MAX: Optional[int] = field(default=None, init=False)
    RT_HAIR: Optional[int] = field(default=None, init=False)
    RT_CURVE: Optional[int] = field(default=None, init=False)
    RS_TRAJ: Optional[int] = field(default=None, init=False)
    RS_DZ_MIN: Optional[int] = field(default=None, init=False)
    RS_DZ_MAX: Optional[int] = field(default=None, init=False)
    RS_ADZ_MIN: Optional[int] = field(default=None, init=False)
    RS_ADZ_MAX: Optional[int] = field(default=None, init=False)
    RS_CURVE: Optional[int] = field(default=None, init=False)

    def __post_init__(self):
        def mirror(base, off):
            return None if base is None else base + off
        self.RT_DZ_MIN = mirror(self.LT_DZ_MIN, self.RT_OFFSET)
        self.RT_DZ_MAX = mirror(self.LT_DZ_MAX, self.RT_OFFSET)
        self.RT_ADZ_MIN = mirror(self.LT_ADZ_MIN, self.RT_OFFSET)
        self.RT_ADZ_MAX = mirror(self.LT_ADZ_MAX, self.RT_OFFSET)
        self.RT_HAIR = mirror(self.LT_HAIR, self.RT_OFFSET)
        self.RT_CURVE = mirror(self.LT_CURVE, self.RT_OFFSET)
        self.RS_TRAJ = mirror(self.ST_TRAJ, self.RS_OFFSET)
        self.RS_DZ_MIN = mirror(self.ST_DZ_MIN, self.RS_OFFSET)
        self.RS_DZ_MAX = mirror(self.ST_DZ_MAX, self.RS_OFFSET)
        self.RS_ADZ_MIN = mirror(self.ST_ADZ_MIN, self.RS_OFFSET)
        self.RS_ADZ_MAX = mirror(self.ST_ADZ_MAX, self.RS_OFFSET)
        self.RS_CURVE = mirror(self.ST_CURVE, self.RS_OFFSET)

    # --- curve format (per side) --------------------------------------------
    # A curve block is [type, intensity, <points>]. 3-point blocks pad two zero
    # bytes after the intensity ([type,int,0,0, x0y0 x1y1 x2y2] = 10B, Cyclone +
    # 8K triggers); 5-point blocks have no padding ([type,int, 5×(x,y)] = 12B, 8K
    # sticks). So "padded" tracks point-count.
    def curve_npts(self, key):
        return self.stick_curve_npts if key in ('st', 'rs') else self.trigger_curve_npts

    def curve_padded(self, key):
        return self.curve_npts(key) == 3

    def curve_len(self, key):
        return (4 if self.curve_padded(key) else 2) + 2 * self.curve_npts(key)

    # --- read plan: (addr, length) reads to populate the editor -------------
    def read_fields(self):
        """(addr, length) pairs for every supported field. Deadzone/anti-deadzone
        read 2 bytes on a 16-bit model (dz_wide) else 1; curve blocks read their
        format length; other scalars read 1. Skips unsupported (None) fields."""
        dzlen = 2 if self.dz_wide else 1
        bytes1 = [self.VIB_L, self.VIB_R, self.POLL_RATE, self.ST_TRAJ, self.RS_TRAJ]
        dz = [self.LT_DZ_MIN, self.LT_DZ_MAX, self.LT_ADZ_MIN, self.LT_ADZ_MAX,
              self.RT_DZ_MIN, self.RT_DZ_MAX, self.RT_ADZ_MIN, self.RT_ADZ_MAX,
              self.ST_DZ_MIN, self.ST_DZ_MAX, self.ST_ADZ_MIN, self.ST_ADZ_MAX,
              self.RS_DZ_MIN, self.RS_DZ_MAX, self.RS_ADZ_MIN, self.RS_ADZ_MAX]
        fields = [(a, 1) for a in bytes1 if a is not None]
        fields += [(a, dzlen) for a in dz if a is not None]
        # Hair-trigger is a [mode, min, max] block: read all 3 so the editor can show
        # the adjustable min/max thresholds, not just the mode.
        fields += [(a, 3) for a in (self.LT_HAIR, self.RT_HAIR) if a is not None]
        for key, base in (('st', self.ST_CURVE), ('rs', self.RS_CURVE),
                          ('lt', self.LT_CURVE), ('rt', self.RT_CURVE)):
            if base is not None:
                fields.append((base, self.curve_len(key)))
        return fields

    def profile_bank(self, profile):
        """Profile number -> register bank (identity map for these models)."""
        return profile if profile in self.profile_banks else None

    def field_labels(self):
        """{addr: human label} for this model's analog/vib/poll/remap fields, so a
        backup names them regardless of model (the 8K's analog addresses differ from
        the Cyclone's, so a flat address table can't cover both)."""
        pairs = [
            (self.VIB_L, 'Vibration L'), (self.VIB_R, 'Vibration R'),
            (self.POLL_RATE, 'Poll rate'),
            (self.ST_TRAJ, 'Left stick trajectory'), (self.RS_TRAJ, 'Right stick trajectory'),
            (self.LT_DZ_MIN, 'LT deadzone min'), (self.LT_DZ_MAX, 'LT deadzone max'),
            (self.LT_ADZ_MIN, 'LT anti-deadzone min'), (self.LT_ADZ_MAX, 'LT anti-deadzone max'),
            (self.LT_HAIR, 'LT hair-trigger'), (self.LT_CURVE, 'LT response curve'),
            (self.RT_DZ_MIN, 'RT deadzone min'), (self.RT_DZ_MAX, 'RT deadzone max'),
            (self.RT_ADZ_MIN, 'RT anti-deadzone min'), (self.RT_ADZ_MAX, 'RT anti-deadzone max'),
            (self.RT_HAIR, 'RT hair-trigger'), (self.RT_CURVE, 'RT response curve'),
            (self.ST_DZ_MIN, 'Left stick deadzone min'), (self.ST_DZ_MAX, 'Left stick deadzone max'),
            (self.ST_ADZ_MIN, 'Left stick anti-deadzone min'),
            (self.ST_ADZ_MAX, 'Left stick anti-deadzone max'), (self.ST_CURVE, 'Left stick curve'),
            (self.RS_DZ_MIN, 'Right stick deadzone min'), (self.RS_DZ_MAX, 'Right stick deadzone max'),
            (self.RS_ADZ_MIN, 'Right stick anti-deadzone min'),
            (self.RS_ADZ_MAX, 'Right stick anti-deadzone max'), (self.RS_CURVE, 'Right stick curve'),
        ]
        labels = {a: n for a, n in pairs if a is not None}
        for name, addr in self.REMAP_SLOTS:
            labels[addr] = 'Remap ' + name
        return labels


# --- Cyclone 2 : sourced verbatim from the proven gamesir_config -------------
CYCLONE = ControllerProfile(
    name='GameSir Cyclone 2',
    short='Cyclone 2',
    # 0575 = extras/macro mode, 100b = pure XInput; 1053 = XInput identity of the
    # firmware images in the flash library (a flashed unit enumerates as this).
    usb_products=(0x0575, 0x100b, 0x1053),
    write_style='cyclone',
    input_style='cyclone_0x12',
    profile_banks=(1, 2, 3, 4),
    can_flash=True,                         # the Linux flasher targets the Cyclone
    factory_reset=True,                     # captured Cyclone factory-default image
    # Flash-header identity confirmed against real dumps of fw 3.26 AND 3.52 (the
    # dongle reads 'GS_C2_Dongle' at the same offset). Version-independent.
    flash_identity='GS_C2_ADC_DEVICE',
    lighting_style='cyclone_keyframe',      # the app's LED module IS the Cyclone's
    # Macros use the Cyclone's own RE'd paddle blocks (L4/R4) -> safe + verified.
    has_motion=True,
    has_macros=True,
    # Cyclone motion block (cap 26) — a COMPACT variant of the 8K's: 3-point curve,
    # byte-width deadzone max, single activation button, X/Y inverts, no sensitivity.
    motion={
        'act_method': 0x0266, 'act_buttons': (0x0267,), 'xaxis': 0x0268,
        'dz_min': 0x026a, 'dz_max': 0x026b, 'dz_wide': False,
        'adz_min': 0x026c, 'adz_max': 0x026d, 'adz_wide': False,
        'curve': 0x026f, 'curve_npts': 3,
        'inverts': (('Invert X', 0x027c), ('Invert Y', 0x027d)),
        'xaxis_gates_inverts': False,
        # Tilt block = Aim block + 0x21 (cap 33_cyclone_tilt: ACT_METHOD 0x0266→0x0287,
        # OUTPUT 0x0280→0x02a1, DZ_MIN 0x026a→0x028b — all +0x21). Same layout as Aim.
        'xy_scale': 0x027e, 'output': 0x0280, 'sens': None, 'tilt_offset': 0x21,
        # Directional-Macros output: 4 single-byte target-code slots
        # (top/bottom/left/right), same layout as the 8K (output+2..+5). From
        # cap 31_cyclone_dir_macros: Output=03@0x0280, then 0x0282=A/0x0283=B/
        # 0x0284=X/0x0285=Y written for Up/Down/Left/Right.
        'dir_macros': (0x0282, 0x0283, 0x0284, 0x0285),
    },

    VIB_L=_cy.VIB_L, VIB_R=_cy.VIB_R,
    POLL_RATE=_cy.POLL_RATE,
    LT_DZ_MIN=_cy.LT_DZ_MIN, LT_DZ_MAX=_cy.LT_DZ_MAX,
    LT_ADZ_MIN=_cy.LT_ADZ_MIN, LT_ADZ_MAX=_cy.LT_ADZ_MAX,
    LT_HAIR=_cy.LT_HAIR, LT_CURVE=_cy.LT_CURVE, RT_OFFSET=_cy.RT_OFFSET,
    ST_TRAJ=_cy.ST_TRAJ, ST_DZ_MIN=_cy.ST_DZ_MIN, ST_DZ_MAX=_cy.ST_DZ_MAX,
    ST_ADZ_MIN=_cy.ST_ADZ_MIN, ST_ADZ_MAX=_cy.ST_ADZ_MAX,
    ST_CURVE=_cy.ST_CURVE, RS_OFFSET=_cy.RS_OFFSET,
    REMAP_SLOTS=tuple(_cy.REMAP_SLOTS),
    MACRO_SLOTS=(('L4', 0xb2), ('R4', 0x151)),   # Cyclone has 2 back paddles
    macro_max=30,                                # tighter paddle block (R4 @0x151) -> 30 steps
)


# --- G7 : from the G7 USB-capture reverse-engineering ------------------------
# Config rides the same register protocol as the Cyclone but wrapped in a
# sequenced envelope (write_style='g7'); input is GIP on the interrupt endpoint.
# Trigger LT base 0x00cf (RT +0x1c), stick LS base 0x013d (RS +0x20). The block
# internal offsets match the Cyclone, only the bases differ.
G7 = ControllerProfile(
    name='GameSir G7',
    short='G7',
    usb_products=(0x10ba,),
    write_style='g7',
    input_style='evdev',
    profile_banks=(1,),                     # single editable bank observed
    VIB_L=0x0020, VIB_R=0x0021,             # grip vibration L/R
    POLL_RATE=0x0030,                       # report rate (encoding differs)
    LT_DZ_MIN=0x00cf, LT_DZ_MAX=0x00d0,
    LT_ADZ_MIN=0x00d1, LT_ADZ_MAX=0x00d2,
    LT_HAIR=0x00d8, LT_CURVE=0x00dc, RT_OFFSET=0x1c,
    ST_TRAJ=0x013d, ST_DZ_MIN=0x013f, ST_DZ_MAX=0x0140,
    ST_ADZ_MIN=0x0141, ST_ADZ_MAX=0x0142,
    ST_CURVE=0x0144, RS_OFFSET=0x20,
    # Button remaps: same stride/target codes as the Cyclone, plus L5/R5 paddles.
    REMAP_SLOTS=(
        ('Dpad Up',    0x0042),
        ('RS',         0x0073),
        ('A',          0x007a),
        ('B',          0x0081),
        ('L4',         0x00b2),
        ('L5',         0x00b9),
        ('R4',         0x00c0),
        ('R5',         0x00c7),
    ),
    # G7-only registers, kept here until the editor grows fields for them.
    extras={
        'VIB_TRIG_L': 0x0022, 'VIB_TRIG_R': 0x0023,   # trigger-motor strength
        'VIB_MODE_L': 0x0024, 'VIB_MODE_R': 0x0025,   # 0 off/1 force/2 sync
        'DPAD_SWAP': 0x002b, 'DPAD_LOCK': 0x002d,
        'RESOLUTION': 0x0032,                          # 04=12-bit / 00=8-bit
        'LT_HAIR_MIN': 0x00d9, 'LT_HAIR_MAX': 0x00da,
        'RT_HAIR_MIN': 0x00f5, 'RT_HAIR_MAX': 0x00f6,
        'ST_INVERT_X': 0x0151, 'ST_INVERT_Y': 0x0152, 'ST_SENS': 0x0153,
        'RS_INVERT_X': 0x0171, 'RS_INVERT_Y': 0x0172, 'RS_SENS': 0x0173,
        'DOCK_AUTO': 0x01f6, 'DOCK_BRIGHT': 0x01f9,    # bank 0x20
    },
)


# --- G7 Pro : GameSir G7 Pro (3537:1022) ------------------------------------
# 1022 is the G7 Pro's Linux-default PC/HID identity (HID gamepad on one interface,
# keyboard/mouse/consumer + a vendor 0xfff0 collection on another). Live input comes
# over evdev. The config protocol IS reverse-engineered (see RESEARCH.md) — it lives
# on the pad's *other* identity, the GIP/Xbox 0x10ba face captured as the `G7` profile
# above. It's left unset HERE because on Linux the pad only ever presents 1022, whose
# vendor channel is INERT (stalls reads, ignores writes); reaching the config-capable
# 10ba identity needs a reset-level mode switch Linux can't trigger.
# NOTE: `G7`(0x10ba) and `G7_PRO`(0x1022) are two USB faces of ONE physical device;
# collapsing them into a single G7 Pro profile w/ two identities is a pending TODO.
G7_PRO = ControllerProfile(
    name='GameSir G7 Pro',
    short='G7 Pro',
    usb_products=(0x1022,),
    write_style='g7',
    input_style='evdev',
    profile_banks=(1,),
)


# --- G7 Pro 8K : GameSir G7 Pro 8K (3537:10c7 wired / 3537:10c8 wireless) ----
# Reverse-engineered 2026-07-07 from live vendor-channel probing + 11 USBPcap
# captures of the official app (see the `g7-pro-8k` memory + "Controller Testing/
# G7 Pro 8k/"). Despite a different board it speaks the CYCLONE register protocol
# (bare 0f03 writes, live 0x12 input, 4 profile banks) and its ANALOG config block
# is byte-for-byte the Cyclone's (33/33 register reads matched), so those fields
# reuse `_cy.*` for a single source of truth.
#
# It diverges from the Cyclone in two measured ways:
#   * REMAPS: the standard 12 buttons + L4 sit at the Cyclone addresses, but the
#     extra-paddle blocks are re-spaced (stride 0xa9): L4=0xb2, R4=0x15b (NOT the
#     Cyclone's 0x151), L5=0x204, R5=0x2ad. LT/RT-as-remap-source were not captured
#     and are deliberately omitted until confirmed. Remap record = 7B
#     [type, code, 0,0,0,0,0]: type 0x01=gamepad button (codes = REMAP_TARGETS),
#     0x00=keyboard key; 00 00 = unmapped.
#   * LIGHTING is a single power/home RGB indicator (a 4-quadrant ring) + global
#     device settings, NOT the Cyclone's per-key keyframe RGB. All of it lives in
#     bank 0x20 (see extras) and is GLOBAL, not per-profile.
# Flash is OFF: geometry/loader identity unknown -> can_flash=False, no identity.
G7_8K = ControllerProfile(
    name='GameSir G7 Pro 8K',
    short='G7 Pro 8K',
    usb_products=(0x10c7, 0x10c8),          # 10c7 wired / 10c8 wireless dongle
    write_style='cyclone',                  # bare 0f03 writes (NOT the g7 envelope)
    input_style='cyclone_0x12',             # live 0x12 on the vendor hidraw
    profile_banks=(1, 2, 3, 4),             # 4 profiles, confirmed via the app
    can_flash=False,                        # loader identity + flash geometry unknown
    factory_reset=False,
    flash_identity=None,
    lighting_style='simple_8k',             # mode/brightness/home-ring/dock (bank 0x20);
                                            # NOT the Cyclone keyframe model
    has_motion=True,                        # Aim/Tilt gyro block (bank 0x01)
    has_macros=True,                        # per-paddle macros

    # Vibration + poll ARE shared with the Cyclone (verified live). But the
    # stick/trigger ANALOG SHAPING is NOT — the 8K's high-rate engine reads it
    # from its OWN block at 0x0357-0x03c4 in a 16-bit (percent×10) format, and the
    # Cyclone's 0x01fe/0x022e are a dead zero region on the 8K (the "33/33 match"
    # was READS of default values, not proof the engine uses them). Decoded from
    # captures 34-49 (2026-07-09). So: dz_wide + 8K addresses + 5-point stick curve.
    VIB_L=_cy.VIB_L, VIB_R=_cy.VIB_R,
    POLL_RATE=_cy.POLL_RATE,                # same reg (0x002e) as the Cyclone, but
    POLL_RATES=('250 Hz', '500 Hz', '1000 Hz',   # the 8K exposes a much taller
                '2000 Hz', '4000 Hz', '8000 Hz'),  # ladder: codes 0..5 (live cap 17)
    dz_wide=True, stick_curve_npts=5,       # 16-bit ×10 deadzones; 5-point stick curves
    LT_DZ_MIN=0x0357, LT_DZ_MAX=0x0359,
    LT_ADZ_MIN=0x035b, LT_ADZ_MAX=0x035d,
    LT_HAIR=0x0364, LT_CURVE=0x0368, RT_OFFSET=0x20,  # hair mode @0x0364 (off/adaptive/
                                                      # fixed, same codes+block as Cyclone,
                                                      # cap 50); trigger curve = 3-point
    ST_TRAJ=0x0395, ST_DZ_MIN=0x0397, ST_DZ_MAX=0x0399,
    ST_ADZ_MIN=0x039b, ST_ADZ_MAX=0x039d,
    ST_CURVE=0x03a0, RS_OFFSET=0x24,        # LS→RS stride 0x24 (Cyclone is 0x20)

    # remaps: Cyclone's standard-12 + L4 unchanged, then 8K-specific paddles
    REMAP_SLOTS=tuple(_cy.REMAP_SLOTS[:13]) + (
        ('R4', 0x015b),
        ('L5', 0x0204),
        ('R5', 0x02ad),
    ),
    MACRO_SLOTS=(('L4', 0x00b2), ('R4', 0x015b),   # 8K has 4 back paddles
                 ('L5', 0x0204), ('R5', 0x02ad)),
    # 8K motion block (caps 14/15/27) — full feature set: 5-point curve, 16-bit
    # deadzone max (/1000), 3-button activation combo, Roll/Y/Yaw inverts, sens.
    motion={
        'act_method': 0x03dc, 'act_buttons': (0x03dd, 0x03de, 0x03df), 'xaxis': 0x03e0,
        'dz_min': 0x03e3, 'dz_max': 0x03e4, 'dz_wide': True,
        'adz_min': 0x03e7, 'adz_max': 0x03e8, 'adz_wide': True,
        'curve': 0x03eb, 'curve_npts': 5,
        'inverts': (('Invert Roll', 0x03f8), ('Invert Y', 0x03f9), ('Invert Yaw', 0x03fa)),
        'xaxis_gates_inverts': True,
        'xy_scale': 0x03fb, 'output': 0x03fd, 'sens': 0x0404, 'tilt_offset': 0x29,
        # Directional-Macros output: 4 target-code slots (top/bottom/left/right),
        # each a gamepad/keyboard/mouse code (cap 14c: 09/4e/84/c8). Single byte.
        'dir_macros': (0x03ff, 0x0400, 0x0401, 0x0402),
    },

    # Extra registers documented from USBPcap RE, kept here until the editor
    # grows UI for them; read_fields() (the per-profile editor plan) does NOT
    # touch these. NOTE the two address spaces:
    #   LIGHT_*/HOME_*/AUTO_/SLEEP_/DOCK_*  live in BANK 0x20 (global, not per-profile)
    #   MOTION_*                            live in BANK 0x01 (per-profile)
    extras={
        # --- bank 0x20: lighting + global device settings ---
        'LIGHT_MODE':     0x0000,   # rainbow=00 off=01 colorful=03 static=04
        'LIGHT_BRIGHT':   0x0001,   # 0..100 (levels 0-4 x25)
        'HOME_Q1':        0x000d,   # 4-quadrant home ring, 2B [hue, intensity]
        'HOME_Q2':        0x0011,
        'HOME_Q3':        0x0015,
        'HOME_Q4':        0x0019,
        'AUTO_ONOFF':     0x00a0,   # 0/1
        'SLEEP_TIMER':    0x00a1,   # minutes (0=off)
        'DOCK_LED_MODE':  0x00a2,   # 0=follow battery, 1=follow animation
        'DOCK_LED_BRIGHT':0x00a3,   # 0..100

        # --- bank 0x01: MOTION "Aim" block 0x03dc..0x0404 (addresses confirmed by
        # the clean 15a/15b captures; NOTE Activate-Method and Output were swapped
        # in the earlier 14a guess). "Tilt" is a consecutive ~0x29-byte block
        # starting 0x0405; its fields mirror these at the same intra-block offsets.
        # LT/RT motion tabs still TBD.
        'MOTION_ACT_METHOD':  0x03dc,  # off/hold/press-to-switch/always-on (codes 00-03)
        'MOTION_ACT_BUTTON':  0x03dd,  # reuses remap target codes (none/disabled=0xff)
        'MOTION_XAXIS_MODE':  0x03e0,  # yaw / roll / both (3 options; couples the inverts)
        'MOTION_DZ':          0x03e3,  # deadzone (shaping sub-block 0x03e3..0x03f6)
        'MOTION_ADZ':         0x03e7,  # anti-deadzone
        'MOTION_CURVE_TYPE':  0x03eb,  # 00 linear/01 curve/02 s-curve/03 custom, then points
        'MOTION_INVERT_A':    0x03f8,  # 3 invert bools (Roll/Yaw/Y); editable only for the
        'MOTION_INVERT_B':    0x03f9,  #   axis the X-Axis mode currently exposes
        'MOTION_INVERT_C':    0x03fa,
        'MOTION_XY_SCALE':    0x03fb,  # 0..100 (0=horiz max, 100=vert max, 50=center)
        'MOTION_OUTPUT':      0x03fd,  # LS/RS/Directional/Mouse (codes ~01-04)
        'MOTION_SENS':        0x0404,  # stick sensitivity 0..100 (shared across LS/RS)
        'MOTION_TILT_BASE':   0x0405,  # Tilt block base (Aim+0x29), same field layout
    },
    # MACRO (per-paddle, inside the 0xa9 paddle block; L5 example @0x204):
    #   +0x05 = macro enable(01), +0x08 = event COUNT, +0x09.. = events.
    #   event = 5 bytes: [target_code, hold_ms(BE16), delay_ms(BE16)]; default 100/100.
    #   target_code reuses REMAP_TARGETS (A=09..RT=14) + keyboard codes (0x28+).
)


# --- registry + detection ----------------------------------------------------
ALL = (CYCLONE, G7, G7_PRO, G7_8K)
DEFAULT = CYCLONE


def by_product_id(pid):
    """ControllerProfile for a USB product id, or None if unrecognised."""
    for prof in ALL:
        if pid in prof.usb_products:
            return prof
    return None


def detect(product_ids):
    """Pick a profile from an iterable of connected GameSir product ids.
    Returns the first recognised profile, else None."""
    for pid in product_ids or ():
        prof = by_product_id(pid)
        if prof is not None:
            return prof
    return None


# The ONLY USB product id the Cyclone and the 8K share: a wired Cyclone
# ("GameSir-Cyclone 2") and an IDLE 8K wireless dongle ("Gamepad") both enumerate
# as 3537:0575. Every other Cyclone id (0x100b pure-XInput, 0x1053 flashed) is
# Cyclone-EXCLUSIVE, and the 8K's active ids (0x10c7 wired, 0x10c8 dongle) are
# 8K-exclusive, so only 0x0575 ever needs the product-string tie-breaker.
_SHARED_PID = 0x0575


def detect_one(pid, product=None):
    """Profile for a single device. Only the shared 0x0575 id is ambiguous, so ONLY
    that id consults the product string: a real Cyclone's is "GameSir-Cyclone 2"
    (contains 'cyclone'); the idle 8K dongle's is "Gamepad". Every other id maps
    straight through by_product_id — crucially a Cyclone in pure-XInput mode
    (0x100b, product NOT containing 'cyclone') must stay a Cyclone, not be
    mis-tagged an 8K, which is the "2 Cyclones show as 2 8Ks" bug."""
    prof = by_product_id(pid)
    if (prof is CYCLONE and pid == _SHARED_PID
            and product and 'cyclone' not in product.lower()):
        return G7_8K
    return prof


# --- active profile ----------------------------------------------------------
# The rest of the app addresses the connected controller through the ACTIVE
# profile. The reader sets it on connect (detect -> set_active); everything else
# reads it via active(). Defaults to the Cyclone so behaviour is unchanged when
# nothing is plugged in yet.
_active = DEFAULT
_recognized = False     # True only when the active profile was matched to a
                        # connected controller (not the idle/unknown fallback)


def active():
    """The profile for the currently connected controller (Cyclone default)."""
    return _active


def is_recognized():
    """True when `active()` was matched to a real connected controller. False for
    the idle default (nothing plugged in) or an unrecognised device — callers
    should NOT expose the register editor in that case, since the fallback map is
    the Cyclone's and writing it to an unknown device could corrupt it."""
    return _recognized


def set_active(prof):
    """Set the active profile. None (nothing connected, or an unrecognised
    device) falls back to the default map but marks the profile unrecognised."""
    global _active, _recognized
    _recognized = prof is not None
    _active = prof or DEFAULT
