"""
Deadband diagnostics ("doctor") — why can't the app talk to my device?
======================================================================
One shared engine behind three faces:

  * `deadband --doctor`            (terminal, for maintainers / bug reports)
  * Settings → Diagnostics window  (in-app, with a "Copy report" button)
  * the reader's access classifier (the "found but can't open" banner)

The core insight (from issue #1): sysfs ENUMERATION needs no permissions, so a
controller can look perfectly detected while every actual open() fails — and the
app used to show that as an eternal "Searching…". The doctor walks the same
ladder for every device node and says exactly which rung broke:

  stat  →  os.open(O_RDWR)  →  hidapi open_path  →  vendor stream probe

Dependency-light on purpose: stdlib + hid only, NO Qt — it must run headless
(`--doctor`) and never take down the app if something here breaks.
"""

import glob
import os
import platform
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# vendors we care about: GameSir controllers + the Logitech mouse work
VENDOR_NAMES = {0x3537: 'GameSir', 0x046D: 'Logitech'}

# Sourced from the protocol module rather than copied, because the copy already
# drifted: the app learned to name other G7 Pro editions and this table didn't,
# so a pad on one of them was skipped entirely and never appeared in a report --
# hiding the single most likely explanation for "it's found but I see no config".
try:
    from vendors.gamesir.models.g7pro import protocol as _g7
    # Every configurable identity comes from CONFIG_PIDS, never a hand list.
    # This used to name 109b/109c literally and then add the UNCONFIRMED
    # editions, so a CONFIGURABLE edition other than Shadow Ember fell through
    # both: when 10ba was promoted it vanished from every diagnostics report,
    # device line and verdict alike, while the app itself drove it fine.
    G7_IDENTITIES = {
        pid: '%s configuration (%s)' % (
            {True: 'wired', False: 'dongle'}.get(_g7.connection_kind(pid), 'config'),
            _g7.edition_name(pid).replace(' (dongle)', ''))
        for pid in _g7.CONFIG_PIDS
    }
    G7_IDENTITIES.update({
        _g7.PID_HID: 'HID transition',
        _g7.PID_NATIVE: 'native/GIP',
    })
    G7_UNCONFIRMED = dict(_g7.UNCONFIRMED_EDITIONS)
    G7_WRITABLE = tuple(_g7.CONFIG_PIDS)
    G7_NEEDS_USB = frozenset(_g7.CONFIG_PIDS + _g7.TRANSITION_PIDS)
except Exception:                      # partial install -- report what we can
    G7_IDENTITIES = {
        0x109B: 'wired configuration', 0x109C: 'dongle configuration',
        0x10BA: 'wired configuration', 0x10BB: 'dongle configuration',
        0x100A: 'HID transition', 0x1022: 'native/GIP',
    }
    G7_UNCONFIRMED = {}
    G7_WRITABLE = (0x109B, 0x109C, 0x10BA, 0x10BB)
    G7_NEEDS_USB = frozenset((0x109B, 0x109C, 0x10BA, 0x10BB, 0x100A))
G7_IDENTITIES.update({pid: f'{name} (not configurable)'
                      for pid, name in G7_UNCONFIRMED.items()})

# A rule can legitimately live in EITHER directory: /etc is for rules an admin
# installed by hand, /usr/lib is where a package puts its own. Checking only /etc
# told every AUR user their rule was "NOT INSTALLED" and sent them off to copy a
# file they already had, out of a source tree the package manager had cleaned up
# (issue #10). Check both, and report which one answered.
UDEV_RULES = {
    'GameSir': (('/etc/udev/rules.d/70-gamesir.rules',
                 '/usr/lib/udev/rules.d/70-gamesir.rules'),
                os.path.join(HERE, '70-gamesir.rules')),
    'Logitech (G502 X)': (('/etc/udev/rules.d/70-deadband-g502x.rules',
                           '/usr/lib/udev/rules.d/70-deadband-g502x.rules'),
                          os.path.join(HERE, 'packaging', 'udev',
                                       '70-deadband-g502x.rules')),
}


def _find_rule(paths):
    """The first of `paths` that exists, or None. /etc wins so a hand-installed
    override is what gets reported when both are present."""
    for path in paths:
        if os.path.exists(path):
            return path
    return None


