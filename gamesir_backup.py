"""
GameSir Cyclone 2 - full-setup backup / restore
================================================
Snapshot the entire controller (all 4 config profiles + the lighting bank) to a
JSON file and write it back later as a restore point.

The snapshot is a faithful image of raw register bytes, so restore is just a
sequence of register writes - no per-field interpretation needed. Reads go
through the same async request/poll layer the editor uses (gamesir_control), which
keeps one read in flight at a time, so a full snapshot takes several seconds; the
GUI shows progress via the on_progress callback.

Each entry is labelled with a human-readable name (so the file is browsable) and
keeps its raw register address + bytes (so restore stays exact). Each profile bank
holds every editor field: analog (sticks/triggers), button remaps, gyro MOTION
(Aim/Tilt) and per-paddle MACROS. Lighting is model-shaped — the Cyclone's keyframe
slots+power, or the 8K's flat bank-0x20 'fields'. JSON shape:
  { "schema": 3, "device": "...", "exported": "<iso>",
    "profiles": { "1": { "Vibration L": {"addr": "0x0020", "bytes": [75]}, ... }, ... },
    "lighting": { "active_slot": {...}, "slots": {...}, "power": {...} }   # Cyclone
             OR { "fields": { "Light mode": {"addr": "0x0000", "bytes": [1]}, ... } } }  # 8K

Restore reads this schema plus the older schema-1 (addr-keyed) and schema-2.
"""

import json
import threading
import time
from datetime import datetime

import gamesir_control as control
import gamesir_config as cfg
import controller_profile as ctrl
import gamesir_led as led
import gamesir_led8k as led8k
import gamesir_motion as motion
import gamesir_macro as macro

SCHEMA = 3          # 3 adds motion + macros to profiles and model-aware lighting
                    # (8K = flat 'fields'); restore still reads schema 1 and 2.
DEVICE_FAMILY = 'GameSir'      # for messages; the snapshot stores the exact model
LED_SLOTS = (0, 1, 2, 3, 4)
POWER_ADDRS = (led.AUDIO_REACTIVE, led.PICKUP_WAKE, led.SLEEP_TIMEOUT)
POWER_NAMES = {
    led.AUDIO_REACTIVE: 'Audio reactive',
    led.PICKUP_WAKE: 'Pick-up to wake',
    led.SLEEP_TIMEOUT: 'Sleep timeout (min)',
}

# Readable names for the 8K's flat lighting/device block (bank 0x20).
_LED8K_NAMES = {
    led8k.MODE: 'Light mode', led8k.BRIGHT: 'Light brightness',
    led8k.HOME_Q[0]: 'Home ring TL', led8k.HOME_Q[1]: 'Home ring TR',
    led8k.HOME_Q[2]: 'Home ring BL', led8k.HOME_Q[3]: 'Home ring BR',
    led8k.AUTO_ONOFF: 'Auto on/off', led8k.SLEEP_TIMER: 'Sleep timer',
    led8k.DOCK_MODE: 'Dock LED mode', led8k.DOCK_BRIGHT: 'Dock LED brightness',
}

# How long to wait for every queued read to land before giving up. A full 8K
# snapshot is now ~480 sequential reads (analog + remaps + motion + macros across
# 4 banks + lighting) and the controller drops back-to-back commands (so some get
# resent), so allow generous headroom.
READ_TIMEOUT = 120.0


def _profile_fields():
    """(addr, length, name) snapshotted per profile bank: analog editor fields,
    button-remap records, gyro MOTION (Aim/Tilt), and per-paddle MACROS — the full
    per-profile register surface, for the active controller's map."""
    prof = ctrl.active()
    labels = prof.field_labels()
    out = [(addr, ln, labels.get(addr, f'0x{addr:04x}')) for addr, ln in prof.read_fields()]
    out += [(addr, 2, 'Remap ' + name) for name, addr in prof.REMAP_SLOTS]
    if prof.has_motion and prof.motion:
        out += [(addr, ln, f'Motion 0x{addr:04x}')
                for addr, ln in motion.read_addrs(prof.motion)]
    if prof.has_macros:
        for pname, base in prof.MACRO_SLOTS:
            out += [(addr, ln, f'Macro {pname} 0x{addr:04x}')
                    for addr, ln in macro.read_addrs(base, prof.macro_max)]
    return out


