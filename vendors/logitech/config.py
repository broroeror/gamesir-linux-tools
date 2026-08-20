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
    if b.kind == 'macro':
        return 'Macro'
    if b.kind == 'unset':
        return 'unset'
    return b.detail


# --- macro definitions (structured steps <-> bytecode + labels) ---------------
# A macro definition is {'steps': [step, ...], 'repeat': bool}. Each step is a
# key/click/text action with an optional HOLD (ms the key/button is held) and
# DELAY-after (ms before the next step) — the same per-step timing model as the
# controller macro editor:
#   {'t':'key',   'combo':'ctrl+c', 'hold':0, 'delay':30}  a key or shortcut
#   {'t':'click', 'button':1,       'hold':0, 'delay':30}  a mouse button
#   {'t':'text',  'text':'hello',             'delay':30}  type a string (auto-shift)
# mouse-button step labels (the action a step performs, named like the buttons)
_CLICK_NAMES = {1: 'Left Click', 2: 'Right Click', 3: 'Middle Click', 4: 'Back', 5: 'Forward'}


def _macro_steps(macrodef):
    return macrodef.get('steps', []) if isinstance(macrodef, dict) else (macrodef or [])


def _ms(v):
    """A timing field (hold/delay) -> a clamped non-negative int (None/'' -> 0)."""
    return max(0, min(0xFFFF, int(v or 0)))


def build_macro_body(macrodef):
    """Structured macro def -> macro bytecode (terminated with END). A key/click step
    emits press, an optional HOLD delay, release, then an optional DELAY-after; text
    types the string then an optional delay. Raises ValueError on an unknown/malformed
    step or an empty macro (the def comes from untrusted JSON, so every field error is
    normalized to ValueError for the callers' `except`)."""
    m = macros.Macro()
    n = 0
    for s in _macro_steps(macrodef):
        if not isinstance(s, dict):
            raise ValueError(f'bad macro step (not an object): {s!r}')
        t = s.get('t')
        try:
            if t == 'key':
                combo = s.get('combo')
                if not isinstance(combo, str) or not combo:
                    raise ValueError('key step needs a non-empty "combo" string')
                mods, key = macros.parse_combo(combo)
                m.press_key(key, mods)
                if _ms(s.get('hold')):
                    m.pause(_ms(s.get('hold')))
                m.release_key(key, mods)
            elif t == 'click':
                m.mouse_down(int(s.get('button', 1) or 1))
                if _ms(s.get('hold')):
                    m.pause(_ms(s.get('hold')))
                m.mouse_up(int(s.get('button', 1) or 1))
            elif t == 'scroll':
                m.scroll(int(s.get('delta', 1) or 1))       # +up / -down (i8)
            elif t == 'media':
                code = int(s.get('code', 0) or 0)
                if code <= 0:
                    raise ValueError('media step needs a "code"')
                m.consumer(code)
            elif t == 'text':
                text = s.get('text')
                if not text:
                    continue                      # empty text step = no-op
                if not isinstance(text, str):
                    raise ValueError('text step "text" must be a string')
                m.type(text)
            else:
                raise ValueError(f'unknown macro step: {t!r}')
            if _ms(s.get('delay')):
                m.pause(_ms(s.get('delay')))
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f'bad macro step {t!r}: {e}')
        n += 1
    if n == 0:
        raise ValueError('macro has no steps')
    if isinstance(macrodef, dict) and macrodef.get('repeat'):
        m.repeat_until_release()          # loop while the button is held
    return m.build()


def _combo_label(combo):
    return '+'.join(p[:1].upper() + p[1:] for p in str(combo).split('+') if p)


def macro_step_label(s):
    """One step -> a short label ('Ctrl+C', 'Left Click', 'Scroll ↑', '“hi”')."""
    if not isinstance(s, dict):
        return str(s)
    t = s.get('t')
    if t == 'key':
        return _combo_label(s.get('combo', ''))
    if t == 'click':
        return _CLICK_NAMES.get(int(s.get('button', 1) or 1), 'Mouse %d' % int(s.get('button', 1) or 1))
    if t == 'scroll':
        return 'Scroll ' + ('↑' if int(s.get('delta', 1) or 1) >= 0 else '↓')
    if t == 'media':
        return macros.CONSUMER.get(int(s.get('code', 0) or 0), 'Media')
    if t == 'text':
        return '“%s”' % s.get('text', '')
    return str(t)