# --------------------------------------------------------------------- helpers
def _os_release(field='PRETTY_NAME'):
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith(field + '='):
                    return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return 'unknown'


def is_nixos():
    """NixOS needs different advice everywhere: /etc is generated (a `sudo cp`
    into /etc/udev/rules.d is wrong/ephemeral) and Python packages are immutable
    (a `pip install` fix doesn't apply). Point at the declarative config — the
    community flake wires up both."""
    return _os_release('ID').lower() == 'nixos'


# Community NixOS flake (Epaphroditus): NixOS module w/ udev wiring + a
# hidraw-backend hidapi override — the NixOS-native fix for both problem classes.
NIX_FLAKE_URL = 'https://codeberg.org/Epaphroditus/gamesir-linux-tools-nix'


def _hidapi_backend():
    """'hidraw' / 'libusb' / 'unknown' — from the path format hid.enumerate()
    returns. The pip 'hidapi' package can be built against either; the libusb
    backend CANNOT open /dev/hidraw paths, which breaks the whole app while
    enumeration (sysfs) still looks fine."""
    try:
        import hidcompat as hid
        for d in hid.enumerate():
            p = d.get('path') or b''
            if isinstance(p, bytes):
                p = p.decode(errors='replace')
            if p.startswith('/dev/hidraw'):
                return 'hidraw'
            if p:
                return f'libusb (paths like {p!r})'
        return 'unknown (no HID devices visible to hidapi)'
    except Exception as e:
        return f'unknown (hid.enumerate failed: {e})'


def _vendor_channel(hidraw_sysfs):
    """What vendor channel a HID node DECLARES, from its report descriptor in
    sysfs (no permissions needed, nothing sent to the device).

    -> 'pages 0xfff0/0xff00, report ids 0x0f 0x10 0x12', 'none declared', or
    '' if unreadable. Report ids are those declared while a vendor usage page
    (0xff00 and up) is current. This is what tells a new pad's protocol apart:
    the Cyclone family declares 0xfff0 with 0x0f/0x10/0x12, the Tarantula 8K
    0xa2/0x43 -- and it used to need a shell one-liner from the user to see."""
    try:
        with open(os.path.join(hidraw_sysfs, 'device', 'report_descriptor'), 'rb') as f:
            desc = f.read()
    except OSError:
        return ''
    pages, ids, vendor, i = [], [], False, 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:                          # long item: skip it whole
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        size = (b & 0x03) if (b & 0x03) != 3 else 4
        val = int.from_bytes(desc[i + 1:i + 1 + size], 'little')
        if (b & 0xFC) == 0x04:                 # Usage Page (global)
            vendor = val >= 0xFF00
            if vendor and val not in pages:
                pages.append(val)
        elif (b & 0xFC) == 0x84 and vendor:    # Report ID (global)
            if val not in ids:
                ids.append(val)
        i += 1 + size
    if not pages:
        return 'none declared'
    return ('pages ' + '/'.join(f'{p:#06x}' for p in pages)
            + (', report ids ' + ' '.join(f'{r:#04x}' for r in ids) if ids else ''))


def _sysfs_nodes():
    """Every /dev/hidrawN owned by a vendor we care about, from sysfs (needs no
    permissions — the same enumeration the app's detection uses).
    -> [{node, vid, pid, product, usb_path}]"""
    out = []
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*'),
                       key=lambda p: int(os.path.basename(p)[6:])):
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        vid = pid = None
        product = ''
        for line in uevent.splitlines():
            if line.startswith('HID_ID='):
                try:
                    _, v, p = line.split('=', 1)[1].split(':')
                    vid, pid = int(v, 16), int(p, 16)
                except ValueError:
                    pass
            elif line.startswith('HID_NAME='):
                product = line.split('=', 1)[1]
        if vid not in VENDOR_NAMES:
            continue
        node = '/dev/' + os.path.basename(path)
        # USB topology (port path) — helps tell two units apart
        try:
            usb = os.path.realpath(path)
            usb_path = usb.split('/usb')[1].split('/')[2] if '/usb' in usb else ''
        except Exception:
            usb_path = ''
        out.append({'node': node, 'vid': vid, 'pid': pid,
                    'product': product, 'usb_path': usb_path,
                    'vendor_channel': _vendor_channel(path) if vid == 0x3537 else ''})
    return out


