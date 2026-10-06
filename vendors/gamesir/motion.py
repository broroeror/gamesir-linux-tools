"""GameSir motion (gyro) config — map-driven.

The Cyclone, G7 Pro and 8K gyro blocks differ (base, field offsets, curve point-count,
deadzone width, feature set), so the ADDRESSES live in each controller profile's
`motion` dict and every function here takes that map (`mp`). Shared enums live
here. DATA ONLY; the bridge does the reads/writes.

motion map keys (section = Aim; Tilt = same fields + `tilt_offset`):
  act_method, xaxis, xy_scale, output      : single-byte enum/scalar addrs
  sens                                      : sensitivity addr, or None
  act_buttons                               : tuple of 1..3 combo-slot addrs (0xff empty)
  dz_min, dz_max, dz_wide                   : deadzone; max is 16-bit BE /1000 if dz_wide
  adz_min, adz_max, adz_wide                : anti-deadzone, same shape
  curve, curve_npts                         : block base (type@curve, int@+1, pts@+2), N pts
  inverts                                   : tuple of (label, addr)
  xaxis_gates_inverts                       : bool (Roll/Yaw inverts gated by X-axis mode)
  tilt_offset                               : int, or None if the model has no Tilt
Optional G7 Pro overrides: xaxis_modes, outputs, buttons, tilt_inverts (absolute
addresses, None for absent fields), curve_points_offset, curve_presets,
curve_mode_only_custom, curve_strength, direction_empty, overlap_area,
range_sensitivity (a convenience control over the existing input endpoint).
"""
import math

import vendors.gamesir.config as cfg

ACT_METHODS = [("Off", 0x00), ("Hold", 0x01), ("Press to switch", 0x02), ("Always on", 0x03)]
OUTPUTS     = [("Left Stick", 0x01), ("Right Stick", 0x02),
               ("Directional Macros", 0x03), ("Mouse", 0x04)]
XAXIS_MODES = [("Yaw", 0x02), ("Roll", 0x03), ("Both", 0x01)]
CURVE_TYPES = [("Linear", 0x00), ("Curve", 0x01), ("S-Curve", 0x02), ("Custom", 0x03)]
ACT_BTN_EMPTY = 0xff
ACT_BUTTONS = [(n, c) for n, c in cfg.REMAP_TARGETS if c != 0xff]

# Curve control-point presets @ intensity 100, per point-count (captured: 8K=5pt
# caps 14b, Cyclone=3pt cap 26). Lower intensity warps toward transpose() (0=inverse,
# 50=linear) via cfg.warp_points. Linear is used verbatim (intensity ignored).
CURVE_PRESETS = {
    5: {'linear': [(18, 19), (65, 67), (128, 128), (190, 188), (237, 236)],
        1:         [(64, 10), (122, 38), (176, 79), (217, 133), (245, 191)],
        2:         [(18, 54), (66, 94), (128, 128), (189, 161), (237, 201)]},
    3: {'linear': [(39, 39), (129, 128), (216, 216)],
        1:         [(94, 23), (176, 79), (232, 161)],
        2:         [(40, 77), (128, 128), (215, 179)]},
}


def _index_of(table, code, default=0):
    for i, (_n, c) in enumerate(table):
        if c == code:
            return i
    return default


# --- deadzone min/max <-> percent (min is a byte 0..100; max is byte/100 or 16-bit/1000)
def dz_min_from(vals, addr):      return min(100, vals[addr][0])
def dz_min_bytes(pct):            return [max(0, min(100, int(pct)))]

def dz_max_from(vals, addr, wide):
    b = vals[addr]
    return round(((b[0] << 8) | b[1]) / 10.0) if wide else min(100, b[0])

def dz_max_bytes(pct, wide):
    pct = max(0, min(100, int(pct)))
    if wide:
        v = pct * 10                          # 0..1000
        return [(v >> 8) & 0xff, v & 0xff]
    return [pct]


def range_sensitivity(dz_min, dz_max):
    """Input-span compression relative to dz_max=100, not an IMU gain.

    The curve's output span and points stay unchanged. This describes the
    input range only; nonlinear curves and game settings affect actual aim.
    Degenerate ranges have no meaningful multiplier.
    """
    if not 0 <= dz_min < dz_max <= 100:
        return None
    return (100 - dz_min) / (dz_max - dz_min)


def sensitivity_dz_max(dz_min, multiplier):
    """Keep the lower deadzone and compress only the upper input endpoint."""
    if not 0 <= dz_min < 100 or not math.isfinite(multiplier):
        return None
    span = 100 - dz_min
    multiplier = max(1.0, min(float(span), multiplier))
    return dz_min + max(1, round(span / multiplier))


# --- curve --------------------------------------------------------------------
def curve_points_for(npts, type_idx, intensity, custom_pts=None):
    presets = CURVE_PRESETS[npts]
    if type_idx == 1:    return cfg.warp_points(presets[1], intensity)
    if type_idx == 2:    return cfg.warp_points(presets[2], intensity)
    if type_idx == 3:    return list(custom_pts) if custom_pts else presets['linear']
    return presets['linear']


