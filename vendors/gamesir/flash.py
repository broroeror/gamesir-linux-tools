#!/usr/bin/env python3
"""
GameSir Cyclone 2 - firmware BACKUP & RESTORE (Linux)
=====================================================
Scope is deliberately narrow: back up the controller's CURRENT firmware, and
restore a firmware-only image you previously backed up (config/calibration
preserved). There is NO arbitrary-file flashing, NO full-image (config-
overwriting) flashing, and NO CLI — this is an import-only module the app's
Backup & Restore panel drives. It is a backup/restore tool, not a firmware
modifier.

Mechanism:  enter loader (vendor cmd 0f 17 55 88)  ->  read/write over the
loader  ->  reset. The controller's MCU is a JieLi BR23; the vendor command
reboots it into its BR23 UBOOT loader (USB mass-storage, vid 0x4c4a) which
exposes SPI-NOR read/write over SCSI.

External dependency (NOT bundled): the actual loader read/write is done by
`jl-uboot-tool` (kagaimiq, MIT), which you install yourself. If it's not present,
firmware backup/restore is simply unavailable (see `tooling_available()`); the
rest of the app is unaffected. Point JLUBOOT_DIR at your install if it isn't
alongside this file.

Safety: an interrupted write isn't fatal — the BR23 mask-ROM re-enters UBOOT on
the next power-cycle, so you can re-run restore. Before writing a byte, the
in-loader identity guard reads the chip's own flash header and refuses anything
that isn't the wired controller (a 2.4GHz dongle reads 'GS_C2_Dongle' and is
rejected). No sudo needed once the udev rule (70-gamesir.rules) is installed.

Firmware library (firmware/, git-ignored — your images stay local):
  cyclone2_<ver>_fw.bin    firmware-only restore image (config preserved)
  backups/                 full per-unit dumps made by a backup
"""
import contextlib
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time

import hid

from gs_common import (find_vendor_hidraw, read_firmware_version, pad,
                       firmware_version, device_pid)
import controller_profile as profiles

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(HERE, 'firmware')
BACKUP_DIR = os.path.join(FW_DIR, 'backups')
JLUBOOT_DIR = os.path.join(HERE, 'jl-uboot-tool')
JLUBOOT_PY = os.path.join(JLUBOOT_DIR, 'jluboottool.py')


def tooling_available():
    """True if the external jl-uboot-tool (kagaimiq) is installed alongside this
    module. It is NOT bundled — without it, firmware backup/restore is unavailable
    but the rest of the app runs normally. The panel checks this to show an
    'install jl-uboot-tool' note instead of failing on click."""
    return os.path.isfile(JLUBOOT_PY)

PRODUCT = 'cyclone2'
FLASH_SIZE = 0x100000      # 1 MB SPI-NOR
FW_REGION = 0x77000        # firmware region (header + body), excludes config sectors
ENTER_LOADER = (0x0F, 0x17, 0x55, 0x88)
LOADER_VID = '4c4a'

# Flash-header identity. JieLi replicates a small header at flash offset 0x1000;
# its bytes at +0x10 are a plaintext product-id string (up to 16 bytes). Confirmed
# VERSION-INDEPENDENT against real dumps: a Cyclone 2 reads 'GS_C2_ADC_DEVICE' on
# fw 3.26 AND 3.52, while its 2.4GHz dongle reads 'GS_C2_Dongle' on fw 1.19 AND
# 1.21. We read this IN the loader, straight off the chip, so it can't be spoofed
# by a USB descriptor and doesn't depend on firmware version numbers -- the
# authoritative, brick-proof answer to "is this actually a controller?".
IDENTITY_ADDR = 0x1000     # header base (sector-aligned block read)
IDENTITY_LEN = 0x20        # bytes to read
IDENTITY_OFF = 0x10        # product-id string offset within that read (abs 0x1010)


class FlashError(Exception):
    pass


# --- jl-uboot-tool plumbing ---------------------------------------------------
def _jluboot_python():
    """Prefer jl-uboot-tool's venv (has crcmod/pyyaml/pycryptodomex/tqdm)."""
    venv = os.path.join(JLUBOOT_DIR, 'venv', 'bin', 'python')
    return venv if os.path.exists(venv) else sys.executable