def _perm_string(node):
    try:
        st = os.stat(node)
        import pwd, grp
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            group = str(st.st_gid)
        return f'{stat.filemode(st.st_mode)} {owner}:{group}'
    except OSError as e:
        return f'stat failed: {e.strerror}'


def open_ladder(node):
    """The diagnostic ladder for one /dev node. Returns a dict:
       {perms, os_open: 'ok'|errno-name, hid_open: 'ok'|error, verdict}
    verdict ∈ ok | no-access | backend | busy | error"""
    r = {'perms': _perm_string(node), 'os_open': None, 'hid_open': None,
         'verdict': 'error'}
    # rung 1: plain os.open — the ground truth for filesystem/ACL access
    try:
        fd = os.open(node, os.O_RDWR)
        os.close(fd)
        r['os_open'] = 'ok'
    except OSError as e:
        import errno as E
        r['os_open'] = E.errorcode.get(e.errno, str(e.errno))
        r['verdict'] = ('no-access' if e.errno in (E.EACCES, E.EPERM)
                        else 'busy' if e.errno == E.EBUSY else 'error')
        return r
    # rung 2: hidapi open — catches a libusb-backend build that can't take
    # hidraw paths even though the node itself is openable
    try:
        import hidcompat as hid
        d = hid.device()
        d.open_path(node.encode())
        d.close()
        r['hid_open'] = 'ok'
        r['verdict'] = 'ok'
    except Exception as e:
        r['hid_open'] = str(e) or type(e).__name__
        r['verdict'] = 'backend'
    return r


def classify_open_failure(node):
    """Cheap classifier for the reader: after hidapi failed to open `node`,
    say WHY — 'no-access' (fs permission) or 'backend' (hidapi build can't
    open an openable node). Never raises."""
    try:
        return open_ladder(node)['verdict']
    except Exception:
        return 'error'


# --------------------------------------------------------------------- report
PLATFORM_VENDORS = {0x057E: 'Nintendo', 0x054C: 'Sony', 0x045E: 'Microsoft'}


def _usb_links():
    """Link speed and fastest input rate of every GameSir/Logitech USB device.

    A pad's poll rate is only real if the link can carry it. At USB Full Speed
    (12 Mb/s) an interrupt endpoint is polled at most once per millisecond, so
    1000 reports/s is a hard ceiling; GameSir's "8K" pads re-enumerate as High
    Speed (480 Mb/s) with a 125 us input endpoint when set above 1000 Hz. A pad
    stuck at Full Speed while set higher produces reports faster than the host
    can collect them (issue #21) -- this line is what tells those apart.
    -> [{port, vid, pid, product, speed_mbps, in_interval_us, max_rate}]"""
    out = []
    for d in sorted(glob.glob('/sys/bus/usb/devices/*/')):
        try:
            vid = int(open(d + 'idVendor').read(), 16)
            if vid not in VENDOR_NAMES:
                continue
            pid = int(open(d + 'idProduct').read(), 16)
            speed = float(open(d + 'speed').read())
        except (OSError, ValueError):
            continue
        # Logitech makes webcams and headsets too; only its HID devices (mice,
        # receivers) belong in a controller report.
        if vid == 0x046D:
            classes = set()
            for ifc in glob.glob(d + '*:*/bInterfaceClass'):
                try:
                    classes.add(open(ifc).read().strip())
                except OSError:
                    pass
            if '03' not in classes or '0e' in classes or '01' in classes:
                continue
        try:
            product = open(d + 'product').read().strip()
        except OSError:
            product = ''
        fastest = None
        for ep in glob.glob(d + '*:*/ep_*'):
            try:
                if open(ep + '/type').read().strip() != 'Interrupt':
                    continue
                if not int(open(ep + '/bEndpointAddress').read(), 16) & 0x80:
                    continue                                  # IN endpoints only
                iv = open(ep + '/interval').read().strip()    # e.g. "125us", "1ms"
                us = float(iv[:-2]) * (1000 if iv.endswith('ms') else 1)
            except (OSError, ValueError):
                continue
            if us > 0 and (fastest is None or us < fastest):
                fastest = us
        out.append({'port': os.path.basename(d.rstrip('/')), 'vid': vid, 'pid': pid,
                    'product': product, 'speed_mbps': speed, 'in_interval_us': fastest,
                    'max_rate': round(1e6 / fastest) if fastest else None})
    return out


