#!/usr/bin/env bash
# Deadband (Qt) — user-local installer for Arch/KDE and other Linux.
#
#   git clone <repo> && cd "GameSir Linux" && ./install.sh
#
# Installs into your home (~/.local), so the only step that needs sudo is the
# one-time udev rule that lets you open the controller without root. Re-runnable.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="deadband"
# Pre-rename install id. The app used to be "gamesir-cyclone2"; leaving that
# behind would give you a second launcher entry pointing at gamesir_qt.py,
# which no longer exists. Cleaned up below. (Settings are carried over
# separately, on first run — see _migrate_settings in deadband.py.)
OLD_APP_ID="gamesir-cyclone2"
BIN="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor"

echo "==> Installing Deadband from: $REPO"
echo "    This installs into your home (~/.local) and never needs root for the"
echo "    app itself. The only step that uses sudo is the optional udev rule,"
echo "    and it asks first."

# Ask a yes/no question. Defaults to "no" if there's no terminal (so the script
# never silently runs a privileged command in a non-interactive context).
confirm() {
  local ans
  if [ ! -t 0 ]; then
    echo "    (no terminal attached — assuming \"no\")"
    return 1
  fi
  read -rp "$1 [y/N] " ans || return 1
  [[ "${ans,,}" == y* ]]
}

# 1. dependencies -----------------------------------------------------------
missing=()
command -v python3 >/dev/null || missing+=("python")
python3 -c 'import PySide6' 2>/dev/null || missing+=("pyside6")
python3 -c 'import hid'     2>/dev/null || missing+=("python-hidapi")
python3 -c 'import ctypes.util; assert ctypes.util.find_library("usb-1.0")' \
  2>/dev/null || missing+=("libusb")
if [ ${#missing[@]} -ne 0 ]; then
  echo
  echo "==> Missing dependencies: ${missing[*]}"
  if command -v pacman >/dev/null; then
    echo "    These can be installed with (uses sudo):"
    echo "        sudo pacman -S --needed python pyside6 python-hidapi libusb"
    if confirm "    Run that now?"; then
      sudo pacman -S --needed python pyside6 python-hidapi libusb
    else
      echo "    Skipped. Install them yourself, then re-run this script."; exit 1
    fi
  else
    echo "   Install the system libusb-1.0 runtime plus PySide6 and hidapi for"
    echo "   Python 3, then re-run this script:"
    echo "       pip install --user PySide6"
    echo "       HIDAPI_WITH_HIDRAW=1 pip install --user --no-binary :all: hidapi"
    echo "   (The HIDAPI_WITH_HIDRAW=1 matters: pip's source build DEFAULTS to the"
    echo "    libusb backend, which cannot open the controller. Building needs gcc,"
    echo "    python3-devel and libudev headers — Fedora/Bazzite: systemd-devel.)"
    exit 1
  fi
fi

# 1b. hidapi backend check --------------------------------------------------
# `import hid` succeeding is not enough: a source-built pip hidapi DEFAULTS to
# the libusb backend, which cannot open /dev/hidraw — the app then finds the
# controller but every open fails. Catch that here, not at first run.
backend="$(python3 -c "import sys; sys.path.insert(0, '$REPO')
from doctor import _hidapi_backend; print(_hidapi_backend())" 2>/dev/null || echo unknown)"
case "$backend" in
  libusb*)
    echo
    echo "==> WARNING: your Python hidapi uses the libusb backend ($backend)."
    echo "    It cannot open hidraw devices, so Deadband will find your controller"
    echo "    but fail to talk to it. Rebuild hidapi with the hidraw backend:"
    echo "        HIDAPI_WITH_HIDRAW=1 pip install --user --force-reinstall \\"
    echo "            --no-cache-dir --no-binary :all: hidapi"
    echo "    (--no-cache-dir matters: pip otherwise reuses the old libusb build."
    echo "     Needs gcc, python3-devel, libudev headers — Fedora/Bazzite:"
    echo "     rpm-ostree install systemd-devel, then reboot.)"
    if confirm "    Try that rebuild now?"; then
      HIDAPI_WITH_HIDRAW=1 pip install --user --force-reinstall \
        --no-cache-dir --no-binary :all: hidapi
      backend="$(python3 -c "import sys; sys.path.insert(0, '$REPO')
from doctor import _hidapi_backend; print(_hidapi_backend())" 2>/dev/null || echo unknown)"
      case "$backend" in
        hidraw*) echo "    Rebuilt OK — hidraw backend active." ;;
        *) echo "    Still not hidraw ($backend) — run ./deadband --doctor after"
           echo "    installing the build prerequisites, and re-run this script." ;;
      esac
    else
      echo "    Continuing anyway — the app's Diagnostics window shows this too."
    fi
    ;;
