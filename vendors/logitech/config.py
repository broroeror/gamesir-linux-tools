"""
Reusable, gated onboard-config operations for the G502 X — the write path the GUI
bridge drives, factored out of the CLIs so there is ONE proven, backed-up,
read-back-verified mutation function (not a copy per caller).

Everything here mirrors remap.py's --keep flow (which is adversarially reviewed and
proven on-device): back up every profile, gate on a MINIMAL diff (only the target
button's 4 bytes + the 2 CRC bytes), write, read the sector back, and restore the
original on any failure. The device is only ever left fully-verified or untouched.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onboard      # noqa: E402
import remap        # noqa: E402  (backup_all / diff_offsets / parse_binding)
import macros       # noqa: E402  (richer key mapping for key: specs)


# --- friendly binding labels for the UI ("Ctrl+C", "F5", "Mouse 5", "Sniper") ---
def _usage_names():
    n = {}
    for nm, u in macros._NAMED.items():
        n.setdefault(u, nm[:1].upper() + nm[1:])        # space->Space, f5->F5, up->Up
    for c in 'abcdefghijklmnopqrstuvwxyz':
        n[macros.char_to_key(c)[0]] = c.upper()
    for ch in "0123456789`-=[]\\;',./":
        try:
            n[macros.char_to_key(ch)[0]] = ch
        except ValueError:
            pass
    return n


_USAGE_NAMES = _usage_names()
_MODS = [(0x01, 'Ctrl'), (0x02, 'Shift'), (0x04, 'Alt'), (0x08, 'Meta'),
         (0x10, 'RCtrl'), (0x20, 'RShift'), (0x40, 'RAlt'), (0x80, 'RMeta')]


def _key_label(usage, mods):
    name = _USAGE_NAMES.get(usage, 'key 0x%02x' % usage)
    return ''.join(m + '+' for bit, m in _MODS if mods & bit) + name


def friendly_binding(b):
    """onboard.Button -> a human label ('Ctrl+C', 'F5', 'Mouse 5', 'Sniper', …);
    falls back to the raw detail for kinds that already read well (function/macro)."""
    if b.kind == 'send-key':
        return _key_label(b.key, b.modifiers)
    if b.kind == 'send-button':
        return 'Mouse %d' % (b.mouse_mask.bit_length() if b.mouse_mask else 0)
    if b.kind == 'function' and b.function == 0x0B:
        return 'G-Shift'
    if b.kind == 'unset':
        return 'unset'
    return b.detail


def profile_bindings(dev, sector, size):
    """Read a profile sector -> {'buttons': {i: {...,'label'}}, 'gbuttons': {...},
    'sensor': {...}} — the primary + G-Shift button banks AND the sensor header
    (DPI stages, active/sniper index, report rate), in a single sector read.
    `label` is the friendly display string used by the UI."""
    raw = dev.read_sector(sector, size)
    prof = onboard.OnboardProfile.decode(raw, sector=sector)

    def bank(src):
        return {i: {'kind': b.kind, 'detail': b.detail, 'label': friendly_binding(b)}
                for i, b in enumerate(src)}
    return {'buttons': bank(prof.buttons), 'gbuttons': bank(prof.gbuttons),
            'sensor': {
                'dpi': list(prof.resolutions),
                'dpi_default': prof.default_dpi_index,
                'dpi_shift': prof.shift_dpi_index,
                'report_rate_hz': prof.report_rate_hz,
            }}


def apply_bindings(dev, info, headers, sector, button_changes=None,
                   gshift_changes=None, sensor=None, backup_headers=None):
    """Gated, reversible write of MANY edits to `sector` in ONE profile write —
    the batch the GUI's "Apply" uses. `button_changes` / `gshift_changes` are
    {button_index: onboard.Button} for the primary bank and the G-Shift (alternate)
    bank; `sensor` is an optional dict of header edits — {'dpi': {stage: value},
    'dpi_default': idx, 'dpi_shift': idx, 'report_rate_hz': hz} — that all live in
    bytes 0..12 of the SAME 255-byte sector. Every kind of edit rides in the single
    write. Returns (ok, message). Backs up first; aborts unless the change touches
    ONLY the edited buttons' 4-byte slots (primary @32, gshift @96), the edited
    sensor bytes, and the CRC; read-back-verifies; restores on any failure so a
    partial write never persists.

    Batching matters: the whole sector is rewritten regardless of how many fields
    change, so N staged edits cost ONE backup + write + read-back — a big deal over
    the wireless link. `backup_headers` limits the pre-write backup (default: all
    profiles); the GUI passes just the edited profile."""
    button_changes = button_changes or {}
    gshift_changes = gshift_changes or {}
    sensor = sensor or {}
    dpi_changes = sensor.get('dpi') or {}
    size = info['sector_size']
    if not button_changes and not gshift_changes and not sensor:
        return False, 'nothing to apply'
    for grp in (button_changes, gshift_changes):
        for b in grp:
            if not (0 <= b < info['button_count']):
                return False, f'button {b} out of range (0..{info["button_count"] - 1})'
    for i in dpi_changes:
        if not (0 <= int(i) < onboard.N_RESOLUTIONS):
            return False, f'dpi stage {i} out of range (0..{onboard.N_RESOLUTIONS - 1})'
    for k in ('dpi_default', 'dpi_shift'):
        if k in sensor and not (0 <= int(sensor[k]) < onboard.N_RESOLUTIONS):
            return False, f'{k} out of range (0..{onboard.N_RESOLUTIONS - 1})'
    if 'report_rate_hz' in sensor and int(sensor['report_rate_hz']) <= 0:
        # guard the 1000/hz in set_report_rate_hz for any future caller (the GUI
        # already only offers positive rates)
        return False, 'report_rate_hz must be positive'
    if sector not in {s for s, _ in headers}:
        return False, f'sector 0x{sector:04x} is not a profile'

    path = remap.backup_all(dev, info, backup_headers if backup_headers is not None else headers)
    raw = dev.read_sector(sector, size)
    prof = onboard.OnboardProfile.decode(raw, sector=sector)
    if not prof.crc_ok:
        return False, 'profile CRC not OK on read — aborting'

    for i, b in button_changes.items():
        prof.set_button(i, b)
    for i, b in gshift_changes.items():
        prof.set_gshift(i, b)
    for i, v in dpi_changes.items():
        prof.set_dpi(int(i), int(v))
    if 'dpi_default' in sensor:
        prof.default_dpi_index = int(sensor['dpi_default'])
    if 'dpi_shift' in sensor:
        prof.shift_dpi_index = int(sensor['dpi_shift'])
    if 'report_rate_hz' in sensor:
        prof.set_report_rate_hz(int(sensor['report_rate_hz']))
    new_bytes = prof.to_bytes()

    offs = remap.diff_offsets(raw, new_bytes)
    expected = {size - 2, size - 1}
    for i in button_changes:
        expected |= set(range(32 + i * 4, 36 + i * 4))
    for i in gshift_changes:
        expected |= set(range(96 + i * 4, 100 + i * 4))
    if 'report_rate_hz' in sensor:
        expected.add(0)
    if 'dpi_default' in sensor:
        expected.add(1)
    if 'dpi_shift' in sensor:
        expected.add(2)
    for i in dpi_changes:
        expected |= set(range(3 + int(i) * 2, 5 + int(i) * 2))
    safe = (onboard.OnboardProfile.decode(new_bytes).crc_ok
            and set(offs).issubset(expected)
            and onboard.OnboardProfile.decode(raw).to_bytes() == raw
            and sector < info['sector_count'])
    if not safe:
        return False, f'safety gate failed (changed bytes {offs}) — not writing'

    try:
        dev.write_sector(sector, new_bytes)
        if dev.read_sector(sector, size) != new_bytes:
            dev.write_sector(sector, raw)                 # revert
            return False, 'read-back mismatch — reverted to original'
    except Exception as e:
        try:
            dev.write_sector(sector, raw)                 # revert
        except Exception as e2:
            return False, (f'write failed ({e}) AND restore failed ({e2}) — '
                           f'restore manually from {os.path.basename(path)}')
        return False, f'write failed ({e}) — reverted to original'
    n = (len(button_changes) + len(gshift_changes) + len(dpi_changes)
         + sum(k in sensor for k in ('dpi_default', 'dpi_shift', 'report_rate_hz')))
    return True, f'applied {n} change{"" if n == 1 else "s"} (backup {os.path.basename(path)})'


def apply_binding(dev, info, headers, sector, button, new_binding, backup_headers=None):
    """Single primary-button convenience wrapper over apply_bindings (see it for the
    gate + safety). Kept for callers that change one button at a time."""
    return apply_bindings(dev, info, headers, sector, {button: new_binding},
                          backup_headers=backup_headers)


# Binding constructors the UI offers, expressed as onboard.Button factories.
# Mirrors remap.parse_binding's vocabulary; the bridge maps a UI choice to one of
# these and hands the Button to apply_binding.
def binding_from_spec(spec):
    """'key:<name|char|combo>' | 'mouse:<n>' | 'sniper' | 'dpi-up' | 'dpi-down' |
    'dpi-cycle' | 'disabled' -> onboard.Button. Raises ValueError on an unknown spec.

    'key:' uses the macro engine's key map (letters, digits, F-keys, symbols,
    arrows, nav keys) and accepts a modifier combo like 'key:ctrl+c' — the onboard
    button binding carries [modifier][key], so a mod+key chord is one binding."""
    if spec.startswith('key:'):
        combo = spec[len('key:'):]
        if '+' in combo:
            mods, usage = macros.parse_combo(combo)
        else:
            mods, usage = 0, macros.key_usage(combo)
        return onboard.Button.key(usage, mods)
    if spec == 'gshift-hold':                     # the G-Shift trigger button
        return onboard.Button.gshift_trigger()
    return remap.parse_binding(spec)