def _platform_mode_devices():
    """USB devices presenting as another platform's controller.

    A GameSir pad's platform-mode combo changes its USB VENDOR id, not just its
    product id -- in Switch mode it enumerates as Nintendo. Everything else here
    scans vendor 0x3537 only, so a pad that got mode-switched vanishes from the
    report entirely and the verdict blames the kernel. This finds it. Best
    effort: a failure here must never cost someone their report."""
    out = []
    try:
        for d in glob.glob('/sys/bus/usb/devices/*/'):
            try:
                vid = int(open(d + 'idVendor').read().strip(), 16)
            except (OSError, ValueError):
                continue
            if vid in PLATFORM_VENDORS:
                try:
                    pid = int(open(d + 'idProduct').read().strip(), 16)
                except (OSError, ValueError):
                    continue
                name = ''
                try:
                    name = open(d + 'product').read().strip()
                except OSError:
                    pass
                out.append({'vendor': PLATFORM_VENDORS[vid], 'vid': vid,
                            'pid': pid, 'product': name})
    except Exception:
        pass
    return out


def _interfaces(sysfs):
    """Interface class/subclass/protocol + bound driver for a USB device.

    Distinguishes a vendor CONFIG interface from an Xbox INPUT one. Both are
    vendor-class with no hidraw node, so from the device line alone they look
    identical -- which is exactly the ambiguity that makes it hard to say whether
    a new edition's identity is configurable or just XInput. `ff/5d/01` is Xbox
    360 XInput; `ff/47/d0` is Xbox GIP.

    Do NOT read "xpad-bound GIP" as "input only". The G7 Pro's verified config
    identity (10ba) has two ff/47/d0 interfaces, and its config channel IS the
    xpad-bound interface 0 -- Deadband detaches xpad to use it. An earlier
    version of this docstring said the opposite, and that reasoning briefly got
    a configurable-looking identity (1003) filed as evidence against itself."""
    out = []
    if not sysfs:
        return out
    try:
        for iface in sorted(glob.glob(os.path.join(sysfs, '*:*'))):
            def rd(name, default='?'):
                try:
                    return open(os.path.join(iface, name)).read().strip()
                except OSError:
                    return default
            link = os.path.join(iface, 'driver')
            drv = os.path.basename(os.path.realpath(link)) if os.path.islink(link) else '-'
            eps = []
            for ep in sorted(glob.glob(os.path.join(iface, 'ep_*'))):
                try:
                    addr = open(os.path.join(ep, 'bEndpointAddress')).read().strip()
                    kind = open(os.path.join(ep, 'type')).read().strip()
                    eps.append(f'0x{int(addr, 16):02x} {kind.lower()}')
                except (OSError, ValueError):
                    continue
            out.append({
                'name': os.path.basename(iface),
                'cls': rd('bInterfaceClass'), 'sub': rd('bInterfaceSubClass'),
                'proto': rd('bInterfaceProtocol'), 'driver': drv, 'eps': eps,
            })
    except Exception:
        pass
    return out


def _version():
    """App version (plus the git commit when running from a checkout). Never
    raises -- a missing version must not cost someone their whole report."""
    try:
        from version import build_id
        return build_id()
    except Exception:
        return '?'


def _same_file(left, right):
    try:
        with open(left, 'rb') as a, open(right, 'rb') as b:
            return a.read() == b.read()
    except OSError:
        return False


