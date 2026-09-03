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

G7_IDENTITIES = {
    0x109B: 'wired configuration',
    0x109C: 'dongle configuration',
    0x100A: 'HID transition',
    0x1022: 'native/GIP',
}

UDEV_RULES = {
    'GameSir': ('/etc/udev/rules.d/70-gamesir.rules',
                os.path.join(HERE, '70-gamesir.rules')),
    'Logitech (G502 X)': ('/etc/udev/rules.d/70-deadband-g502x.rules',
                          os.path.join(HERE, 'packaging', 'udev',
                                       '70-deadband-g502x.rules')),
}


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
        import hid
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
                    'product': product, 'usb_path': usb_path})
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
        import hid
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
        'verdict': [],
    }
    try:
        import hid
        rep['hidapi_version'] = getattr(hid, '__version__', '?')
    except Exception:
        rep['hidapi_version'] = 'IMPORT FAILED'
    try:
        from vendors.gamesir.usb_transport import BACKEND, library_version
        version = library_version()
        rep['raw_usb_backend'] = BACKEND + (f' — {version}' if version else ' — unavailable')
    except Exception:
        rep['raw_usb_backend'] = 'native libusb-1.0 — unavailable'

    for label, (installed, source) in UDEV_RULES.items():
        rep['rules'][label] = {
            'installed': os.path.exists(installed),
            'source_present': os.path.exists(source),
            'current': _same_file(installed, source),
        }

    for n in _sysfs_nodes():
        entry = dict(n)
        entry.update(open_ladder(n['node']))
        rep['nodes'].append(entry)

    try:
        from gs_common import find_controllers
        for dev in find_controllers():
            if dev.get('pid') not in G7_IDENTITIES:
                continue
            meta = dev.get('usb') or {}
            node = '/dev/bus/usb/%03d/%03d' % (meta.get('bus', 0), meta.get('address', 0))
            rep['usb_devices'].append({
                'pid': dev['pid'], 'identity': G7_IDENTITIES[dev['pid']],
                'product': dev.get('product', ''), 'port': dev['port'],
                'node': node, 'access': os.access(node, os.R_OK | os.W_OK),
            })
    except Exception:
        pass

    # ---- overall verdicts, most-specific first ----
    gsnodes = [n for n in rep['nodes'] if n['vid'] == 0x3537]
    if not gsnodes and not rep['usb_devices']:
        rep['verdict'].append(
            'No GameSir device is enumerated. If one is plugged in, that is a '
            'kernel/USB-level problem (check `dmesg`), not an app problem.')
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
        elif not rule.get('installed') or not rule.get('current'):
            rep['verdict'].append(
                'GameSir device found but NOT openable (permission denied), and '
                'the current udev rule is NOT installed. Fix:\n'
                f'    sudo cp "{UDEV_RULES["GameSir"][1]}" /etc/udev/rules.d/\n'
                '    sudo udevadm control --reload-rules && sudo udevadm trigger\n'
                'then UNPLUG AND REPLUG the controller.')
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
        ready = [n for n in rep['usb_devices'] if n['pid'] in (0x109B, 0x109C)]
        transition = [n for n in rep['usb_devices'] if n['pid'] == 0x100A]
        native = [n for n in rep['usb_devices'] if n['pid'] == 0x1022]
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
                'configuration requires holding MENU (START) + SHARE together.')

    monodes = [n for n in rep['nodes'] if n['vid'] == 0x046D]
    if monodes and all(n['verdict'] == 'no-access' for n in monodes):
        rep['verdict'].append(
            'Logitech mouse found but not openable — install its udev rule '
            '(Settings shows the commands on the mouse page) and replug.')
    return rep


def format_report(rep):
    """The structured report as paste-into-an-issue text."""
    L = []
    L.append('## Deadband diagnostic report')
    L.append(f'- Deadband {rep.get("version", "?")}')
    L.append(f'- OS: {rep["os"]}  (kernel {rep["kernel"]})')
    L.append(f'- Session: {rep["session"]} / {rep["desktop"]}')
    L.append(f'- Python {rep["python"]}, hidapi {rep.get("hidapi_version", "?")} '
             f'— backend: {rep["hidapi_backend"]}')
    L.append(f'- Raw USB: {rep.get("raw_usb_backend", "?")}')
    for label, r in rep['rules'].items():
        status = ('NOT INSTALLED' if not r['installed'] else
                  'installed' if r.get('current') else 'installed, OUTDATED')
        L.append(f'- udev rule ({label}): {status}')
    L.append('')
    L.append('### Devices')
    if not rep['nodes']:
        L.append('(no GameSir/Logitech HID devices enumerated)')
    for n in rep['nodes']:
        vend = VENDOR_NAMES.get(n['vid'], hex(n['vid']))
        L.append(f'- {n["node"]}  {vend} {n["pid"]:04x}  "{n["product"]}"'
                 + (f'  port {n["usb_path"]}' if n['usb_path'] else ''))
        L.append(f'    perms: {n["perms"]}')
        L.append(f'    os.open: {n["os_open"]}   hidapi: {n["hid_open"]}'
                 f'   → {n["verdict"].upper()}')
    for n in rep.get('usb_devices', []):
        L.append(f'- {n["node"]}  GameSir {n["pid"]:04x} '
                 f'({n.get("identity", "unknown")})  "{n["product"]}" port {n["port"]}')
        L.append('    raw USB access: ' + ('OK' if n['access'] else 'PERMISSION DENIED'))
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