def macro_summary(macrodef):
    """Short human label for a whole macro def (chips / button preview)."""
    parts = [macro_step_label(s) for s in _macro_steps(macrodef)]
    label = ' · '.join(parts) or 'empty'
    if isinstance(macrodef, dict) and macrodef.get('repeat'):
        label += ' ⟳'
    return label


# One macro may chain across this many sectors (via JUMP). 4 of the ~10 slots is
# a generous single-macro cap (~1000 bytes ≈ 80 steps) that can't starve the rest.
MAX_MACRO_SECTORS = 4


def max_macro_bytes(sector_size, sectors=MAX_MACRO_SECTORS):
    """Largest macro bytecode that fits `sectors` chained sectors. Matches
    split_body exactly: its per-chunk budget is sector_size-5 for EVERY chunk
    (the last included), so advertising the last chunk at full sector size let
    1001..1005-byte bodies pass the limit check and then fail the split
    (review #5 false-abort)."""
    return sectors * (sector_size - 5)


def free_macro_sectors(dev, info, headers):
    """Every macro-region sector a new macro may be written to: ERASED (all-0xFF),
    not the directory / a listed profile, AND NOT REFERENCED by any button. The
    referenced check matters even for blank sectors — a pointer or chain JUMP
    targeting an erased sector is a legal instant-END macro, and allocating that
    sector would make that button run someone else's bytecode (review #4). If
    the reference scan can't complete, claim nothing (allocating on an unproven
    map is how live macros get clobbered)."""
    listed = {s for s, _ in headers} | {0x0000}
    try:
        refs = referenced_macro_sectors(dev, info, headers)
    except Exception:
        return []
    size = info['sector_size']
    out = []
    for s in range(info['profile_count'] + 1, info['sector_count']):
        if s in listed or s in refs:
            continue
        if all(b == 0xFF for b in dev.read_sector(s, size)):
            out.append(s)
    return out


def _macro_body_at(dev, size, sector, offset):
    """Read the LOGICAL macro bytecode at (sector, offset): the opcode stream up
    to and including END, FOLLOWING chain JUMPs (which are dropped from the
    result, so a chained macro compares equal to its pre-split body). b'' on any
    issue — malformed stream, missing END, or a jump loop."""
    try:
        raw = dev.read_sector(sector, size)
        out = bytearray()
        i, hops = offset, 0
        for _ in range(2048):
            if i >= len(raw):
                return b''
            op = raw[i]
            n = macros.opcode_len(op)
            if n is None or i + n > len(raw):
                return b''
            if op == macros.OP_JUMP:
                hops += 1
                if hops > MAX_MACRO_SECTORS + 2:      # loop guard
                    return b''
                tgt = (raw[i + 1] << 8) | raw[i + 2]
                off = (raw[i + 3] << 8) | raw[i + 4]
                raw = dev.read_sector(tgt, size)
                i = off
                continue
            out += raw[i:i + n]
            i += n
            if op == macros.OP_END:
                return bytes(out)
        return b''
    except Exception:
        return b''