def _find_loader():
    """Return the /dev/sgN path of the JieLi loader, or None. Needs sg access."""
    sys.path.insert(0, JLUBOOT_DIR)
    try:
        from jldevfind import find_jl_devices
    except Exception as e:
        raise FlashError(f"can't import jl-uboot-tool (vendored at {JLUBOOT_DIR}): {e}")
    for d in find_jl_devices(venfilter='BR23'):
        return d['path']
    return None


def _sg_nodes():
    return set(glob.glob('/dev/sg*'))


def _jluboot(sgpath, command, inherit=True):
    """Run one jl-uboot-tool shell command (e.g. 'write 0x0 img.bin') on sgpath.
    `command` is passed as a SINGLE argv token (the tool splits it itself)."""
    py = _jluboot_python()
    argv = [py, JLUBOOT_PY, '--chip', 'br23', '--device', sgpath, command]
    kw = {} if inherit else dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return subprocess.run(argv, cwd=JLUBOOT_DIR, text=True, **kw)


@contextlib.contextmanager
def _scratch_path(name):
    """Yield a private scratch file path for a jl-uboot-tool flash readback.

    jl-uboot-tool opens and writes a path we hand it (so we can't pass it an fd),
    and these tools are documented to run under sudo. A predictable name from
    tempfile.mktemp() in world-writable /tmp would let a local user pre-plant a
    symlink there and redirect that write to an arbitrary file — as root. Instead
    we hand it a file inside a fresh 0700 dir only we own; no other user can
    traverse it or plant a symlink inside, and the readback path can never alias
    the image being verified. The dir (and any readback in it) is removed after."""
    d = tempfile.mkdtemp(prefix='gsflash-')
    try:
        yield os.path.join(d, name)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- loader entry / exit ------------------------------------------------------
def current_version():
    """bcdDevice firmware version of the connected gamepad, or None."""
    return read_firmware_version()


def _send_enter_loader_hid():
    """Send the enter-loader vendor command over a fresh hidraw handle (CLI use)."""
    node, name, _ = find_vendor_hidraw()
    if not node:
        raise FlashError("no controller found: plug in the Cyclone 2 in Xbox mode "
                         "(use the Start / pause buttons), or it's already in the loader "
                         "but /dev/sg* isn't accessible (install the udev rule or use sudo).")
    try:
        d = hid.device()
        d.open_path(node.encode())
        d.write(pad(*ENTER_LOADER))
        d.close()
    except Exception as e:
        # a write error is normal if it drops off instantly
        sys.stderr.write(f"(enter-loader write: {e})\n")


def _guard_wired(guard_node=None):
    """Normal-mode PRE-FILTER: refuse to enter the loader unless the connected
    GameSir device is a MODEL this flasher supports, identified by its USB product
    id (version-independent).

    This is only a courtesy early-out. The AUTHORITATIVE brick guard is
    assert_write_target_ok(), which runs IN the loader and reads the chip's own
    flash-header identity right before any write -- so even if a device slips past
    this PID check (e.g. a dongle relaying under a controller-like product id), no
    non-controller can ever be WRITTEN. We deliberately do NOT gate on firmware
    version (bcdDevice major): the major IS the version, so gating on it would
    eventually lock a legitimate controller out of updates if a future hardware
    revision ships in the old dongle major range. Identity (PID + the in-loader
    flash header), never version, decides.

    `guard_node` pins the check to the exact device the loader command targets --
    the GUI passes the SELECTED controller's node so we don't validate one
    controller while the command targets another when several are plugged in.
    Without it we fall back to the live vendor interface (the CLI's own target).

    Fails CLOSED: an unrecognised or unreadable product id is refused."""
    node = guard_node
    if node is None:
        node, _name, _ = find_vendor_hidraw()
    if not node:
        return                      # nothing in normal mode; loader-wait handles it
    # Refuse a non-flashable MODEL before touching the loader. The GUI already
    # gates on the recognized model, but the CLI's own enter-loader path bypasses
    # control.send_cmd's recognition guard, so this is the one check that protects
    # both. (A controller already IN the loader has no GameSir node, so node is
    # None above and we never get here -- loader recovery of a parked controller is
    # unaffected; assert_write_target_ok still guards that write.)
    pid = device_pid(node)
    prof = profiles.by_product_id(pid) if pid is not None else None
    if prof is None or not prof.can_flash:
        which = f" (USB product 0x{pid:04x})" if pid is not None else ""
        raise FlashError(
            f"Refusing to flash: the connected controller{which} isn't a model this "
            "flasher supports — it targets the Cyclone 2 (JieLi BR23) only. If it's "
            "connected over the 2.4GHz wireless DONGLE, connect it DIRECTLY with a "
            "USB cable (Xbox mode: use the Start / pause buttons) and retry.")


