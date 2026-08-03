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

UDEV_RULES = {
    'GameSir': ('/etc/udev/rules.d/70-gamesir.rules',
                os.path.join(HERE, '70-gamesir.rules')),
    'Logitech (G502 X)': ('/etc/udev/rules.d/70-deadband-g502x.rules',
                          os.path.join(HERE, 'packaging', 'udev',
                                       '70-deadband-g502x.rules')),
}


# --------------------------------------------------------------------- helpers
def _os_release():
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return 'unknown'


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
def collect():
    """Gather the full diagnostic picture (structured)."""
    rep = {
        'app': 'Deadband',
        'os': _os_release(),
        'kernel': platform.release(),
        'python': sys.version.split()[0],
        'session': os.environ.get('XDG_SESSION_TYPE', '?'),
        'desktop': os.environ.get('XDG_CURRENT_DESKTOP', '?'),
        'hidapi_backend': _hidapi_backend(),
        'rules': {},
        'nodes': [],
        'verdict': [],
    }
    try:
        import hid
        rep['hidapi_version'] = getattr(hid, '__version__', '?')
    except Exception:
        rep['hidapi_version'] = 'IMPORT FAILED'

    for label, (installed, source) in UDEV_RULES.items():
        rep['rules'][label] = {
            'installed': os.path.exists(installed),
            'source_present': os.path.exists(source),
        }

    for n in _sysfs_nodes():
        entry = dict(n)
        entry.update(open_ladder(n['node']))
        rep['nodes'].append(entry)

    # ---- overall verdicts, most-specific first ----
    gsnodes = [n for n in rep['nodes'] if n['vid'] == 0x3537]
    if not gsnodes:
        rep['verdict'].append(
            'No GameSir device is enumerated. If one is plugged in, that is a '
            'kernel/USB-level problem (check `dmesg`), not an app problem.')
    elif all(n['verdict'] == 'no-access' for n in gsnodes):
        rule = rep['rules'].get('GameSir', {})
        if not rule.get('installed'):
            rep['verdict'].append(
                'GameSir device found but NOT openable (permission denied), and '
                'the udev rule is NOT installed. Fix:\n'
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
        rep['verdict'].append(
            'The device node is openable, but the Python hidapi library cannot '
            'open it — your hidapi appears to be built with the libusb backend '
            f'({rep["hidapi_backend"]}). Reinstall it with the hidraw backend:\n'
            '    pip install --user --force-reinstall --no-binary :all: hidapi')
    elif any(n['verdict'] == 'ok' for n in gsnodes):
        rep['verdict'].append('GameSir device access: OK.')

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
    L.append(f'- OS: {rep["os"]}  (kernel {rep["kernel"]})')
    L.append(f'- Session: {rep["session"]} / {rep["desktop"]}')
    L.append(f'- Python {rep["python"]}, hidapi {rep.get("hidapi_version", "?")} '
             f'— backend: {rep["hidapi_backend"]}')
    for label, r in rep['rules'].items():
        L.append(f'- udev rule ({label}): '
                 + ('installed' if r['installed'] else 'NOT INSTALLED'))
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
