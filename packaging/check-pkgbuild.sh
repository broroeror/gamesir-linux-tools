#!/usr/bin/env bash
# Guard against the issue-#4 class of bug: a packaged app missing a module it
# imports at runtime. Compares the repo's top-level Python modules against what
# the PKGBUILD's package() would install. Run it after adding a new module.
#
#   ./packaging/check-pkgbuild.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

missing=0
# every tracked top-level module (excluding dev-only tools)
for f in $(git ls-files '*.py' | grep -v / | grep -v '^smoke_test\.py$'); do
  # does package() install it — - via the glob or by name?
  if ! grep -qE '(install -Dm644 \./\*\.py|[[:space:]]'"${f//./\\.}"')' packaging/PKGBUILD; then
    echo "MISSING from PKGBUILD: $f"
    missing=1
  fi
done

# every udev rule in the repo should ship too
for r in 70-gamesir.rules packaging/udev/70-deadband-g502x.rules; do
  [ -f "$r" ] || continue
  base="$(basename "$r")"
  if ! grep -q "$base" packaging/PKGBUILD; then
    echo "MISSING from PKGBUILD: $r"
    missing=1
  fi
done

if [ "$missing" -eq 0 ]; then
  echo "PKGBUILD covers every top-level module and udev rule."
else
  echo
  echo "Fix packaging/PKGBUILD before publishing — an AUR user would hit"
  echo "ModuleNotFoundError at launch (see issue #4)."
  exit 1
fi
