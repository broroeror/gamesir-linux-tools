"""
Logitech HID++ 2.0 transport (Linux / hidraw)
=============================================
Minimal, dependency-light HID++ 2.0 client, enough to READ the onboard-profile
memory of a G502 X LIGHTSPEED and validate our codec against the real device.
Modelled on Solaar's proven framing (logitech_receiver/base.py + hidpp20.py) but
written as our own clean code so the shipped app carries no Solaar runtime dep.

Wire format (over hidraw, using hidapi like the rest of Deadband):
  request  = [report_id, device_index, feature_index, func<<4 | sw_id, params...]
  report_id 0x10 = SHORT  (7 bytes total, 3 param bytes)
  report_id 0x11 = LONG   (20 bytes total, 16 param bytes)
  choose LONG when the inner payload (feature_index+funcbyte+params) exceeds 5.
  reply    = same header echoed back, then the response data bytes.
  error    = report_id 0x10, feature_index byte == 0xFF, then [orig_feature,
             orig_funcbyte, error_code].

device_index is 0xFF for a directly-wired device; for a pad behind the
Lightspeed receiver it's the pairing slot (1..6) — not needed yet (mouse is
wired) but plumbed through as a parameter.

Reads use feature-discovery pings + 0x8100 reads (function indices 0/2/4/5).
WRITES (indices 6/7/8 = addrWrite/write/writeEnd) live in write_sector() and
MUTATE the device — they are NEVER called by read_profile.py; only by an
explicit, backed-up, read-back-verified write flow.
"""

import time
import glob
import os
import hid

# --- HID++ constants ---------------------------------------------------------
SHORT_ID = 0x10
LONG_ID = 0x11
SHORT_LEN = 7
LONG_LEN = 20
SW_ID = 0x0F                 # our software id (low nibble of the func byte)

ROOT_INDEX = 0x00            # the ROOT feature is always at index 0
FEATURE_ROOT = 0x0000
FEATURE_FEATURE_SET = 0x0001
FEATURE_ONBOARD_PROFILES = 0x8100
FEATURE_UNIFIED_BATTERY = 0x1004

# ONBOARD_PROFILES (0x8100) FUNCTION INDICES — RAW 0..15; request() applies the
# <<4 to place them in the high nibble. Pass raw indices here, NOT the pre-shifted
# wire byte. (Review caught the original bug: these were the shifted bytes
# 0x20/0x40/0x50, so request()'s <<4 double-shifted them all down to fn 0 = getInfo,
# collapsing every profile read. libratbag's map confirms the indices: the wire
# bytes 0x20/0x40/0x50 = index 2/4/5.)
OB_GET_INFO = 0x00           # fn 0  getOnboardProfilesInfo
OB_GET_MODE = 0x02           # fn 2  getOnboardMode (0x01 on-board / 0x02 host)
OB_GET_CURRENT_PROFILE = 0x04  # fn 4  getCurrentProfile
OB_MEMORY_READ = 0x05        # fn 5  memoryRead
OB_ADDR_WRITE = 0x06         # fn 6  begin sector write (addr + length)  [MUTATES]
OB_WRITE = 0x07              # fn 7  write next 16 bytes                 [MUTATES]
OB_WRITE_END = 0x08          # fn 8  end / commit the sector write       [MUTATES]

LOGITECH_VID = 0x046D
# G502 X LIGHTSPEED USB product ids: wired pad, and the wireless id it presents
# through the Lightspeed receiver.
G502X_PIDS = (0xC098, 0x409F)


class HidppError(Exception):
    """A HID++ 2.0 error reply (feature index 0xFF), carrying the error code."""
    def __init__(self, code, feature_index, function):
        self.code = code
        super().__init__(f'HID++ error 0x{code:02x} on feature idx '
                         f'{feature_index} fn 0x{function:02x}')


