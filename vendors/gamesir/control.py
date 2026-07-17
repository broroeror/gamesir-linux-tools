"""
GameSir Cyclone 2 - command / write layer
=========================================
Everything the host SENDS to the controller over the vendor command channel
(report 0x0F): the shared device handle, the thread-safe writer, and the
high-level commands (profile, rumble, register write).

Commands and the read loop share ONE hid handle across threads, so every write
goes through a single lock. The handle is REBOUND on each reconnect, so callers
must never cache it: `send_cmd` reads the current handle live, and the reader
publishes the handle via `set_device` / `clear_device`.
"""

import collections
import threading
import time

from gs_common import pad
import controller_profile as profiles

_write_lock = threading.Lock()
_device = None
_generation = 0        # bumped on each (re)bind so a multi-step operation can
                       # tell the device handle was swapped under it


def set_device(dev):
    """Publish the freshly-opened handle so commands target it. Advances the
    session generation so an in-flight multi-write (config Apply, backup restore,
    loader entry) can tell the controller was switched/reconnected under it, and
    drops any reads queued for the OLD handle so the new session starts clean."""
    global _device, _generation
    with _write_lock:
        _device = dev
        _generation += 1
    _reset_reads()


def clear_device():
    """Drop the handle (on disconnect); commands become no-ops until reopened.
    Also drops pending reads so none are attributed to a later session."""
    global _device
    with _write_lock:
        _device = None
    _reset_reads()


def generation():
    """Current device-session generation. Capture it when a multi-step operation
    begins and pass it back via `gen=` to send_cmd/write_reg; those calls then
    refuse once the handle is rebound, so a controller switch mid-operation can't
    deliver the remaining writes to a different unit."""
    return _generation


def send_cmd(*payload, gen=None, probe=False):
    """Thread-safe padded command write to the current device.

    Refuses (returns False) when the connected controller is NOT a recognized
    model: the active register/command map falls back to the Cyclone's, so firing
    Cyclone-framed commands at an unknown device could corrupt it. This is the
    single choke point behind every write path (register writes via write_reg,
    profile/rumble/playback, loader entry), so a new write path can't silently
    bypass the guard — the reason to guard here instead of at each call site.

    `probe=True` exempts the reader's own session-maintenance traffic — the
    heartbeat, the profile/lighting queries, and queued register READS — which
    must keep flowing to sustain and read a session and never change device state.

    If `gen` is given and no longer matches the live session generation, the write
    is refused (the device was rebound under the caller — e.g. a controller
    switch). All checks and the write are atomic under the lock, so no write can
    straddle a rebind."""
    with _write_lock:
        if _device is None:
            return False
        if not probe and not profiles.is_recognized():
            return False
        if gen is not None and gen != _generation:
            return False
        try:
            _device.write(pad(*payload))
            return True
        except Exception:
            return False


def set_profile(n):
    send_cmd(0x0F, 0x07, n)          # device will reply to the periodic get-profile


def rumble(left, right):
    send_cmd(0x0F, 0x20, 0x66, 0x55, left, right)


def rumble_test():
    def run():
        rumble(0xC0, 0xC0)
        time.sleep(0.4)
        rumble(0x00, 0x00)
    threading.Thread(target=run, daemon=True).start()


_g7_seq = 0            # rolling sequence for the G7's enveloped writes


def write_reg(bank, addr, data, write_style=None, gen=None):
    """Thread-safe register write, chunked to fit the 64-byte report. Frames the
    command for whichever controller is active: the Cyclone sends the bare
    `0f 03 …` register write; the G7 wraps the SAME inner command in its
    sequenced envelope `0f 00 <seq> 3c | 03 …` (write_style on the profile).

    A multi-register operation (config Apply / backup restore) captures the
    profile's `write_style` ONCE and passes it here, so a controller switch
    partway through can't reframe the remaining chunks for the wrong device.
    Omitted, it resolves the live active profile (fine for a one-off write).

    `gen` pins the write to a device session (see generation()): a multi-register
    operation captures it once and passes it here, so a controller switch mid-way
    makes each remaining chunk refuse (return False) instead of landing on the
    newly-bound unit. Returns False on the first refused/failed chunk."""
    global _g7_seq
    g7 = (write_style or profiles.active().write_style) == 'g7'
    chunk_len = 55 if g7 else 48    # inner block caps at 60B (5B header + 55 data)
    i = 0
    while i < len(data):
        chunk = data[i:i + chunk_len]
        a = addr + i
        inner = (0x03, bank, (a >> 8) & 0xFF, a & 0xFF, len(chunk), *chunk)
        if g7:
            _g7_seq = (_g7_seq + 1) & 0xFF
            ok = send_cmd(0x0F, 0x00, _g7_seq, 0x3C, *inner, gen=gen)
        else:
            ok = send_cmd(0x0F, *inner, gen=gen)
        if not ok:
            return False
        time.sleep(0.02)
        i += chunk_len
    return True