def enter_loader(timeout=8.0, send=None, guard_node=None):
    """Ensure the controller is in BR23 UBOOT; return its /dev/sgN path.

    If already in the loader, just find it. Otherwise emit the enter-loader
    command and wait for the loader to appear. `send` is an optional callable
    that emits the command over an existing channel (the GUI passes its own
    control writer so we don't open a second hidraw handle); default uses hidraw.
    `guard_node` is the hidraw node the command targets, so the PID pre-filter
    validates that exact device (see _guard_wired).

    The PID pre-filter here is a courtesy early-out; the brick-proof guarantee is
    assert_write_target_ok(), run by the callers IN the loader before any write.
    """
    try:
        existing = _find_loader()
    except FlashError:
        existing = None
    if existing:
        return existing

    _guard_wired(guard_node)         # PID pre-filter; write-time identity gate is authoritative

    before = _sg_nodes()
    (send or _send_enter_loader_hid)()

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            sg = _find_loader()
        except FlashError:
            sg = None
        if sg:
            return sg
    # didn't find it: distinguish "no loader" from "no permission"
    new = _sg_nodes() - before
    if new:
        nodes = ', '.join(sorted(new))
        raise FlashError(f"loader appeared ({nodes}) but jl-uboot-tool can't open it. "
                         "Install the udev rule (70-gamesir.rules) and reload, or run with sudo.")
    raise FlashError("loader did not appear after enter-loader command.")


def reset_controller(sgpath=None):
    """Kick the loader back into normal (app) mode. The reset drops the device
    off USB mid-command, so jl-uboot-tool reports a benign transfer error."""
    sg = sgpath or _find_loader()
    if not sg:
        return False
    _jluboot(sg, 'reset', inherit=False)   # swallow the expected error
    return True


# --- flash / read / verify ----------------------------------------------------
def _looks_like_raw(path):
    if path.lower().endswith('.ufw'):
        raise FlashError(f"{os.path.basename(path)} is a packaged .ufw, NOT a raw "
                         "flash image. Only raw .bin dumps can be written.")
    sz = os.path.getsize(path)
    if sz == 0 or sz > FLASH_SIZE:
        raise FlashError(f"{os.path.basename(path)} size {sz} is not a valid raw image "
                         f"(expected 1..{FLASH_SIZE} bytes).")
    return sz


def flash_image(image_path, sgpath, verify=True):
    """Write image_path at flash address 0 (erases only its own length, so a
    firmware-only image leaves the config sectors intact). Optionally verify."""
    n = _looks_like_raw(image_path)
    assert_write_target_ok(sgpath, image_path)   # brick guard before any write
    print(f"Flashing {os.path.basename(image_path)} ({n} bytes / 0x{n:x}) ...")
    r = _jluboot(sgpath, f"write 0x0 {image_path}")
    if r.returncode != 0:
        raise FlashError("write failed (jl-uboot-tool returned non-zero). "
                         "Power-cycle the controller -> it auto-enters UBOOT -> re-flash.")
    if verify:
        print("Verifying ...")
        if not verify_region(image_path, sgpath):
            raise FlashError("VERIFY MISMATCH! Do NOT unplug. Re-flash a known-good image now.")
        print("Verify OK - flash matches the image.")


def verify_region(image_path, sgpath):
    n = os.path.getsize(image_path)
    with _scratch_path('readback.bin') as tmp:
        r = _jluboot(sgpath, f"read 0x0 0x{n:x} {tmp}", inherit=False)
        if r.returncode != 0 or not os.path.exists(tmp):
            return False
        with open(tmp, 'rb') as a, open(image_path, 'rb') as b:
            return a.read() == b.read()