class Hidpp:
    """One open hidraw handle speaking HID++ 2.0 to a single device."""

    def __init__(self, path, device_index=0xFF, timeout_ms=2000):
        self.path = path
        self.device_index = device_index
        self.timeout_ms = timeout_ms
        self._dev = hid.device()
        self._dev.open_path(path if isinstance(path, bytes) else path.encode())
        self._dev.set_nonblocking(True)
        self._feature_cache = {}     # feature_id -> index

    def close(self):
        try:
            self._dev.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- low-level request/response -----------------------------------------
    def request(self, feature_index, function, params=b''):
        """Send one HID++ 2.0 request and return the response DATA bytes
        (everything after the 4-byte header). Raises HidppError on an error
        reply, TimeoutError if no matching reply arrives."""
        params = bytes(params)
        func_byte = ((function & 0x0F) << 4) | SW_ID
        inner = bytes([feature_index, func_byte]) + params

        # short carries 3 param bytes (inner<=5); anything longer must go long.
        if len(inner) <= SHORT_LEN - 2:
            report_id, total = SHORT_ID, SHORT_LEN
        else:
            report_id, total = LONG_ID, LONG_LEN
        frame = bytes([report_id, self.device_index]) + inner
        frame = frame + b'\x00' * (total - len(frame))
        # hidapi's write wants report id as first byte; hidraw has no numbered
        # report here, so we prepend a 0 only if the platform needs it. On Linux
        # hidraw, the report id IS the first byte of the buffer.
        self._dev.write(list(frame))

        deadline = time.time() + self.timeout_ms / 1000.0
        while time.time() < deadline:
            data = self._dev.read(64, timeout_ms=50)
            if not data:
                continue
            r = bytes(data)
            if len(r) < 4 or r[0] not in (SHORT_ID, LONG_ID):
                continue
            if r[1] != self.device_index:
                continue
            # HID++ 2.0 error reply: feature-index byte is 0xFF.
            if r[2] == 0xFF and len(r) >= 6 and r[3] == feature_index \
                    and r[4] == func_byte:
                raise HidppError(r[5], feature_index, function)
            if r[2] == feature_index and r[3] == func_byte:
                return r[4:]
            # else: an unsolicited notification or another sw_id's reply — skip.
        raise TimeoutError(f'no HID++ reply for feature idx {feature_index} '
                           f'fn 0x{function:02x}')

    # --- feature discovery ---------------------------------------------------
    def get_feature_index(self, feature_id):
        """Resolve a 16-bit feature id to its per-device index via ROOT, or 0
        if the device doesn't support it (index 0 is ROOT itself = 'absent')."""
        if feature_id in self._feature_cache:
            return self._feature_cache[feature_id]
        data = self.request(ROOT_INDEX, 0x00,
                            bytes([feature_id >> 8, feature_id & 0xFF, 0x00]))
        index = data[0] if data else 0
        self._feature_cache[feature_id] = index
        return index

    def ping(self):
        """ROOT.getProtocolVersion — cheap liveness/HID++ probe. Returns
        (major, minor) or raises. Used to find the HID++ hidraw node."""
        # function 0x1, with a ping marker in the 3rd param that the device
        # echoes back in data[2], so we know the reply is really ours.
        data = self.request(ROOT_INDEX, 0x01, bytes([0x00, 0x00, 0x5A]))
        if len(data) >= 3 and data[2] != 0x5A:
            raise TimeoutError('ping marker not echoed')
        return (data[0], data[1]) if len(data) >= 2 else (0, 0)

    # --- ONBOARD_PROFILES (0x8100) reads ------------------------------------
    def onboard_info(self):
        """feature 0x8100 fn 0x00 -> dict describing the onboard-profile store.
        Fields mirror the HID++ spec / Solaar: memory_model_id, profile_format,
        macro_format, profile_count, oob_count, button_count, sector_count,
        sector_size, mechanical_layout (the shift-capability nibble)."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        if not idx:
            raise RuntimeError('device has no ONBOARD_PROFILES (0x8100) feature')
        d = self.request(idx, OB_GET_INFO)
        return {
            'feature_index': idx,
            'memory_model_id': d[0],
            'profile_format': d[1],
            'macro_format': d[2],
            'profile_count': d[3],
            'oob_count': d[4],
            'button_count': d[5],
            'sector_count': d[6],
            'sector_size': (d[7] << 8) | d[8],
            'mechanical_layout': d[9],
            # G-Shift second bank exists iff the low 2 bits are 0b10 (Solaar rule).
            'has_gshift': (d[9] & 0x03) == 0x02,
        }

    def current_profile(self):
        """feature 0x8100 fn 0x40 -> the active profile sector id (BE)."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        d = self.request(idx, OB_GET_CURRENT_PROFILE)
        return (d[0] << 8) | d[1]

    def battery(self):
        """feature 0x1004 (unified battery) getStatus -> {'percent', 'charging'},
        or None if the feature is absent/unreadable. Best-effort; never raises so a
        battery hiccup can't break a profile read. `percent` is state-of-charge 0..100;
        `charging` is true for the charging/near-full/complete states."""
        try:
            idx = self.get_feature_index(FEATURE_UNIFIED_BATTERY)
            if not idx:
                return None
            d = self.request(idx, 0x01)              # fn1 get_status
            return {'percent': d[0], 'charging': len(d) > 2 and d[2] in (1, 2, 3)}
        except Exception:
            return None

    def profile_headers(self):
        """Read the directory sector and return [(sector, enabled), ...].
        The directory lives in RAM sector 0x0000, or ROM sector 0x0100 if RAM
        is blank; each entry is 4 bytes [sector(BE), enabled, pad], terminated
        by 0xFFFF."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        base = 0x0000
        first = self._mem_read16(idx, base, 0)
        if first[0:4] in (b'\x00\x00\x00\x00', b'\xff\xff\xff\xff'):
            base = 0x0100                      # fall back to ROM
        headers = []
        offset = 0
        while True:
            chunk = self._mem_read16(idx, base, offset)
            if chunk[0:2] == b'\xff\xff':
                break
            sector = (chunk[0] << 8) | chunk[1]
            enabled = chunk[2]
            headers.append((sector, enabled))
            offset += 4
            if offset > 15 * 4:                # safety: directory can't be huge
                break
        return headers

    def _mem_read16(self, feature_index, sector, offset):
        """One 16-byte memory read (fn 0x50) at (sector, offset)."""
        params = bytes([sector >> 8, sector & 0xFF, offset >> 8, offset & 0xFF])
        return self.request(feature_index, OB_MEMORY_READ, params)[:16]

    def read_sector(self, sector, size):
        """Read `size` bytes of a profile sector, 16 at a time. Mirrors Solaar's
        awkward tail handling so the final (possibly partial) line lines up."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        out = b''
        offset = 0
        while offset < size - 15:
            out += self._mem_read16(idx, sector, offset)
            offset += 16
        tail = self._mem_read16(idx, sector, size - 16)
        out += tail[16 + offset - size:]
        return out[:size]

    # --- ONBOARD_PROFILES (0x8100) WRITE (mutates the device) ---------------
    def write_sector(self, sector, data):
        """Write a full sector image `data` (including its CRC trailer) to
        `sector`. Skips the write if the current contents already match
        (comparing everything but the 2 CRC bytes) and returns False; returns
        True if a write actually happened.

        MUTATES the device — callers MUST have taken a backup and MUST read-back-
        verify afterwards. Sequence mirrors Solaar/libratbag: 0x60 begin (addr +
        length), 0x70 write each 16-byte line (final line may be short), 0x80 end.
        """
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        if not idx:
            raise RuntimeError('device has no ONBOARD_PROFILES (0x8100) feature')
        data = bytes(data)
        n = len(data)
        current = self.read_sector(sector, n)
        if current[:-2] == data[:-2]:
            return False                     # unchanged (ignoring CRC) -> no write
        self.request(idx, OB_ADDR_WRITE,
                     bytes([sector >> 8, sector & 0xFF, 0, 0, n >> 8, n & 0xFF]))
        o = 0
        while o < n - 1:
            self.request(idx, OB_WRITE, data[o:o + 16])
            o += 16
        self.request(idx, OB_WRITE_END)
        return True

    def write_partial(self, sector, offset, data):
        """SUPERSEDED by write_full_sector_no_crc — kept only to document the dead
        end. The theory was that writing a region that excludes the last 2 (CRC)
        bytes would skip CRC validation. It does NOT: WRITE_END validates the whole
        sector's CRC unconditionally, so even a partial write that never touches the
        trailer is rejected with err 0x04 (the trailer still isn't a valid checksum
        afterward). Because this method lets request() raise on that 0x04, it can
        never complete a macro write. Use write_full_sector_no_crc instead, which
        swallows the 0x04 (the bytes commit regardless — see that method)."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        if not idx:
            raise RuntimeError('device has no ONBOARD_PROFILES (0x8100) feature')
        data = bytes(data)
        n = len(data)
        self.request(idx, OB_ADDR_WRITE,
                     bytes([sector >> 8, sector & 0xFF, offset >> 8, offset & 0xFF, n >> 8, n & 0xFF]))
        o = 0
        while o < n:
            self.request(idx, OB_WRITE, data[o:o + 16])
            o += 16
        self.request(idx, OB_WRITE_END)
        return True

    def write_full_sector_no_crc(self, sector, data):
        """Write a FULL-sector image `data` (macro opcodes + 0xFF fill, length ==
        sector_size, with NO valid CRC trailer) — how G HUB stores macro sectors.

        WRITE_END reports HID++ err 0x04 (HWError) because the trailer isn't a valid
        CRC, but the firmware COMMITS the bytes to flash regardless. We swallow ONLY
        that 0x04 and treat the write as done; every other error re-raises. This
        "written anyway" behaviour is documented in cvuchener/hidpp
        (IOnboardProfiles.h: "memoryWriteEnd may throw errors ... but the data is
        written anyway"; its hidpp20-write-page tool catches HWError and returns
        success) and is independently used by libratbag PR #1850.

        MUTATES the device. Target an ERASED (all-0xFF) sector — flash programs
        1->0 only, so the macro bytes land in erased space and the untouched trailer
        stays 0xFF. Because the 0x04 is the one signal we ignore, the caller MUST
        read the sector back to confirm the commit."""
        idx = self.get_feature_index(FEATURE_ONBOARD_PROFILES)
        if not idx:
            raise RuntimeError('device has no ONBOARD_PROFILES (0x8100) feature')
        data = bytes(data)
        n = len(data)
        self.request(idx, OB_ADDR_WRITE,
                     bytes([sector >> 8, sector & 0xFF, 0, 0, n >> 8, n & 0xFF]))
        o = 0
        while o < n:
            self.request(idx, OB_WRITE, data[o:o + 16])
            o += 16
        try:
            self.request(idx, OB_WRITE_END)
        except HidppError as e:
            if e.code != 0x04:               # only the expected soft-CRC error is OK
                raise
        return True


# --- device discovery --------------------------------------------------------
def _candidate_paths(pids=G502X_PIDS):
    """All hidraw /dev paths for the Logitech mouse (and its receiver), so we can
    probe each for the one that actually answers HID++."""
    paths = []
    seen = set()
    for d in hid.enumerate():
        if d.get('vendor_id') != LOGITECH_VID:
            continue
        pid = d.get('product_id')
        # accept the mouse's own PIDs and the receiver (0xC547) it may sit behind
        if pid in pids or pid == 0xC547:
            p = d.get('path')
            if p and p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def find_device(pids=G502X_PIDS):
    """Open the hidraw node that actually speaks HID++ for the target mouse.
    Tries each candidate interface with a ROOT ping; returns an open Hidpp, or
    None if nothing answered. READ-ONLY (ping only)."""
    for path in _candidate_paths(pids):
        try:
            h = Hidpp(path)
            h.ping()                       # only the HID++ collection replies
            # make sure the onboard feature is really there before claiming it
            if h.get_feature_index(FEATURE_ONBOARD_PROFILES):
                return h
            h.close()
        except (HidppError, TimeoutError, OSError, ValueError):
            try:
                h.close()
            except Exception:
                pass
            continue
    return None
