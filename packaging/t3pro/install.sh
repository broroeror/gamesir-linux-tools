#!/usr/bin/env bash
# Install the optional Tarantula Pro bridge: per-user service + udev rule that
# starts it when the dongle (3537:103e) appears. The service runs from this
# checkout, like the app itself. Only the udev rule needs sudo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$UNIT_DIR"
sed "s#@REPO@#$REPO#" "$HERE/t3pro-bridge.service" > "$UNIT_DIR/t3pro-bridge.service"
systemctl --user daemon-reload
echo "==> installed $UNIT_DIR/t3pro-bridge.service"

echo "==> installing the udev rule (needs sudo)"
sudo cp "$HERE/72-t3pro-bridge.rules" /etc/udev/rules.d/
sudo udevadm control --reload
echo "==> done. Replug the dongle (XInput mode) to start the bridge."