# --- register READ request/response ----------------------------------------
# The reader thread owns the hid handle, so register reads can't be done
# synchronously from another thread. Instead callers QUEUE reads here; the
# reader thread pumps them (one in flight at a time, resending on timeout) and
# stores replies, which callers poll via reg_result().
_read_lock = threading.Lock()
_read_q = collections.deque()      # pending (bank, addr, length)
_read_results = {}                 # (bank, addr) -> list[int]
_inflight = None                   # {'key', 'cmd', 't'} or None


def _reset_reads():
    """Drop all queued/in-flight reads and their results. Called on every (re)bind
    and disconnect so a new session never inherits the previous device's pending
    reads -- results are keyed only by (bank, addr), so a stale reply would
    otherwise be attributed to (or stitched into) the wrong unit."""
    global _inflight
    with _read_lock:
        _read_q.clear()
        _read_results.clear()
        _inflight = None


def request_regs(reqs):
    """Queue a batch of (bank, addr, length) reads, clearing their old results
    so a caller can tell fresh values from stale ones."""
    with _read_lock:
        for bank, addr, length in reqs:
            _read_results.pop((bank, addr), None)
            _read_q.append((bank, addr, length))


def reg_result(bank, addr):
    """Latest bytes read at (bank, addr), or None if not yet available."""
    with _read_lock:
        return _read_results.get((bank, addr))


def store_reg_result(bank, addr, data):
    """Called by the reader thread when a 0x10 0x05 reply arrives."""
    global _inflight
    with _read_lock:
        _read_results[(bank, addr)] = data
        if _inflight is not None and _inflight['key'] == (bank, addr):
            _inflight = None


def pump_reads():
    """Run from the reader thread between device reads: keep exactly one
    register read in flight, resending if a reply is dropped (the controller
    drops back-to-back commands)."""
    global _inflight
    now = time.time()
    cmd = None
    with _read_lock:
        if _inflight is not None:
            if now - _inflight['t'] > 0.25:      # timed out -> resend
                _inflight['t'] = now
                cmd = _inflight['cmd']
        elif _read_q:
            bank, addr, length = _read_q.popleft()
            cmd = (0x0F, 0x04, bank, (addr >> 8) & 0xFF, addr & 0xFF, length)
            _inflight = {'key': (bank, addr), 'cmd': cmd, 't': now}
    if cmd:
        send_cmd(*cmd, probe=True)   # reader's own register-read pump: a read,
                                     # never a state change, so it bypasses the
                                     # recognized-model guard


# --- demo mode: answer register reads with defaults (no hardware) -------------
_demo_regs = {}                    # (bank, addr) -> list[int] overrides


def set_demo_regs(regs):
    """Install the per-controller default register map the demo pump answers from
    (keyed by (bank, addr)). Anything not in the map gets a generic default."""
    global _demo_regs
    _demo_regs = dict(regs or {})


def _demo_bytes(bank, addr, length):
    """Default bytes for a demo read. Curve blocks (10 bytes) get a linear diagonal
    so the response-curve editor draws sensibly; everything else defaults to zero
    (neutral: no deadzone, effects off, remaps unmapped, macros empty)."""
    v = _demo_regs.get((bank, addr))
    if v is not None:
        return list(v)[:length] + [0] * max(0, length - len(v))
    if length == 10:               # [type, intensity, 0, 0, (x,y)*3] linear preset
        return [0x00, 0x64, 0x00, 0x00, 0x27, 0x27, 0x80, 0x80, 0xD8, 0xD8]
    return [0] * length


def pump_demo_reads():
    """Demo stand-in for pump_reads: immediately answer every queued register read
    with a default, so the bridge's pollers populate exactly as they would from a
    real device. Runs from the (idled) reader loop while demo mode is on."""
    with _read_lock:
        q = list(_read_q)
        _read_q.clear()
    for bank, addr, length in q:
        store_reg_result(bank, addr, _demo_bytes(bank, addr, length))