def _lighting_requests():
    """(bank, addr, length) lighting reads for the active model: Cyclone keyframe
    records + power, or the 8K's flat bank-0x20 block, or nothing."""
    style = ctrl.active().lighting_style
    if style == 'cyclone_keyframe':
        reqs = [(led.LED_BANK, 0x0000, 1)]                 # active-slot selector
        for slot in LED_SLOTS:
            reqs += led.record_read_fields(slot)           # full 124-byte records
        reqs += [(led.LED_BANK, addr, 1) for addr in POWER_ADDRS]
        return reqs
    if style == 'simple_8k':
        return list(led8k.read_fields())                   # (bank, addr, len)
    return []


def _all_requests():
    """Every (bank, addr, length) read needed for a full snapshot."""
    reqs = []
    for prof in ctrl.active().profile_banks:
        for addr, ln, _nm in _profile_fields():
            reqs.append((prof, addr, ln))
    return reqs + _lighting_requests()


def export_async(path, on_progress=None, on_done=None):
    """Queue every snapshot read, wait for the replies, build the JSON image and
    write it to `path`. Runs on a daemon thread. on_progress(done, total) fires as
    replies arrive; on_done(ok, message) fires once at the end."""
    reqs = _all_requests()
    keys = [(bank, addr) for bank, addr, _ln in reqs]
    total = len(keys)

    def run():
        control.request_regs(reqs)
        deadline = time.time() + READ_TIMEOUT
        while time.time() < deadline:
            done = sum(control.reg_result(b, a) is not None for b, a in keys)
            if on_progress:
                on_progress(done, total)
            if done >= total:
                break
            time.sleep(0.1)

        vals = {(b, a): control.reg_result(b, a) for b, a in keys}
        missing = [k for k, v in vals.items() if v is None]
        if missing:
            if on_done:
                on_done(False, f'Timed out reading {len(missing)}/{total} registers '
                               '(is the controller connected and in Xbox mode?)')
            return
        try:
            with open(path, 'w') as fh:
                json.dump(_build(vals), fh, indent=2)
        except OSError as e:
            if on_done:
                on_done(False, f'Could not write file: {e}')
            return
        if on_done:
            on_done(True, f'Saved snapshot to {path}')

    threading.Thread(target=run, daemon=True).start()


def _entry(addr, byts):
    """A labelled backup entry: keeps the raw register address + bytes so restore
    stays exact, while the dict key (the field name) makes the file readable."""
    return {'addr': f'0x{addr:04x}', 'bytes': byts}


def _build(vals):
    """Assemble the JSON-serialisable snapshot dict from {(bank, addr): bytes}."""
    fields = _profile_fields()
    profiles = {}
    for prof in ctrl.active().profile_banks:
        profiles[str(prof)] = {name: _entry(addr, vals[(prof, addr)])
                               for addr, _ln, name in fields}
    return {
        'schema': SCHEMA,
        'device': ctrl.active().name,
        'exported': datetime.now().isoformat(timespec='seconds'),
        'profiles': profiles,
        'lighting': _build_lighting(vals),
    }


def _build_lighting(vals):
    """Lighting section for the active model: Cyclone keyframe slots + power, or
    the 8K's flat 'fields' block, or empty."""
    style = ctrl.active().lighting_style
    if style == 'cyclone_keyframe':
        led_vals = {a: vals[(led.LED_BANK, a)] for b, a in vals if b == led.LED_BANK}
        return {
            'active_slot': _entry(0x0000, vals[(led.LED_BANK, 0x0000)]),
            'slots': {str(slot): _entry(led.record_addr(slot),
                                        led.stitch_record(slot, led_vals))
                      for slot in LED_SLOTS},
            'power': {POWER_NAMES[addr]: _entry(addr, vals[(led.LED_BANK, addr)])
                      for addr in POWER_ADDRS},
        }
    if style == 'simple_8k':
        return {'fields': {_LED8K_NAMES.get(addr, f'0x{addr:04x}'):
                           _entry(addr, vals[(led8k.BANK, addr)])
                           for _b, addr, _ln in led8k.read_fields()}}
    return {}


