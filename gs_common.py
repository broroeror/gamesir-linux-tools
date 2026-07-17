"""
GameSir Cyclone 2 - shared helpers for the vendor interface (hidraw)
===================================================================
The vendor protocol is only live in XInput/Xbox mode (hold green ~2s); in PS4
mode it's inert.

When the controller is wired into the PC, it exposes TWO vendor (VID 0x3537)
interfaces: one streams an EMPTY 0x12 report, the other (with a heartbeat)
streams the real, populated enhanced report. So we don't just take the first
match -- we probe and pick the interface that actually carries live data.
"""

import glob
import os
import re
import time
import hid

VENDOR_VID = 0x3537   # GameSir native vendor interface
REPORT_LEN = 64       # 0x0F output report = report ID + 63 payload bytes


def pad(*payload):
    """Pad a command payload to the fixed 64-byte output report length."""
    return list(payload) + [0x00] * (REPORT_LEN - len(payload))


def read_firmware_version(product_id=None):
    """Return the controller firmware version string (e.g. '3.52'), or None.

    The official Windows app's Info button makes NO network or USB-command
    traffic (captures 22/24): the version comes straight from the USB device
    descriptor's bcdDevice field, which the OS already has from enumeration.
    hidapi exposes it as `release_number`; bcdDevice is BCD-encoded as JJ.MN
    (high byte = major, low byte = minor), so 0x0352 -> '3.52'.

    `product_id` narrows the match to a specific model when several GameSir
    controllers are connected (else the first vendor device is used)."""
    try:
        rel = next((d.get('release_number', 0) for d in hid.enumerate()
                    if d.get('vendor_id') == VENDOR_VID
                    and (product_id is None or d.get('product_id') == product_id)),
                   None)
    except Exception:
        return None
    if not rel:
        return None
    return f'{rel >> 8:x}.{rel & 0xff:02x}'


def find_vendor_nodes():
    """Return list of (devnode, hidraw_name, hid_name) for all GameSir vendor
    interfaces (matched by USB vendor id, so it survives mode/node changes)."""
    nodes = []
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*'),
                       key=lambda p: int(os.path.basename(p)[6:])):
        name = os.path.basename(path)
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = hid_name = ''
        for line in uevent.splitlines():
            if line.startswith('HID_ID='):
                hid_id = line.split('=', 1)[1]
            elif line.startswith('HID_NAME='):
                hid_name = line.split('=', 1)[1]
        parts = hid_id.split(':')
        if len(parts) == 3:
            try:
                vid = int(parts[1], 16)
            except ValueError:
                vid = 0
            if vid == VENDOR_VID:
                nodes.append((f'/dev/{name}', name, hid_name))
    return nodes


def _usb_device_dir(hidraw_sysfs):
    """Walk up from a hidraw's sysfs path to the owning USB DEVICE directory
    (the one holding idVendor/busnum), which is shared by all interfaces of the
    same physical controller. Returns the dir path, or None."""
    d = os.path.realpath(hidraw_sysfs)
    for _ in range(12):                       # bounded walk up the device tree
        if os.path.exists(os.path.join(d, 'idVendor')) and \
           os.path.exists(os.path.join(d, 'busnum')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def find_controllers():
    """Enumerate DISTINCT physical GameSir controllers (not per-interface).

    The Cyclone exposes two vendor interfaces (empty + live) on one USB device,
    so we group hidraw nodes by their owning USB device (topology) and return one
    entry per controller: {id, pid, nodes, port}. `id`/`port` is the USB bus+path
    (stable per physical port; serials are empty so this is our unique key), and
    `nodes` are that controller's /dev/hidraw* paths."""
    by_dev = {}
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*'),
                       key=lambda p: int(os.path.basename(p)[6:])):
        name = os.path.basename(path)
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = next((ln.split('=', 1)[1] for ln in uevent.splitlines()
                       if ln.startswith('HID_ID=')), '')
        parts = hid_id.split(':')
        if len(parts) != 3:
            continue
        try:
            vid, pid = int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            continue
        if vid != VENDOR_VID:
            continue
        devdir = _usb_device_dir(path)
        if devdir is None:
            continue
        try:
            bus = open(os.path.join(devdir, 'busnum')).read().strip()
            devpath = open(os.path.join(devdir, 'devpath')).read().strip()
        except OSError:
            bus, devpath = '?', os.path.basename(devdir)
        # USB product string — needed to disambiguate the 0x0575 PID shared by the
        # Cyclone ("GameSir-Cyclone 2") and the idle G7 Pro 8K dongle ("Gamepad").
        try:
            product = open(os.path.join(devdir, 'product')).read().strip()
        except OSError:
            product = ''
        port = f'{bus}-{devpath}'
        entry = by_dev.setdefault(port, {'id': port, 'port': port, 'pid': pid,
                                         'product': product, 'nodes': []})
        entry['nodes'].append(f'/dev/{name}')
    return list(by_dev.values())