def read_full(out_path, sgpath, inherit=True):
    r = _jluboot(sgpath, f"read 0x0 0x{FLASH_SIZE:x} {out_path}", inherit=inherit)
    if r.returncode != 0:
        raise FlashError("flash read failed.")
    return out_path


# --- authoritative in-loader brick guard --------------------------------------
def _ascii_run(buf, off, maxlen):
    """Leading run of printable ASCII at off, stopping at the first non-printable
    byte (the 0x00/0xff pad or the checksum bytes that bound the field)."""
    out = []
    for b in buf[off:off + maxlen]:
        if 32 <= b < 127:
            out.append(chr(b))
        else:
            break
    return ''.join(out) or None


def read_flash_identity(sgpath):
    """Read the product-id string from the chip's flash header (IN the loader), or
    None if it can't be read. This is the chip's OWN identity, not a USB
    descriptor, so it tells a real controller from a 2.4GHz dongle regardless of
    firmware version."""
    with _scratch_path('identity.bin') as tmp:
        r = _jluboot(sgpath, f"read 0x{IDENTITY_ADDR:x} 0x{IDENTITY_LEN:x} {tmp}",
                     inherit=False)
        if r.returncode != 0 or not os.path.exists(tmp):
            return None
        with open(tmp, 'rb') as f:
            buf = f.read()
        return _ascii_run(buf, IDENTITY_OFF, 16)


def image_identity(image_path):
    """The product-id string embedded in a raw firmware image (offset 0x1010), or
    None -- so we can also refuse an image whose identity doesn't match the chip
    (e.g. a dongle image aimed at a controller)."""
    try:
        with open(image_path, 'rb') as f:
            f.seek(IDENTITY_ADDR)
            buf = f.read(IDENTITY_LEN)
    except OSError:
        return None
    return _ascii_run(buf, IDENTITY_OFF, 16)


def _flashable_identities():
    """Set of flash-header identities we recognise as flashable controllers
    (e.g. {'GS_C2_ADC_DEVICE'}). A dongle's 'GS_C2_Dongle' is deliberately absent,
    so writing to a dongle is refused."""
    return {p.flash_identity for p in profiles.ALL
            if p.can_flash and p.flash_identity}


def assert_write_target_ok(sgpath, image_path):
    """AUTHORITATIVE brick guard -- runs IN the loader, immediately before any
    flash write. Reads the chip's own flash-header identity and refuses unless:
      * the chip identifies as a known flashable controller (not a dongle), AND
      * the image about to be written carries that SAME identity.
    Fails CLOSED (refuses on any unreadable/mismatched identity) and resets the
    loader back to normal mode, so a wrongly-parked device (e.g. a dongle) recovers
    on its own. Version-independent and read straight off the silicon, so it holds
    even if USB descriptors or firmware version numbers change in the future."""
    allowed = _flashable_identities()
    chip_id = read_flash_identity(sgpath)
    img_id = image_identity(image_path)
    problem = None
    if not chip_id:
        problem = ("couldn't read the connected chip's flash identity to confirm "
                   "it's a flashable controller")
    elif chip_id not in allowed:
        problem = (f"the connected chip identifies itself as '{chip_id}', which is "
                   "NOT a flashable controller (a 2.4GHz wireless DONGLE reads "
                   "'GS_C2_Dongle' here, and flashing it bricks it)")
    elif not img_id:
        problem = "couldn't read the firmware image's identity to match it to the chip"
    elif img_id != chip_id:
        problem = (f"the image is for '{img_id}' but the connected chip is "
                   f"'{chip_id}' -- refusing to write a mismatched image")
    if problem:
        reset_controller(sgpath)     # un-park the device; nothing was written
        raise FlashError(
            "Refusing to write firmware: " + problem + ".\n"
            "  Nothing was written and the device was returned to normal mode.\n"
            "  Connect the controller DIRECTLY over USB (Xbox mode: use the Start / "
            "pause buttons) and retry.")


