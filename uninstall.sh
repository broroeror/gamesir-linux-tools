#!/usr/bin/env bash
# Remove the user-local Deadband install (leaves the repo + udev rule).
set -euo pipefail
APP_ID="deadband"
OLD_APP_ID="gamesir-cyclone2"   # pre-rename install, if one is still around
rm -f "$HOME/.local/bin/$APP_ID" "$HOME/.local/bin/$OLD_APP_ID"
rm -f "$HOME/.local/share/applications/$APP_ID.desktop" \
      "$HOME/.local/share/applications/$OLD_APP_ID.desktop"
for sz in 256x256 128x128 64x64 48x48; do
  rm -f "$HOME/.local/share/icons/hicolor/$sz/apps/$APP_ID.png" \
        "$HOME/.local/share/icons/hicolor/$sz/apps/$OLD_APP_ID.png"
done
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Removed launcher, desktop entry and icons."
echo "The udev rule (/etc/udev/rules.d/70-gamesir.rules) was left in place; remove with:"
echo "  sudo rm /etc/udev/rules.d/70-gamesir.rules && sudo udevadm control --reload-rules"