def collect():
    """Gather the full diagnostic picture (structured)."""
    rep = {
        'app': 'Deadband',
        'version': _version(),
        'os': _os_release(),
        'nixos': is_nixos(),
        'kernel': platform.release(),
        'python': sys.version.split()[0],
        'session': os.environ.get('XDG_SESSION_TYPE', '?'),
        'desktop': os.environ.get('XDG_CURRENT_DESKTOP', '?'),
        'hidapi_backend': _hidapi_backend(),
        'rules': {},
        'nodes': [],
        'usb_devices': [],
        'usb_links': [],
        'evdev': [],
        'verdict': [],
    }
    try:
        import hidcompat as hid
        rep['hidapi_version'] = getattr(hid, '__version__', '?')
        rep['hidapi_impl'] = getattr(hid, 'IMPL', 'hidapi (cython)')
    except Exception:
        rep['hidapi_version'] = 'IMPORT FAILED'
    try:
        from vendors.gamesir.usb_transport import BACKEND, library_version
        version = library_version()
        rep['raw_usb_backend'] = BACKEND + (f' — {version}' if version else ' — unavailable')
    except Exception:
        rep['raw_usb_backend'] = 'native libusb-1.0 — unavailable'

    for label, (paths, source) in UDEV_RULES.items():
        found = _find_rule(paths)
        rep['rules'][label] = {
            'installed': found is not None,
            'path': found,
            'packaged': bool(found and found.startswith('/usr/lib/')),
            'source_present': os.path.exists(source),
            # with no source tree (an installed app) we can't compare, so don't
            # claim the rule is stale -- that reads as a problem when it isn't
            'current': _same_file(found, source) if (found and os.path.exists(source)) else None,
        }

    for n in _sysfs_nodes():
        entry = dict(n)
        entry.update(open_ladder(n['node']))
        rep['nodes'].append(entry)

    # Which button-code convention each gamepad node uses. Read passively from
    # the node's advertised EV_KEY bitmap -- nothing has to be pressed. This is
    # here because "X and Y are swapped" was open across two issues (#10, #17)
    # with no way to tell from a report which of the two layouts the reporter's
    # pad used, and the answer is one ioctl away.
    try:
        import reader
        from gs_common import parse_devices, VENDOR_VID
        for d in parse_devices():
            if d['vendor'] != VENDOR_VID:
                continue
            for ev in d.get('events', []):
                try:
                    fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
                except OSError as e:
                    rep['evdev'].append({'node': ev, 'name': d.get('name', ''),
                                         'pid': d.get('product'), 'error': e.strerror})
                    continue
                try:
                    keys = reader.keybits(fd)
                finally:
                    os.close(fd)
                pad = sorted(c for c in keys if 0x130 <= c <= 0x13e)
                if not pad:
                    continue          # keyboard/mouse/consumer node, not a pad
                rep['evdev'].append({
                    'node': ev, 'name': d.get('name', ''), 'pid': d.get('product'),
                    'count': len(pad), 'btn_c': reader.BTN_C in keys,
                    'layout': reader._key_map(keys)[1],
                })
    except Exception:
        pass

    try:
        from gs_common import find_controllers
        for dev in find_controllers():
            if dev.get('pid') not in G7_IDENTITIES:
                continue
            # 3537:1004 is shared with the T4 Kaleid (mainline xpad); only report
            # it as a G7 Pro identity when the device names itself one.
            try:
                if not _g7.is_g7_device(dev.get('pid'), dev.get('product')):
                    continue
            except NameError:
                pass
            meta = dev.get('usb') or {}
            node = '/dev/bus/usb/%03d/%03d' % (meta.get('bus', 0), meta.get('address', 0))
            rep['usb_devices'].append({
                'pid': dev['pid'], 'identity': G7_IDENTITIES[dev['pid']],
                'product': dev.get('product', ''), 'port': dev['port'],
                'node': node, 'access': os.access(node, os.R_OK | os.W_OK),
                'interfaces': _interfaces(meta.get('sysfs') or dev.get('sysfs')),
            })
    except Exception:
        pass

    # ---- overall verdicts, most-specific first ----
    gsnodes = [n for n in rep['nodes'] if n['vid'] == 0x3537]
    # Tarantula Pro 8K in its non-PC mode. It auto-detects its host; config only
    # works in PC/XBOX mode (3537:103d). As 103c its vendor channel is declared
    # but never answers, so say what that means rather than list an unknown pad.
    if any(n['pid'] == 0x103C for n in gsnodes):
        rep['verdict'].append(
            'GameSir Tarantula (3537:103c) found in its non-PC mode, where it can\'t be '
            'configured. Configuration needs its PC/XBOX mode (3537:103d). GameSir\'s '
            'manual: hold Home + X for 2 seconds (the light turns green); holding Home '
            'for 10 seconds restores automatic mode detection.')
    if not gsnodes and not rep['usb_devices']:
        others = _platform_mode_devices()
        if others:
            found = ', '.join(f'{o["vendor"]} {o["vid"]:04x}:{o["pid"]:04x}'
                              + (f' "{o["product"]}"' if o['product'] else '')
                              for o in others)
            rep['verdict'].append(
                'No GameSir device is enumerated, but a controller from another '
                f'platform is: {found}. A GameSir pad changes its USB VENDOR id '
                'when you switch platform mode, so if you just used a button '
                'combo it may have moved to Switch/PS mode rather than into '
                'configuration mode. Put it back in Xbox/XInput mode and re-check.')
        else:
            rep['verdict'].append(
                'No GameSir device is enumerated. If one is plugged in, check '
                '`lsusb` — a platform-mode combo changes the USB vendor id, so a '
                'mode-switched pad will appear under another vendor entirely. If '
                'it is absent from `lsusb` too, that is a kernel/USB-level '
                'problem (check `dmesg`), not an app problem.')
    elif gsnodes and all(n['verdict'] == 'no-access' for n in gsnodes):
        rule = rep['rules'].get('GameSir', {})
        if rep.get('nixos'):
            rep['verdict'].append(
                'GameSir device found but NOT openable (permission denied). On '
                'NixOS the udev rule must come from your configuration (files '
                'copied into /etc/udev/rules.d are generated over). Easiest: use '
                f'the community flake — {NIX_FLAKE_URL} — whose NixOS module '
                'wires the rule up. Or add it declaratively:\n'
                '    services.udev.extraRules = builtins.readFile '
                f'"{UDEV_RULES["GameSir"][1]}";\n'
                'then `sudo nixos-rebuild switch` and UNPLUG AND REPLUG the '
                'controller.')
        elif not rule.get('installed') or rule.get('current') is False:
            if rule.get('source_present'):
                fix = (f'    sudo cp "{UDEV_RULES["GameSir"][1]}" /etc/udev/rules.d/\n'
                       '    sudo udevadm control --reload-rules && sudo udevadm trigger')
            else:
                # installed app, no source tree: reinstalling the package is the
                # route, not copying a file they don't have
                fix = ('    reinstall/update the package (it ships the rule), then\n'
                       '    sudo udevadm control --reload-rules && sudo udevadm trigger')
            rep['verdict'].append(
                'GameSir device found but NOT openable (permission denied), and '
                'the current udev rule is NOT installed. Fix:\n'
                + fix + '\nthen UNPLUG AND REPLUG the controller.')
        else:
            rep['verdict'].append(
                'GameSir device found but NOT openable (permission denied) even '
                'though the udev rule IS installed. Unplug and replug the device '
                '(udevadm trigger does not always re-apply the access tag), and '
                'make sure you are on a local (not SSH/remote) login.')
    elif any(n['verdict'] == 'backend' for n in gsnodes):
        msg = ('The device node is openable, but the Python hidapi library cannot '
               'open it — your hidapi is built with the libusb backend '
               f'({rep["hidapi_backend"]}), which cannot open /dev/hidraw devices. ')
        if rep.get('nixos'):
            msg += ('On NixOS, override the package to build with the hidraw '
                    'backend — the community flake already does this:\n'
                    f'    {NIX_FLAKE_URL}\n'
                    'or in your own config:\n'
                    '    python3Packages.hidapi.overrideAttrs (o: { env = '
                    '(o.env or {}) // { HIDAPI_WITH_HIDRAW = "1"; }; })')
        else:
            msg += ('The pip package DEFAULTS to libusb when built from source; '
                    'rebuild it with the hidraw backend (HIDAPI_WITH_HIDRAW is '
                    'the selector, and --no-cache-dir is required or pip '
                    'silently reuses the previously built libusb wheel from its '
                    'cache):\n'
                    '    HIDAPI_WITH_HIDRAW=1 pip install --user --force-reinstall '
                    '--no-cache-dir --no-binary :all: hidapi\n'
                    'Build prerequisites: gcc, python3-devel, and libudev headers '
                    '— on Fedora/Bazzite: rpm-ostree install systemd-devel (then '
                    'reboot); on Debian/Ubuntu: sudo apt install build-essential '
                    'python3-dev libudev-dev.')
        rep['verdict'].append(msg)
    elif any(n['verdict'] == 'ok' for n in gsnodes):
        rep['verdict'].append('GameSir device access: OK.')
    if rep['usb_devices']:
        # Sourced from protocol.CONFIG_PIDS, never hand-listed: this line used to
        # read (0x109B, 0x109C) and so told Amazon-edition owners their working
        # configuration identity was unrecognised.
        ready = [n for n in rep['usb_devices'] if n['pid'] in G7_WRITABLE]
        transition = [n for n in rep['usb_devices'] if n['pid'] == 0x100A]
        native = [n for n in rep['usb_devices'] if n['pid'] == 0x1022]
        other_ed = [n for n in rep['usb_devices'] if n['pid'] in G7_UNCONFIRMED]
        if other_ed:
            names = ', '.join(sorted({G7_UNCONFIRMED[n['pid']] for n in other_ed}))
            pids = ', '.join(sorted({f'3537:{n["pid"]:04x}' for n in other_ed}))
            rep['verdict'].append(
                f'G7 Pro {names} found ({pids}). Input works. Deadband '
                'recognises this edition but does not configure it: no config '
                'write has ever been confirmed on this USB id. The editions '
                'differ only by that id, so it may well work — it has just never '
                'been proven, and guessing is how a different controller '
                'entirely ended up on this list once (issue #14). If you are '
                'willing to try it, say so on an issue; that is exactly what '
                'would unblock it.')
        if ready:
            if any(n['access'] for n in ready):
                kinds = ', '.join(sorted({n['identity'].split()[0] for n in ready}))
                rep['verdict'].append(
                    f'G7 Pro {kinds} configuration access: OK.')
            else:
                rep['verdict'].append(
                    'G7 Pro configuration identity found, but raw USB access is '
                    'denied; install the current 70-gamesir.rules and replug it.')
        elif transition:
            if any(n['access'] for n in transition):
                rep['verdict'].append(
                    'G7 Pro 100a HID identity found; Deadband can transition it '
                    'automatically to 109b/109c for configuration.')
            else:
                rep['verdict'].append(
                    'G7 Pro 100a HID identity found, but the automatic transition '
                    'is blocked by raw USB permissions; install the current '
                    '70-gamesir.rules and replug it.')
        elif native:
            rep['verdict'].append(
                'G7 Pro 1022 native/GIP identity found. Input is available, but '
                'configuration requires holding SHARE + MENU together. Be aware '
                'that combo also resets the active profile\'s remaps and the '
                'Shift layer, so back them up first if you care about them.')

    monodes = [n for n in rep['nodes'] if n['vid'] == 0x046D]
    if monodes and all(n['verdict'] == 'no-access' for n in monodes):
        rep['verdict'].append(
            'Logitech mouse found but not openable — install its udev rule '
            '(Settings shows the commands on the mouse page) and replug.')
    try:
        rep['usb_links'] = _usb_links()
    except Exception:
        pass                      # best effort: never cost someone their report
    return rep


