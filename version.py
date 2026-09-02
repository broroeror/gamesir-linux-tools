"""The app version, in its own module so `doctor.py` can report it.

`deadband --doctor` runs before Qt is imported (so it works over SSH and in a
broken graphical session), which means the diagnostics can't import deadband.py
to find the version -- that would drag Qt in. Both import this instead.
"""

__version__ = '0.3.0-dev'


def build_id():
    """`version (commit)` when running from a git checkout, else just the version.

    The AUR package is a `-git` build tracking main, so the version string alone
    doesn't identify which code someone is running -- the commit does, and that's
    exactly what a bug report needs.
    """
    import os
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(os.path.join(here, '.git')):
        return __version__
    try:
        out = subprocess.run(['git', '-C', here, 'describe', '--always', '--dirty'],
                             capture_output=True, text=True, timeout=2)
        rev = out.stdout.strip()
        return f'{__version__} ({rev})' if out.returncode == 0 and rev else __version__
    except Exception:
        return __version__          # no git binary, not a checkout, whatever -- ignore
