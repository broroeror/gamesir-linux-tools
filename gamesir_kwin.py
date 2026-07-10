"""
KWin "Game Controller" plugin toggle (KDE Plasma 6.7+)
======================================================
"Mouse mode" - the sticks driving the desktop cursor after a dongle re-pair - is
KDE's KWin Game Controller plugin (maps sticks -> pointer, triggers -> clicks,
reading the joystick evdev node directly). This module reads/sets that plugin's
enabled flag in ~/.config/kwinrc, so the in-app toggle can turn it OFF (normal
gamepad) or ON (couch/bed cursor control) the clean, gaming-safe way - games read
evdev directly and are unaffected either way.

This is the same setting as System Settings -> Game Controller; it persists.
Falls back to nothing on non-KDE sessions (available() returns False), where the
app uses the EVIOCGRAB suppressor in gamesir_mousegrab.py instead.
"""

import os
import shutil
import subprocess

GROUP = 'Plugins'
KEY = 'gamecontrollerEnabled'
PLUGIN = 'gamecontroller'   # KWin's internal plugin id (org.kde.KWin.Plugins)
GAMECONTROLLER_SINCE = (6, 7)   # KWin/Plasma release that first shipped the plugin


def _qdbus():
    return shutil.which('qdbus6') or shutil.which('qdbus')


def _plugins(method, *args):
    """Call org.kde.KWin.Plugins.<method>. Returns the command's stdout (str)
    on success, or None if qdbus is missing / the call failed. This is the live
    load/unload mechanism — loading the plugin enables couch mode *immediately*,
    which a plain `reconfigure` did not do for enabling."""
    q = _qdbus()
    if not q:
        return None
    try:
        r = subprocess.run([q, 'org.kde.KWin', '/Plugins',
                            'org.kde.KWin.Plugins.' + method, *args],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _kwin_version():
    """(major, minor) of the *running* KWin, or None if undeterminable.

    Read from the already-running compositor via D-Bus (supportInformation
    carries a 'KWin version: X.Y.Z' line) — this queries the live instance and
    does NOT spawn a compositor the way `kwin_wayland --version` would."""
    q = _qdbus()
    if not q:
        return None
    try:
        out = subprocess.run([q, 'org.kde.KWin', '/KWin',
                              'org.kde.KWin.supportInformation'],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.lower().startswith('kwin version:'):
            parts = line.split(':', 1)[1].strip().split('.')
            try:
                return int(parts[0]), int(parts[1])
            except (IndexError, ValueError):
                return None
    return None


def plugin_present():
    """Whether KWin's gamecontroller plugin exists here: True / False / None.

    The Plugins D-Bus interface can only load/unload and list *loaded* plugins —
    there's no "available plugins" query — so presence is inferred two ways:
      * If it's already loaded, it's obviously present (ground truth, no side
        effects). Conclusive only for True; a disabled-but-present plugin is
        absent from this list, so a miss here is not a "no".
      * Otherwise fall back to the KWin version: the plugin is built into KWin
        from 6.7 on, so >= 6.7 => present, < 6.7 => absent.
    Returns None when neither the loaded list nor the version can be read, so the
    caller can stay lenient rather than hide a toggle that might actually work."""
    loaded = _plugins('LoadedPlugins')
    if loaded is not None and PLUGIN in loaded.split():
        return True
    ver = _kwin_version()
    if ver is None:
        return None
    return ver >= GAMECONTROLLER_SINCE


def available():
    """True if this is a KDE session that actually ships the gamecontroller
    plugin. Everything else — non-KDE desktops, and KDE too old for the plugin —
    falls back to the EVIOCGRAB grabber in gamesir_mousegrab.py.

    The plugin check only vetoes when we're *sure* it's missing (old KWin); an
    undeterminable version keeps the KWin path, so a working setup whose version
    probe fails is never regressed into the fallback."""
    if not (shutil.which('kwriteconfig6') and shutil.which('kreadconfig6')):
        return False
    desk = (os.environ.get('XDG_CURRENT_DESKTOP', '') + ':' +
            os.environ.get('XDG_SESSION_DESKTOP', '')).upper()
    if 'KDE' not in desk and 'PLASMA' not in desk:
        return False
    return plugin_present() is not False


def is_enabled():
    """Current plugin state. Prefer the live loaded-plugin list (ground truth);
    fall back to the kwinrc flag if D-Bus is unavailable. An unset kwinrc key
    means KWin's default, which is enabled. Returns None if nothing is readable."""
    loaded = _plugins('LoadedPlugins')
    if loaded is not None:
        return PLUGIN in loaded.split()
    try:
        out = subprocess.run(
            ['kreadconfig6', '--file', 'kwinrc', '--group', GROUP, '--key', KEY],
            capture_output=True, text=True, timeout=5).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return None
    if out in ('true', 'false'):
        return out == 'true'
    return True


def set_enabled(on):
    """Apply the mouse-mode (couch) setting both live and persistently.

    1. Write the kwinrc flag so the choice survives a relogin and matches what
       System Settings -> Game Controller shows.
    2. Load / unload the plugin over D-Bus so it takes effect *now*. Loading is
       what previously needed a logout; LoadPlugin makes enabling instant.

    Returns True if either the live apply or the persisted write succeeded."""
    val = 'true' if on else 'false'
    ok_cfg = True
    try:
        subprocess.run(['kwriteconfig6', '--file', 'kwinrc', '--group', GROUP,
                        '--key', KEY, val], check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        ok_cfg = False

    live = _plugins('LoadPlugin' if on else 'UnloadPlugin', PLUGIN)
    if live is None:
        # No plugin D-Bus call possible — fall back to asking KWin to reread
        # config (works reliably for disabling, less so for enabling).
        q = _qdbus()
        if q:
            try:
                subprocess.run([q, 'org.kde.KWin', '/KWin', 'reconfigure'],
                               timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        return ok_cfg

    return True
