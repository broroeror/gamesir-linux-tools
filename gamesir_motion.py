"""GameSir motion (gyro) config — map-driven.

The Cyclone and 8K gyro blocks differ (base, field offsets, curve point-count,
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
"""
import gamesir_config as cfg

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


def read_addrs(mp):
    """(addr, length) reads populating the whole motion view (all sections)."""
    reads = []
    for _name, off in sections(mp):
        singles = [mp['act_method'], mp['xaxis'], mp['output'],
                   mp['dz_min'], mp['adz_min']] + list(mp['act_buttons']) \
                  + [a for _l, a in mp['inverts']] + [mp['xy_scale']]
        if mp.get('sens') is not None:
            singles.append(mp['sens'])
        reads += [(a + off, 1) for a in singles]
        reads += [(mp['dz_max'] + off, 2 if mp['dz_wide'] else 1),
                  (mp['adz_max'] + off, 2 if mp['adz_wide'] else 1)]
        reads += [(mp['curve'] + off, 1), (mp['curve'] + 1 + off, 1)]
        reads += [(mp['curve'] + 2 + off + 2 * i, 2) for i in range(mp['curve_npts'])]
        reads += [(a + off, 1) for a in mp.get('dir_macros', ())]
    return reads


def decode_section(mp, vals, off):
    g = lambda a: vals[a + off][0]
    d = {
        'act_method':  _index_of(ACT_METHODS, g(mp['act_method'])),
        'act_slots':   [g(a) for a in mp['act_buttons']],
        'xaxis':       _index_of(XAXIS_MODES, g(mp['xaxis'])),
        'dz_min':      dz_min_from(vals, mp['dz_min'] + off),
        'dz_max':      dz_max_from(vals, mp['dz_max'] + off, mp['dz_wide']),
        'adz_min':     dz_min_from(vals, mp['adz_min'] + off),
        'adz_max':     dz_max_from(vals, mp['adz_max'] + off, mp['adz_wide']),
        'curve_type':  _index_of(CURVE_TYPES, g(mp['curve'])),
        'curve_int':   g(mp['curve'] + 1),
        'curve_points': [list(vals[mp['curve'] + 2 + off + 2 * i]) for i in range(mp['curve_npts'])],
        'xy_scale':    g(mp['xy_scale']),
        'output':      _index_of(OUTPUTS, g(mp['output'])),
        'sens':        g(mp['sens']) if mp.get('sens') is not None else 50,
        'dir_macros':  [g(a) for a in mp.get('dir_macros', ())],
    }
    for i, (_label, addr) in enumerate(mp['inverts']):
        d['invert_%d' % i] = bool(g(addr))
    return d