def parse_devices():
    """Parse /proc/bus/input/devices into a list of {name, vendor, product,
    handlers, events} — `events` is that device's /dev/input/event* nodes. Core
    evdev enumeration used by the press-to-select loop (and diagnostics)."""
    try:
        with open('/proc/bus/input/devices') as fh:
            blocks = fh.read().split('\n\n')
    except OSError:
        return []
    out = []
    for blk in blocks:
        if not blk.strip():
            continue
        name = vendor = product = None
        handlers = ''
        for line in blk.splitlines():
            if line.startswith('I:'):
                mv = re.search(r'Vendor=([0-9a-fA-F]{4})', line)
                mp = re.search(r'Product=([0-9a-fA-F]{4})', line)
                if mv:
                    vendor = int(mv.group(1), 16)
                if mp:
                    product = int(mp.group(1), 16)
            elif line.startswith('N: Name='):
                name = line.split('=', 1)[1].strip().strip('"')
            elif line.startswith('H: Handlers='):
                handlers = line.split('=', 1)[1].strip()
        events = re.findall(r'\bevent(\d+)\b', handlers)
        out.append({
            'name': name, 'vendor': vendor, 'product': product,
            'handlers': handlers,
            'events': ['/dev/input/event' + e for e in events],
        })
    return out


def evdev_port(event_node):
    """USB port id (busnum-devpath) for a /dev/input/eventN node, matching the
    ids from find_controllers(), or None. Lets a button press seen on evdev be
    attributed to the exact physical controller it came from."""
    sysfs = os.path.join('/sys/class/input', os.path.basename(event_node))
    devdir = _usb_device_dir(sysfs)
    if devdir is None:
        return None
    try:
        bus = open(os.path.join(devdir, 'busnum')).read().strip()
        devpath = open(os.path.join(devdir, 'devpath')).read().strip()
    except OSError:
        return None
    return f'{bus}-{devpath}'


def device_bcd(devnode):
    """USB bcdDevice (firmware version) for a /dev/hidrawN node as an int
    (e.g. 0x0326 for fw 3.26), or None if unreadable.

    Mainly a display/labelling helper now (firmware_version builds on it to pin a
    version string to one physical unit). NOTE: the firmware flasher no longer uses
    the bcd major to detect the 2.4GHz dongle — that gated on the *version*, which
    would eventually lock a legit controller out of updates; the dongle guard is now
    identity-based (USB product id + the chip's in-loader flash-header signature)."""
    name = os.path.basename(devnode)
    devdir = _usb_device_dir(os.path.join('/sys/class/hidraw', name))
    if devdir is None:
        return None
    try:
        return int(open(os.path.join(devdir, 'bcdDevice')).read().strip(), 16)
    except (OSError, ValueError):
        return None


def device_pid(devnode):
    """USB idProduct (int) for the device that owns a /dev/hidrawN node, or None.
    Lets a caller identify the exact model behind a node — e.g. the flasher
    refusing a non-Cyclone before it sends the loader command."""
    name = os.path.basename(devnode)
    devdir = _usb_device_dir(os.path.join('/sys/class/hidraw', name))
    if devdir is None:
        return None
    try:
        return int(open(os.path.join(devdir, 'idProduct')).read().strip(), 16)
    except (OSError, ValueError):
        return None