def curve_block(npts, type_idx, intensity, custom_pts=None):
    """Block at `curve`: [type, intensity, x0,y0 .. ]. Firmware shapes from the LUT."""
    pts = curve_points_for(npts, type_idx, intensity, custom_pts)[:npts]
    flat = []
    for x, y in pts:
        flat += [max(0, min(255, int(x))), max(0, min(255, int(y)))]
    return [CURVE_TYPES[type_idx][1], max(0, min(100, int(intensity)))] + flat


# --- reads / decode -----------------------------------------------------------
def sections(mp):
    """[(name, offset)] — Aim always; Tilt only if the model has it."""
    out = [("Aim", 0x00)]
    if mp.get('tilt_offset') is not None:
        out.append(("Tilt", mp['tilt_offset']))
    return out


def enum_table(mp, field):
    return mp.get({'xaxis': 'xaxis_modes', 'output': 'outputs'}.get(field, ''),
                  {'act_method': ACT_METHODS, 'xaxis': XAXIS_MODES, 'output': OUTPUTS}.get(field))


def invert_addrs(mp, off):
    if off and 'tilt_inverts' in mp:
        return mp['tilt_inverts']
    return tuple(a + off for _label, a in mp['inverts'])


def curve_payload(mp, type_idx, intensity=100):
    """Captured model-specific presets; Custom may select its existing LUT only."""
    if mp.get('curve_mode_only_custom') and type_idx == 3:
        return [3]
    if 'curve_presets' in mp:
        return list(mp['curve_presets'][type_idx])
    return curve_block(mp['curve_npts'], type_idx, intensity)


def read_addrs(mp):
    """(addr, length) reads populating the whole motion view (all sections)."""
    reads = []
    for _name, off in sections(mp):
        singles = [mp['act_method'], mp['xaxis'], mp['output'],
                   mp['dz_min'], mp['adz_min']] + list(mp['act_buttons']) \
                  + [mp['xy_scale']]
        if mp.get('sens') is not None:
            singles.append(mp['sens'])
        reads += [(a + off, 1) for a in singles]
        reads += [(a, 1) for a in invert_addrs(mp, off) if a is not None]
        if 'overlap_area' in mp:
            reads.append((mp['overlap_area'] + off, 1))
        reads += [(mp['dz_max'] + off, 2 if mp['dz_wide'] else 1),
                  (mp['adz_max'] + off, 2 if mp['adz_wide'] else 1)]
        reads += [(mp['curve'] + off, 1), (mp['curve'] + 1 + off, 1)]
        point_off = mp.get('curve_points_offset', 2)
        reads += [(mp['curve'] + point_off + off + 2 * i, 2) for i in range(mp['curve_npts'])]
        reads += [(a + off, 1) for a in mp.get('dir_macros', ())]
    return reads


def decode_section(mp, vals, off):
    g = lambda a: vals[a + off][0]
    enum = lambda field: _index_of(enum_table(mp, field), g(mp[field]),
                                  mp.get('enum_unknown_index', 0))
    d = {
        'act_method':  enum('act_method'),
        'act_slots':   [g(a) for a in mp['act_buttons']],
        'xaxis':       enum('xaxis'),
        'dz_min':      dz_min_from(vals, mp['dz_min'] + off),
        'dz_max':      dz_max_from(vals, mp['dz_max'] + off, mp['dz_wide']),
        'adz_min':     dz_min_from(vals, mp['adz_min'] + off),
        'adz_max':     dz_max_from(vals, mp['adz_max'] + off, mp['adz_wide']),
        'curve_type':  _index_of(CURVE_TYPES, g(mp['curve'])),
        'curve_int':   g(mp['curve'] + 1),
        'curve_points': [list(vals[mp['curve'] + mp.get('curve_points_offset', 2) + off + 2 * i])
                         for i in range(mp['curve_npts'])],
        'xy_scale':    g(mp['xy_scale']),
        'output':      enum('output'),
        'sens':        g(mp['sens']) if mp.get('sens') is not None else 50,
        'dir_macros':  [g(a) for a in mp.get('dir_macros', ())],
    }
    for i, addr in enumerate(invert_addrs(mp, off)):
        d['invert_%d' % i] = bool(vals[addr][0]) if addr is not None else False
    if 'overlap_area' in mp:
        d['overlap_area'] = g(mp['overlap_area'])
    return d


def is_blank_section(mp, sec):
    """True when a decoded section's storage looks uninitialised: a response
    curve whose points are all zero, which no real curve is. (An axis mode the
    app doesn't name is NOT a sign of blankness -- the Wuchang's real Tilt block
    stores 0x02 there, and the PR's own tests caught that.) Only models with
    `default_blocks` can be repaired, so only they are ever reported blank."""
    if 'default_blocks' not in mp or not sec:
        return False
    pts = sec.get('curve_points') or []
    return bool(pts) and all(list(p) == [0, 0] for p in pts)


def decode_block(mp, name, off, block):
    """Decode one section from its raw storage block (as staged, not as read)."""
    base = mp['act_method'] + off
    vals = {}
    for a, n in read_addrs(mp):
        i = a - base
        vals[a] = list(block[i:i + n]) if 0 <= i and i + n <= len(block) else [0] * n
    return decode_section(mp, vals, off)