esac

# 2. udev rule (one-time sudo, optional) -----------------------------------
RULE_OK=1
if [ ! -f /etc/udev/rules.d/70-gamesir.rules ] || \
   ! cmp -s "$REPO/70-gamesir.rules" /etc/udev/rules.d/70-gamesir.rules; then
  echo
  echo "==> Controller access (udev rule)"
  echo "    To open the controller without running the app as root, one file is"
  echo "    copied into /etc/udev/rules.d/ and the rules are reloaded. The exact"
  echo "    commands, which need sudo, are:"
  echo "        sudo cp \"$REPO/70-gamesir.rules\" /etc/udev/rules.d/"
  echo "        sudo udevadm control --reload-rules && sudo udevadm trigger"
  if confirm "    Run these now?"; then
    if sudo cp "$REPO/70-gamesir.rules" /etc/udev/rules.d/ \
       && sudo udevadm control --reload-rules && sudo udevadm trigger; then
      echo "    Installed. Unplug and replug the controller once before use."
    else
      RULE_OK=0
      echo "    !! udev step failed — continuing without it (see the note below)."
    fi
  else
    RULE_OK=0
    echo "    Skipped. The app still installs and launches from your menu, but it"
    echo "    can't reach the controller until the rule is in place. You can:"
    echo "      • re-run ./install.sh and accept this step,"
    echo "      • run the two commands above yourself later, or"
    echo "      • launch it with sudo (not recommended)."
  fi
else
  echo "==> current udev rule already installed"
fi

# 3. launcher ---------------------------------------------------------------
mkdir -p "$BIN"
cat > "$BIN/$APP_ID" <<EOF
#!/usr/bin/env bash
exec python3 "$REPO/deadband.py" "\$@"
EOF
chmod +x "$BIN/$APP_ID"

# 4. icons ------------------------------------------------------------------
install -Dm644 "$REPO/assets/icon.png"     "$ICON_DIR/256x256/apps/$APP_ID.png"
install -Dm644 "$REPO/assets/icon-128.png" "$ICON_DIR/128x128/apps/$APP_ID.png"
install -Dm644 "$REPO/assets/icon-64.png"  "$ICON_DIR/64x64/apps/$APP_ID.png"
install -Dm644 "$REPO/assets/icon-48.png"  "$ICON_DIR/48x48/apps/$APP_ID.png"

# 5. desktop entry ----------------------------------------------------------
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Deadband
GenericName=Controller Configuration
Comment=Configure game controller lighting, sticks, triggers and buttons
Exec=$BIN/$APP_ID
Icon=$APP_ID
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=controller;gamepad;joystick;rgb;deadzone;gamesir;
EOF

# 6. remove the pre-rename install ------------------------------------------
if [ "$OLD_APP_ID" != "$APP_ID" ]; then
  removed=0
  for f in "$BIN/$OLD_APP_ID" "$DESKTOP_DIR/$OLD_APP_ID.desktop"; do
    [ -e "$f" ] && { rm -f "$f"; removed=1; }
  done
  for sz in 256x256 128x128 64x64 48x48; do
    f="$ICON_DIR/$sz/apps/$OLD_APP_ID.png"
    [ -e "$f" ] && { rm -f "$f"; removed=1; }
  done
  [ "$removed" = 1 ] && echo "==> Removed the old '$OLD_APP_ID' install (renamed to $APP_ID)."
fi

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f "$ICON_DIR" 2>/dev/null || true

echo
echo "==> Done. Find 'Deadband' in your app launcher, or run: $APP_ID"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "    (Note: add ~/.local/bin to your PATH to use the '$APP_ID' command.)" ;;
esac
echo "    Put the controller in Xbox mode first (hold the green button ~2s)."
if [ "$RULE_OK" -ne 1 ]; then
  echo
  echo "    Reminder: the udev rule was not installed, so the app won't see the"
  echo "    controller yet. Re-run ./install.sh (accepting the udev step) to fix."
fi