def load(path):
    """Read and validate a snapshot file. Returns the parsed dict, or raises
    ValueError on a bad/incompatible file. Accepts the current schema and the
    older schema-1 (addr-keyed) layout."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get('schema') not in (1, 2, 3):
        raise ValueError(f'Not a {DEVICE_FAMILY} backup (schema 1-{SCHEMA})')
    if 'profiles' not in data or 'lighting' not in data:
        raise ValueError('Backup is missing profiles/lighting')
    return data


def _writes_from(data):
    """Flatten a loaded snapshot (either schema) into ordered (bank, addr, bytes)
    writes. The active-slot selector is written last so a restore lands on the
    same slot the snapshot had active."""
    writes = []
    lighting = data['lighting']
    if data.get('schema') == 1:
        # schema 1: profile fields keyed by hex addr -> raw bytes
        for prof_s, fields in data['profiles'].items():
            for addr_s, byts in fields.items():
                writes.append((int(prof_s), int(addr_s, 16), list(byts)))
        for slot_s, byts in lighting['records'].items():
            writes.append((led.LED_BANK, led.record_addr(int(slot_s)), list(byts)))
        for addr_s, byts in lighting['power'].items():
            writes.append((led.LED_BANK, int(addr_s, 16), list(byts)))
        writes.append((led.LED_BANK, 0x0000, list(lighting['selector'])))
    else:
        # schema 2/3: labelled entries {name: {addr, bytes}}; addr is authoritative.
        # Lighting is model-shaped: Cyclone has slots+power+active_slot, the 8K has
        # a flat 'fields' block — write whichever the file carries (all bank 0x20).
        for prof_s, fields in data['profiles'].items():
            for ent in fields.values():
                writes.append((int(prof_s), int(ent['addr'], 16), list(ent['bytes'])))
        for ent in lighting.get('slots', {}).values():
            writes.append((led.LED_BANK, int(ent['addr'], 16), list(ent['bytes'])))
        for ent in lighting.get('power', {}).values():
            writes.append((led.LED_BANK, int(ent['addr'], 16), list(ent['bytes'])))
        for ent in lighting.get('fields', {}).values():
            writes.append((led8k.BANK, int(ent['addr'], 16), list(ent['bytes'])))
        if 'active_slot' in lighting:
            sel = lighting['active_slot']
            writes.append((led.LED_BANK, int(sel['addr'], 16), list(sel['bytes'])))
    return writes


# Restore writes are split into <=48-byte units so a write chunk and its
# read-back share the same (addr, length) - the controller's read replies top out
# around 56 bytes, so a 124-byte lighting record can't be verified in one read.
WRITE_CHUNK = 48
MAX_PASSES = 3                 # write -> verify -> re-write dropped, up to N times
CRITICAL_BANKS = (0x01, led.LED_BANK)   # active profile + lighting: must verify


def _expand_units(writes):
    """Split (bank, addr, bytes) writes into <=WRITE_CHUNK-byte (bank, addr, bytes)
    units so each can be written and read back at the same address+length."""
    units = []
    for bank, addr, byts in writes:
        for i in range(0, len(byts), WRITE_CHUNK):
            units.append((bank, addr + i, list(byts[i:i + WRITE_CHUNK])))
    return units


def _allowed_addrs():
    """bank -> set of writable register addresses for the ACTIVE controller,
    derived from the very read plan a snapshot is built from. A restore may only
    write registers a snapshot could have read, so the map is authoritative."""
    allowed = {}
    for bank, addr, ln in _all_requests():
        allowed.setdefault(bank, set()).update(range(addr, addr + ln))
    return allowed


def _validate_writes(writes):
    """Reject a restore plan that targets a bank/address outside the active
    controller's known register map, or a value outside 0..255 — so importing a
    hand-crafted or corrupt backup can only ever restore real settings, never
    drive register writes to arbitrary banks/addresses. Raises ValueError on the
    first violation (the whole restore is refused; nothing is written)."""
    allowed = _allowed_addrs()
    for bank, addr, byts in writes:
        ok = allowed.get(bank)
        if ok is None:
            raise ValueError(f'backup targets unknown register bank 0x{bank:02x} '
                             '(not part of this controller)')
        if any(not isinstance(b, int) or isinstance(b, bool) or not (0 <= b <= 255)
               for b in byts):
            raise ValueError(f'backup has a non-byte value at bank 0x{bank:02x} '
                             f'addr 0x{addr:04x}')
        if not all((addr + i) in ok for i in range(len(byts))):
            raise ValueError('backup writes outside the known register map '
                             f'(bank 0x{bank:02x} addr 0x{addr:04x}, '
                             f'{len(byts)} bytes)')


def apply_backup(data, on_progress=None, on_done=None):
    """Write a loaded snapshot back to the controller on a daemon thread, then
    READ IT BACK and re-write whatever didn't take - the controller silently
    drops back-to-back commands, so a blind write loses blocks (e.g. a lighting
    record). on_progress(done, total) fires as blocks confirm; on_done(ok, message)
    fires once.

    Banks 0x02-0x04 are the stored (non-active) profiles, which the controller
    appears to expose read-only; they're written best-effort but not required to
    confirm, so they don't mask a genuine failure in the active profile/lighting.

    Raises ValueError (before spawning the worker) on a backup whose write plan
    escapes the controller's known register map -- see _validate_writes."""
    writes = _writes_from(data)
    _validate_writes(writes)
    units = _expand_units(writes)
    total = len(units)

    def run():
        style = ctrl.active().write_style   # capture once: consistent framing
        gen = control.generation()          # pin to this device session
        pending = list(units)
        confirmed = []
        for _pass in range(MAX_PASSES):
            # 1. (re)write the not-yet-confirmed units (write_reg paces ~20ms each).
            #    write_reg refuses once the handle is rebound, so a controller
            #    switch mid-restore leaves the new unit untouched -- the pass then
            #    fails to verify and the restore is reported as incomplete.
            for bank, addr, byts in pending:
                control.write_reg(bank, addr, byts, write_style=style, gen=gen)

            # 2. read them all back through the reader thread's request/poll layer
            control.request_regs([(b, a, len(by)) for b, a, by in pending])
            keys = [(b, a) for b, a, _by in pending]
            deadline = time.time() + READ_TIMEOUT
            while time.time() < deadline:
                got = sum(control.reg_result(b, a) is not None for b, a in keys)
                if on_progress:
                    on_progress(len(confirmed) + got, total)
                if got >= len(keys):
                    break
                time.sleep(0.1)

            # 3. keep only the units whose read-back doesn't match what we wrote
            still = []
            for bank, addr, byts in pending:
                back = control.reg_result(bank, addr)
                if back is not None and list(back) == byts:
                    confirmed.append((bank, addr, byts))
                else:
                    still.append((bank, addr, byts))
            pending = still
            if on_progress:
                on_progress(len(confirmed), total)
            if not pending:
                break

        if on_done:
            crit_fail = [u for u in pending if u[0] in CRITICAL_BANKS]
            if not pending:
                on_done(True, f'Restored and verified all {total} register blocks.')
            elif not crit_fail:
                on_done(True, f'Restored & verified the active profile + lighting '
                              f'({len(confirmed)}/{total}). The {len(pending)} '
                              'unconfirmed blocks are the stored profiles 2-4 '
                              '(read-only on this controller) - not used live.')
            else:
                on_done(False, f'Restored {len(confirmed)}/{total}; {len(crit_fail)} '
                               'active-profile/lighting blocks were dropped and '
                               'could not be confirmed - click Restore again.')

    threading.Thread(target=run, daemon=True).start()