def referenced_macro_sectors(dev, info, headers):
    """Every sector some button's macro pointer (any listed profile, either bank)
    reaches — the pointed-at sectors plus everything their chains JUMP into.
    These are the macro sectors that must NEVER be blanked.

    RAISES on anything it cannot FULLY decode — an unreadable sector, an unknown
    opcode, a stream running off the sector end. An incomplete walk must abort
    the caller (reclaim), never under-collect: a silently truncated walk would
    classify a live chain tail as an orphan and blank it (adversarial-review
    findings #1/#2 — foreign-written chains, e.g. G HUB's, can be longer or use
    opcodes we don't model). Loops are detected via visited jump states (safe to
    stop there: everything reachable has been walked); there is NO hop cap."""
    size = info['sector_size']
    starts = set()
    for sector, _ in headers:
        prof = onboard.OnboardProfile.decode(dev.read_sector(sector, size),
                                             sector=sector)
        for b in list(prof.buttons) + list(prof.gbuttons):
            if b.kind == 'macro':
                starts.add((b.macro_sector, b.macro_address))
    seen = set()
    for start_sec, start_off in starts:
        visited = set()                  # (sector, jump-op offset) states
        sec, i = start_sec, start_off
        seen.add(sec)
        raw = dev.read_sector(sec, size)
        for _ in range(8192):
            if i >= len(raw):
                raise ValueError(
                    f'macro stream in sector 0x{sec:04x} runs past the sector end')
            op = raw[i]
            n = macros.opcode_len(op)
            if n is None:
                raise ValueError(
                    f'undecodable opcode 0x{op:02x} in macro sector 0x{sec:04x}')
            if i + n > len(raw):
                raise ValueError(f'truncated opcode in macro sector 0x{sec:04x}')
            if op == macros.OP_END:
                break
            if op == macros.OP_JUMP:
                if (sec, i) in visited:
                    break                # loop — all reachable sectors collected
                visited.add((sec, i))
                tgt = (raw[i + 1] << 8) | raw[i + 2]
                off = (raw[i + 3] << 8) | raw[i + 4]
                seen.add(tgt)
                raw = dev.read_sector(tgt, size)
                sec, i = tgt, off
                continue
            i += n
        else:
            raise ValueError('macro walk exceeded the op budget')
    return seen


def reclaim_orphan_macros(dev, info, headers):
    """Blank (erase to all-0xFF) every macro-region sector that NO button in any
    listed profile references — the orphans left behind by macro edits/clears
    (and old G HUB macros nothing points at). Structurally safe: the candidate
    set excludes the directory, every listed profile sector, and every sector
    reachable from any macro pointer; blanking an unreferenced sector cannot
    change any behaviour. Each blank is read-back-verified. Returns
    (ok, freed_count, message)."""
    size = info['sector_size']
    listed = {s for s, _ in headers} | {0x0000}
    try:
        refs = referenced_macro_sectors(dev, info, headers)
    except Exception as e:
        # can't PROVE what's referenced -> touch NOTHING (raises cover unreadable
        # sectors AND undecodable/foreign macro streams — review #1/#2)
        return False, 0, f'could not verify macro references ({e}) — nothing was changed'
    blank = b'\xff' * size
    freed = failed = 0
    for s in range(info['profile_count'] + 1, info['sector_count']):
        if s in listed or s in refs:
            continue
        try:
            if dev.read_sector(s, size) == blank:
                continue                       # already free
            dev.write_full_sector_no_crc(s, blank)
            if dev.read_sector(s, size) == blank:
                freed += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    if failed and not freed:
        return False, 0, ('could not blank any orphaned sector — this firmware '
                          'may not support erasing (nothing was referencing '
                          'them, so nothing changed)')
    msg = f'freed {freed} macro slot{"" if freed == 1 else "s"}'
    if failed:
        msg += f' ({failed} could not be blanked)'
    if freed == 0:
        msg = 'no orphaned macro slots to free — every stored macro is in use'
    return True, freed, msg


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
                   gshift_changes=None, sensor=None, backup_headers=None,
                   existing_backup=None):
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

    if existing_backup is not None:
        path = existing_backup            # caller already snapshotted (see apply_edits)
    else:
        try:
            path = remap.backup_all(
                dev, info, backup_headers if backup_headers is not None else headers)
        except OSError as e:
            # e.g. an installed app whose backup dir isn't writable: refuse rather
            # than write to the device with no way back
            return False, f'could not save the safety backup ({e}) — nothing was changed'
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


