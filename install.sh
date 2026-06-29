#!/usr/bin/env bash
# GameSir Cyclone 2 (Qt) — user-local installer for Arch/KDE and other Linux.
#
#   git clone <repo> && cd "GameSir Linux" && ./install.sh
#
# Installs into your home (~/.local), so the only step that needs sudo is the
# one-time udev rule that lets you open the controller without root. Re-runnable.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="gamesir-cyclone2"
BIN="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor"

echo "==> Installing GameSir Cyclone 2 from: $REPO"

# 1. dependencies -----------------------------------------------------------
missing=()
command -v python3 >/dev/null || missing+=("python")
python3 -c 'import PySide6' 2>/dev/null || missing+=("python-pyside6")
python3 -c 'import hid'     2>/dev/null || missing+=("python-hidapi")
if [ ${#missing[@]} -ne 0 ]; then
  echo "!! Missing dependencies: ${missing[*]}"
  if command -v pacman >/dev/null; then
    read -rp "   Install them now with pacman? [y/N] " a
    if [[ "${a,,}" == y* ]]; then
      sudo pacman -S --needed python python-pyside6 python-hidapi
    else
      echo "   Run: sudo pacman -S --needed ${missing[*]}"; exit 1
    fi
  else
    echo "   Install PySide6 and hidapi for Python 3 (e.g. pip install --user PySide6 hidapi),"
    echo "   then re-run this script."; exit 1
  fi
fi

# 2. udev rule (one-time sudo) ---------------------------------------------
if [ ! -f /etc/udev/rules.d/70-gamesir.rules ]; then
  echo "==> Installing udev rule (use the controller without sudo)"
  sudo cp "$REPO/70-gamesir.rules" /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
else
  echo "==> udev rule already installed"
fi

# 3. launcher ---------------------------------------------------------------
mkdir -p "$BIN"
cat > "$BIN/$APP_ID" <<EOF
#!/usr/bin/env bash
exec python3 "$REPO/gamesir_qt.py" "\$@"
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
Name=GameSir Cyclone 2
GenericName=Controller Configuration
Comment=Configure GameSir Cyclone 2 lighting, sticks, triggers and buttons
Exec=$BIN/$APP_ID
Icon=$APP_ID
Terminal=false
Categories=Settings;HardwareSettings;
Keywords=gamesir;controller;gamepad;rgb;
EOF

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
gtk-update-icon-cache -f "$ICON_DIR" 2>/dev/null || true

echo
echo "==> Done. Find 'GameSir Cyclone 2' in your app launcher, or run: $APP_ID"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "    (Note: add ~/.local/bin to your PATH to use the '$APP_ID' command.)" ;;
esac
echo "    Put the controller in Xbox mode first (hold the green button ~2s)."