def format_report(rep):
    """The structured report as paste-into-an-issue text."""
    L = []
    L.append('## Deadband diagnostic report')
    L.append(f'- Deadband {rep.get("version", "?")}')
    L.append(f'- OS: {rep["os"]}  (kernel {rep["kernel"]})')
    L.append(f'- Session: {rep["session"]} / {rep["desktop"]}')
    L.append(f'- Python {rep["python"]}, {rep.get("hidapi_impl", "hidapi")} {rep.get("hidapi_version", "?")} '
             f'— backend: {rep["hidapi_backend"]}')
    L.append(f'- Raw USB: {rep.get("raw_usb_backend", "?")}')
    for label, r in rep['rules'].items():
        if not r['installed']:
            status = 'NOT INSTALLED'
        elif r.get('current') is False:
            status = 'installed, OUTDATED'
        else:
            # current is None when there's no source tree to compare against (an
            # installed app). Installed is all we can honestly claim.
            status = 'installed' + (' (packaged)' if r.get('packaged') else '')
        L.append(f'- udev rule ({label}): {status}')
    L.append('')
    L.append('### Devices')
    # Link speed per physical device: decides what poll rate is actually deliverable.
    for u in rep.get('usb_links', []):
        sp = u['speed_mbps']
        kind = ('High Speed' if sp >= 480 else 'Full Speed' if sp >= 12 else 'Low Speed')
        rate = (f', input every {u["in_interval_us"]:g} us (up to {u["max_rate"]} reports/s)'
                if u.get('max_rate') else '')
        L.append(f'- USB {u["port"]}  {VENDOR_NAMES.get(u["vid"], hex(u["vid"]))} '
                 f'{u["pid"]:04x}  "{u["product"]}"  link: {sp:g}M ({kind}){rate}')
    if not rep['nodes']:
        L.append('(no GameSir/Logitech HID devices enumerated)')
    for n in rep['nodes']:
        vend = VENDOR_NAMES.get(n['vid'], hex(n['vid']))
        L.append(f'- {n["node"]}  {vend} {n["pid"]:04x}  "{n["product"]}"'
                 + (f'  port {n["usb_path"]}' if n['usb_path'] else ''))
        L.append(f'    perms: {n["perms"]}')
        L.append(f'    os.open: {n["os_open"]}   hidapi: {n["hid_open"]}'
                 f'   → {n["verdict"].upper()}')
        if n.get('vendor_channel'):
            L.append(f'    vendor channel: {n["vendor_channel"]}')
    for n in rep.get('evdev', []):
        if n.get('error'):
            L.append(f'- {n["node"]}  "{n["name"]}"  cannot open: {n["error"]}')
            continue
        L.append(f'- {n["node"]}  "{n["name"]}"  {n["count"]}/15 gamepad buttons'
                 f'  layout: {n["layout"].upper()}')
        if n['layout'] == 'sequential':
            L.append('    advertises BTN_C, so the kernel numbered its buttons '
                     'straight through and Deadband\'s button names may be wrong '
                     'for this pad. Please mention this on an issue.')

    for n in rep.get('usb_devices', []):
        L.append(f'- {n["node"]}  GameSir {n["pid"]:04x} '
                 f'({n.get("identity", "unknown")})  "{n["product"]}" port {n["port"]}')
        if n['pid'] not in G7_NEEDS_USB:
            # Deadband only opens the identities it can configure, plus the one
            # it transitions through. Everything else -- a detect-only edition,
            # or 1022, which is transitioned by holding SHARE + MENU on the pad
            # rather than over USB -- is never opened, so a denial here is the
            # intended state and not a fault. Printing PERMISSION DENIED sent a
            # reporter chasing a udev rule that is absent on purpose (#17).
            L.append('    raw USB access: not required (Deadband never opens this identity)')
        else:
            L.append('    raw USB access: ' + ('OK' if n['access'] else 'PERMISSION DENIED'))
        for i in n.get('interfaces', []):
            cls, sub, proto = i['cls'], i['sub'], i['proto']
            # ff/47/d0 = Xbox GIP, ff/5d/01 = Xbox 360 XInput. A higher unclaimed
            # GIP interface is usually audio. Interface 0 carries input -- AND, on
            # a G7 Pro config identity like 10ba, the config channel itself.
            if (cls, sub, proto) == ('ff', '47', 'd0'):
                kind = ('   <- Xbox GIP (input; on a G7 Pro config identity, also config)'
                        if i['name'].endswith(':1.0') else '   <- Xbox GIP (usually audio)')
            elif (cls, sub, proto) == ('ff', '5d', '01'):
                kind = '   <- Xbox 360 XInput (input)'
            elif cls == 'ff' and i['driver'] == '-':
                kind = '   <- vendor, unclaimed (config candidate)'
            else:
                kind = ''
            L.append(f"    iface {i['name']}: class {cls}/{sub}/{proto}"
                     f"  driver {i['driver']}{kind}")
            if i.get('eps'):
                # our transport hardcodes EP_OUT 0x02 / EP_IN 0x82; a mismatch
                # means the claim succeeds and every transfer then times out
                L.append(f"      endpoints: {', '.join(i['eps'])}")
    L.append('')
    L.append('### Verdict')
    for v in rep['verdict'] or ['Nothing conclusive — attach this report to the issue.']:
        L.append(v)
    return '\n'.join(L)


def run_cli():
    print(format_report(collect()))
    return 0


if __name__ == '__main__':
    raise SystemExit(run_cli())