# --- high-level operations (used by both the CLI and the GUI bridge) ----------
def flash_version(version=None, *, verify=True,
                  on_progress=None, send=None, guard_node=None):
    """RESTORE a firmware image from the library (identified by `version`), gated by
    the in-loader identity guard. This writes back a firmware-only image you already
    backed up (config/calibration preserved) — it deliberately CANNOT flash an
    arbitrary file or a full image (that capability was removed for the public
    build; this stays a backup/restore tool, not a firmware modifier).

    on_progress(phase:str) is called at each phase (GUI). send is an optional
    enter-loader emitter (GUI passes its own control writer); guard_node is the
    node that emitter targets, so the dongle guard checks the right device.
    Returns the image.
    """
    quiet = on_progress is not None
    prog = on_progress or (lambda _p: None)
    image = pick_firmware(version)
    n = _looks_like_raw(image)

    prog("Entering loader…")
    sg = enter_loader(send=send, guard_node=guard_node)
    # AUTHORITATIVE brick guard: confirm from the chip's own flash header that this
    # is the expected controller (not a dongle) before writing a single byte.
    assert_write_target_ok(sg, image)
    prog(f"Writing firmware ({n // 1024} KB)…")
    r = _jluboot(sg, f"write 0x0 {image}", inherit=not quiet)
    if r.returncode != 0:
        raise FlashError("write failed. Power-cycle the controller -> it auto-enters "
                         "UBOOT -> re-flash.")
    if verify:
        prog("Verifying…")
        if not verify_region(image, sg):
            raise FlashError("VERIFY MISMATCH! Do NOT unplug. Re-flash a known-good image now.")
    prog("Resetting…")
    reset_controller(sg)
    prog("Done")
    return image


def backup_current(label=None, on_progress=None, send=None, derive_fw=True,
                   guard_node=None):
    """Dump the connected controller's full flash into firmware/backups/.

    Reads the version first (must be done before entering the loader). Returns the
    backup path. guard_node pins the dongle guard to the emitter's device.
    """
    prog = on_progress or (lambda _p: None)
    # Pin the version to the SELECTED unit (guard_node's bcdDevice) so the backup
    # and derived library image aren't mislabelled with another connected
    # controller's version. The CLI passes no guard_node -> first vendor device.
    ver = (firmware_version(guard_node) if guard_node else current_version()) or 'unknown'
    os.makedirs(BACKUP_DIR, exist_ok=True)
    lbl = (label + '_') if label else ''
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = os.path.join(BACKUP_DIR, f"{PRODUCT}_{lbl}{ver}_{stamp}_full.bin")

    prog("Entering loader…")
    sg = enter_loader(send=send, guard_node=guard_node)
    prog("Reading flash (1 MB)…")
    read_full(out, sg, inherit=on_progress is None)
    prog("Resetting…")
    reset_controller(sg)

    if derive_fw and os.path.getsize(out) == FLASH_SIZE and ver != 'unknown':
        fwpath = os.path.join(FW_DIR, f"{PRODUCT}_{ver}_fw.bin")
        if not os.path.exists(fwpath):
            with open(out, 'rb') as a, open(fwpath, 'wb') as b:
                b.write(a.read()[:FW_REGION])
    prog("Done")
    return out, ver


# --- firmware library ---------------------------------------------------------
def list_firmware():
    """Return [{path, product, version, kind}] for the flashable library."""
    out = []
    for path in sorted(glob.glob(os.path.join(FW_DIR, '*.bin'))):
        base = os.path.basename(path)[:-4]
        parts = base.split('_')
        if len(parts) >= 3 and parts[-1] in ('fw', 'full'):
            out.append({'path': path, 'product': '_'.join(parts[:-2]),
                        'version': parts[-2], 'kind': parts[-1]})
    return out


def pick_firmware(version):
    """Path of a firmware-ONLY library image for `version` (config preserved on
    restore). Full images are never selected for writing."""
    for f in list_firmware():
        if f['version'] == version and f['kind'] == 'fw' and f['product'] == PRODUCT:
            return f['path']
    raise FlashError(f"no {PRODUCT} {version} firmware image in {FW_DIR}. "
                     "Use 'Back up current firmware' first to create a restore point.")


# NOTE: the standalone CLI (status/list/backup/flash/reset, including flashing an
# arbitrary --file or a --full config-overwriting image) was intentionally REMOVED
# for the public build. This module is now import-only, exposing exactly the
# backup + firmware-only restore the app's Backup & Restore panel uses, so it can't
# be driven as a general firmware flasher.