def firmware_version(devnode):
    """Firmware version string (e.g. '3.52') for the exact device that owns a
    /dev/hidrawN node, or None. Unlike read_firmware_version(pid), which returns
    the FIRST vendor device matching a product id, this pins to one physical unit
    via its bcdDevice — so with two identical controllers it reports the selected
    one's version, not whichever hidapi happens to enumerate first."""
    bcd = device_bcd(devnode)
    return f'{bcd >> 8:x}.{bcd & 0xff:02x}' if bcd else None


def connected_product_ids():
    """USB product ids (ints) of all connected GameSir vendor interfaces.

    Parsed from each hidraw node's HID_ID (`bus:VID:PID`, hex). Lets the app
    tell a Cyclone (0575/100b) from a G7 (10ba) to pick the right profile.
    Matched by vendor id, so it survives mode/node renumbering like the rest."""
    pids = []
    for path in glob.glob('/sys/class/hidraw/hidraw*'):
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = next((ln.split('=', 1)[1] for ln in uevent.splitlines()
                       if ln.startswith('HID_ID=')), '')
        parts = hid_id.split(':')
        if len(parts) == 3:
            try:
                vid, pid = int(parts[1], 16), int(parts[2], 16)
            except ValueError:
                continue
            if vid == VENDOR_VID and pid not in pids:
                pids.append(pid)
    return pids


def _streams_live_data(devnode, secs=1.0):
    """Open devnode, send heartbeats, and report whether it yields a POPULATED
    0x12 report (sticks rest at 128 / battery non-zero, so an empty all-zero
    stream is rejected)."""
    try:
        d = hid.device()
        d.open_path(devnode.encode())
        d.set_nonblocking(True)
    except Exception:
        return False
    live = False
    last_hb = 0.0
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            now = time.time()
            if now - last_hb > 0.4:
                try:
                    d.write(pad(0x0F, 0xF2))
                except Exception:
                    pass
                last_hb = now
            try:
                data = d.read(64, timeout_ms=50)
            except OSError:
                break
            if (data and len(data) >= 37 and data[0] == 0x12 and
                    (data[1] or data[2] or data[3] or data[4] or data[36])):
                # a short 0x12 report (crafted/faulty device) would IndexError past
                # the try's finally-only guard and kill the reader thread, so the
                # length check gates the deep indexing.
                live = True
                break
    finally:
        try:
            d.close()
        except Exception:
            pass
    return live


def has_live_pad(devnodes):
    """Is a controller actually BEHIND this USB device, or is it an empty dongle?

    A dongle with nothing paired to it still enumerates and still streams 0x12 —
    just all-zero — and answers no vendor command at all, so a POPULATED stream is
    the only reliable signal. Identity is no help: every dongle reports the same
    firmware-constant USB serial (an 8K's and both Cyclones' read identically), and
    the pairing address lives in flash, reachable only from the bootloader.

    NOTE a pad in a non-Xbox mode also fails this (the vendor channel is Xbox-only),
    so callers must not treat False as "definitely no hardware" — see the reader."""
    return any(_streams_live_data(n) for n in (devnodes or []))


def pick_live_node(devnodes):
    """From ONE controller's candidate /dev/hidraw* nodes, return the one that
    carries live enhanced data, or the first if we can't tell. A wired Cyclone
    exposes an empty + a real interface, so we probe and prefer the populated
    0x12 stream. (A G7 speaks GIP, not 0x12, so it falls through to the first.)"""
    if not devnodes:
        return None
    if len(devnodes) == 1:
        return devnodes[0]
    for n in devnodes:
        if _streams_live_data(n):
            return n
    return devnodes[0]


def find_vendor_hidraw():
    """Return (devnode, name, hid_name) for the GameSir vendor interface that
    carries live enhanced data, or (None, None, None) if not found.

    With a single match we return it directly (fast path). With several (e.g.
    wired: empty + real interfaces) we probe and prefer the one streaming a
    populated 0x12 report, falling back to the first match.
    """
    nodes = find_vendor_nodes()
    if not nodes:
        return (None, None, None)
    if len(nodes) == 1:
        return nodes[0]
    for node in nodes:
        if _streams_live_data(node[0]):
            return node
    return nodes[0]