def apply_edits(dev, info, headers, sector, button_changes=None, gshift_changes=None,
                sensor=None, macro_changes=None, backup_headers=None):
    """Full staged Apply, macros included. `macro_changes` = {button: macrodef|None}
    (None clears -> disabled). For each NEW macro this writes its bytecode into a
    free ERASED sector (the proven full-sector no-CRC write + read-back), then folds
    the resulting macro pointer into `button_changes` so the profile is written ONCE,
    gated, by apply_bindings (buttons + gshift + sensor together). A macro byte-
    identical to what the button already runs is skipped (no slot burned). Returns
    (ok, message).

    Batch macros are PLANNED before any flash write: every button index, macro body,
    and size is validated and total free-slot capacity is checked up front, so a
    doomed batch (bad index, empty/oversized macro, not enough slots) fails BEFORE
    touching flash and never orphans a slot. v1: one sector per macro (no cross-
    sector chaining); reassigning/clearing a macro orphans its old sector (harmless;
    flash can't be erased here yet). If a macro write's read-back fails mid-batch (a
    hardware hiccup) the profile is never written and any already-written sectors are
    harmless orphans."""
    button_changes = dict(button_changes or {})
    macro_changes = macro_changes or {}
    size = info['sector_size']
    backup_path = None                     # set once a macro write needs one first
    if macro_changes:
        try:
            cur = onboard.OnboardProfile.decode(dev.read_sector(sector, size), sector=sector)
        except Exception as e:
            return False, f'profile read failed: {e}'
        # --- plan (no writes): validate + build bodies + split into chunks ---
        to_write = []                                  # [(button, [chunk, ...])]
        for btn, macrodef in macro_changes.items():
            if not (0 <= btn < info['button_count']):
                return False, f'macro button {btn} out of range (0..{info["button_count"] - 1})'
            if macrodef is None:
                button_changes[btn] = onboard.Button.disabled()
                continue
            try:
                body = build_macro_body(macrodef)
            except ValueError as e:
                return False, f'button {btn}: {e}'
            if len(body) > max_macro_bytes(size):
                return False, (f'macro on button {btn} is {len(body)} bytes — over the '
                               f'{max_macro_bytes(size)}-byte limit '
                               f'({MAX_MACRO_SECTORS} chained sectors); shorten it')
            curb = cur.buttons[btn]
            # identical-skip only for a macro-EXECUTE binding: 'macro' kind also
            # covers macro-STOP (behavior 0x1), whose bytes may match the staged
            # body while the button does the opposite thing (review #3)
            if curb.kind == 'macro' and curb.behavior == onboard.BEHAVIOR_MACRO_EXECUTE \
                    and _macro_body_at(dev, size, curb.macro_sector, curb.macro_address) == body:
                continue                               # already runs this exact macro
            # one sector if it fits; else split at opcode boundaries + JUMP-chain
            try:
                chunks = ([body] if len(body) <= size
                          else macros.split_body(body, size, MAX_MACRO_SECTORS))
            except ValueError as e:
                return False, f'button {btn}: {e}'
            to_write.append((btn, chunks))
        # --- capacity check up front (whole batch, chains included), then write ---
        if to_write:
            # The safety backup must exist BEFORE the first flash write. It used to
            # be taken inside apply_bindings, i.e. AFTER the macro sectors were
            # written, so a backup failure (installed app, read-only backup dir)
            # left those sectors written but unreferenced -- orphaned slots for a
            # write that never completed.
            try:
                backup_path = remap.backup_all(
                    dev, info, backup_headers if backup_headers is not None else headers)
            except OSError as e:
                return False, f'could not save the safety backup ({e}) — nothing was changed'
            need = sum(len(c) for _, c in to_write)
            free = free_macro_sectors(dev, info, headers)
            if len(free) < need:
                return False, (f'not enough free macro slots — {len(free)} free, '
                               f'need {need} (use "Free unused slots", or clear a macro)')
            fi = 0
            for btn, chunks in to_write:
                alloc = free[fi:fi + len(chunks)]
                fi += len(chunks)
                for j, chunk in enumerate(chunks):
                    # every chunk but the last ends with a JUMP to the next sector
                    stream = chunk if j == len(chunks) - 1 \
                        else chunk + macros.jump(alloc[j + 1], 0)
                    image = macros.to_sector(stream, size, crc=False, offset=0)
                    try:
                        dev.write_full_sector_no_crc(alloc[j], image)
                        if dev.read_sector(alloc[j], size) != image:
                            return False, (f'macro sector 0x{alloc[j]:04x} read-back '
                                           'mismatch — not committed')
                    except Exception as e:
                        return False, f'macro write failed: {e}'
                button_changes[btn] = onboard.Button.macro_ptr(alloc[0], 0)

    if not button_changes and not gshift_changes and not sensor:
        return True, 'no changes needed'          # all staged edits were no-ops
    return apply_bindings(dev, info, headers, sector,
                          button_changes=button_changes, gshift_changes=gshift_changes,
                          sensor=sensor, backup_headers=backup_headers,
                          existing_backup=backup_path)


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
