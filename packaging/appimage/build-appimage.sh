#!/usr/bin/env bash
# Build Deadband-x86_64.AppImage: one file that runs on most x86_64 Linux
# desktops (glibc 2.34 or newer -- PySide6 6.11's own floor: Ubuntu 22.04+,
# Debian 12+, RHEL 9+) with nothing installed.
#
#     packaging/appimage/build-appimage.sh            # output: build/appimage/
#
# The build runs inside the manylinux_2_34 container (AlmaLinux 9, glibc 2.34),
# which the script starts itself with podman (or docker, CONTAINER_ENGINE=docker).
# 2.34 is PySide6's floor anyway, so building there costs nothing; an older image
# can't be used, because pip there refuses PySide6 6.11's manylinux_2_34 wheels.
# Every native file that isn't a downloaded wheel -- the hidapi it compiles, the
# libusb and libxcb-cursor it copies -- links against whatever glibc and
# toolchain it was built with. Built on the host, they inherit the host's: a
# Fedora 44 build needed glibc 2.38 for hidapi and libxcb-cursor and a newer
# TLS ABI (GLIBC_ABI_GNU2_TLS) for libusb, so the AppImage ran only on distros
# as new as the build machine. Step 6 fails the build if anything bundled needs
# more than GLIBC_MAX. NO_CONTAINER=1 builds on the host anyway (that host only).
#
# What goes in:
#   * a relocatable CPython (python-appimage's manylinux build, downloaded),
#   * PySide6 (pinned below to the version the app is tested with),
#   * cython-hidapi built from source WITH THE HIDRAW BACKEND -- pip's source
#     build defaults to libusb, which cannot open the controllers (see
#     install.sh); a libusb build would launch fine and then fail every open,
#   * libusb-1.0 from the build container (the G7 Pro / Kaleid raw-USB path),
#     handed to the app through DEADBAND_LIBUSB because ctypes.util.find_library
#     only searches the system linker cache, never the bundle,
#   * libxcb-cursor from the build container: Qt 6.5+ needs it for X11
#     and many distros don't install it by default,
#   * the app itself, selected exactly as packaging/PKGBUILD selects it.
#
# What can't go in: the udev rule. Granting device access needs root on the
# host, so AppImage users still install 70-gamesir.rules once; the README
# shows how to extract it from the AppImage (--appimage-extract <path>).
#
# Build prerequisites (this machine only, not users'): podman or docker.
# Inside the container the script installs systemd-devel (libudev headers),
# libusbx (libusb-1.0) and xcb-util-cursor; gcc, curl, file and Python 3.12 come
# with the image.
# Downloads: the container image from quay.io; python-appimage from PyPI and its
# Python build from its GitHub releases; appimagetool from
# github.com/AppImage/appimagetool.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY_VERSION="${PY_VERSION:-3.12}"
PYSIDE6_VERSION="${PYSIDE6_VERSION:-6.11.2}"   # what the Linux checks ran on
LINUX_TAG="manylinux_2_28_x86_64"              # the relocatable Python's floor
GLIBC_MAX="${GLIBC_MAX:-2.34}"                 # PySide6 6.11's; nothing may need more
BUILD_IMAGE="${BUILD_IMAGE:-quay.io/pypa/manylinux_2_34_x86_64}"
OUT="${OUT:-$REPO/build/appimage}"
WORK="$OUT/work"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

# appimagetool and the python-appimage base are AppImages themselves; extract-
# and-run means FUSE isn't needed on the build machine.
export APPIMAGE_EXTRACT_AND_RUN=1

say() { printf '==> %s\n' "$*"; }
die() { printf '!! %s\n' "$*" >&2; exit 1; }

[ "$(uname -m)" = x86_64 ] || die "builds x86_64 only (this is $(uname -m))"

# 0. Re-run inside the build container ----------------------------------------------
if [ -z "${DEADBAND_IN_CONTAINER:-}" ] && [ -z "${NO_CONTAINER:-}" ]; then
  engine="${CONTAINER_ENGINE:-$(command -v podman || command -v docker || true)}"
  [ -n "$engine" ] || die "podman or docker is needed (or NO_CONTAINER=1 for a host-only build)"
  mkdir -p "$OUT"
  owner=()
  # Rootful docker writes root-owned files; hand them back at the end. Rootless
  # podman maps container root to this user already, so it must not chown.
  case "$(basename "$engine")" in docker*) owner=(-e "HOST_OWNER=$(id -u):$(id -g)") ;; esac
  say "Building inside $BUILD_IMAGE (via $(basename "$engine"))"
  # label=disable: read the repo without relabelling it for SELinux (no :z).
  exec "$engine" run --rm --security-opt label=disable \
    -v "$REPO:$REPO" -v "$OUT:$OUT" -w "$REPO" \
    -e DEADBAND_IN_CONTAINER=1 -e OUT="$OUT" -e PY_VERSION="$PY_VERSION" \
    -e PYSIDE6_VERSION="$PYSIDE6_VERSION" -e GLIBC_MAX="$GLIBC_MAX" "${owner[@]}" \
    "$BUILD_IMAGE" bash "$REPO/packaging/appimage/build-appimage.sh"
fi
if [ -n "${DEADBAND_IN_CONTAINER:-}" ]; then
  say "Build container: $(. /etc/os-release; echo "$PRETTY_NAME"), $(ldd --version | head -n1)"
  dnf install -y -q systemd-devel libusbx xcb-util-cursor >/dev/null \
    || die "could not install systemd-devel / libusbx / xcb-util-cursor in the container"
fi
command -v gcc >/dev/null || die "gcc is needed to build hidapi"
command -v curl >/dev/null || die "curl is needed for downloads"

rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

# 1. Base AppDir: a relocatable Python -------------------------------------------
say "Fetching python-appimage (Python $PY_VERSION, $LINUX_TAG)"
"$(command -v python3.12 || command -v python3)" -m venv "$WORK/tools"   # the image's python3 is 3.9
"$WORK/tools/bin/pip" install --quiet --upgrade pip python-appimage

recipe="$WORK/recipe"
mkdir -p "$recipe"
cp "$REPO/packaging/deadband.desktop" "$recipe/deadband.desktop"
cp "$REPO/assets/icon.png" "$recipe/deadband.png"
: > "$recipe/requirements.txt"          # everything is installed after extraction
cat > "$recipe/entrypoint.sh" <<'EOF'
{{ python-executable }} "$@"
EOF
"$WORK/tools/bin/python-appimage" build app -l "$LINUX_TAG" -p "$PY_VERSION" "$recipe"
base="$(ls "$WORK"/*.AppImage 2>/dev/null | head -n1)"
[ -n "$base" ] || die "python-appimage produced no AppImage"

say "Extracting the base AppDir"
"$base" --appimage-extract >/dev/null
APPDIR="$WORK/squashfs-root"
PYBIN="$(ls -d "$APPDIR"/opt/python"$PY_VERSION"/bin/python"$PY_VERSION" 2>/dev/null | head -n1)"
[ -x "$PYBIN" ] || die "no python$PY_VERSION inside the base AppDir"
PYREL="${PYBIN#"$APPDIR"/}"

# 2. Python dependencies ----------------------------------------------------------
say "Installing PySide6 $PYSIDE6_VERSION"
"$PYBIN" -m pip install --quiet --no-cache-dir "PySide6==$PYSIDE6_VERSION"

say "Building hidapi with the hidraw backend"
HIDAPI_WITH_HIDRAW=1 "$PYBIN" -m pip install --quiet --no-cache-dir \
    --no-binary hidapi hidapi
backend="$("$PYBIN" -c "import sys; sys.path.insert(0, '$REPO')
from doctor import _hidapi_backend; print(_hidapi_backend())")"
case "$backend" in
  hidraw*) say "hidapi backend: $backend" ;;
  *) die "hidapi built with '$backend', not hidraw; the app could not open controllers" ;;
esac

# 3. Native libraries ---------------------------------------------------------------
mkdir -p "$APPDIR/usr/lib"
bundle_lib() {   # bundle_lib <soname> <required: 1|0>
  local path
  # awk reads to the end (no early exit): stopping early SIGPIPEs ldconfig,
  # which pipefail + set -e turn into a silent abort (exit 141).
  path="$(ldconfig -p 2>/dev/null | awk -v n="$1" '$1 == n && /x86-64/ && !p { p = $NF } END { if (p) print p }')"
  if [ -n "$path" ]; then
    cp -L "$path" "$APPDIR/usr/lib/$1"
    say "bundled $1 (from $path)"
  elif [ "$2" = 1 ]; then
    die "$1 not found on this machine; install it to bundle it"
  else
    say "not bundling $1 (not installed here; users without it on X11 need it)"
  fi
}
bundle_lib libusb-1.0.so.0 1
bundle_lib libxcb-cursor.so.0 0

# 4. The app (same selection as packaging/PKGBUILD) -------------------------------
say "Copying the app"
share="$APPDIR/usr/share/deadband"
mkdir -p "$share/assets" "$share/packaging/udev"
cp "$REPO"/*.py "$share"/
rm -f "$share/smoke_test.py"
cp -r "$REPO/vendors" "$REPO/qml" "$share"/
find "$share" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$REPO"/assets/icon.png "$REPO"/assets/icon-64.png "$REPO"/assets/icon-48.png \
   "$REPO"/assets/glyph-pad.png "$REPO"/assets/glyph-pad-dark.png "$share/assets"/
cp "$REPO/70-gamesir.rules" "$share"/
cp "$REPO/packaging/udev/70-deadband-g502x.rules" "$share/packaging/udev"/
cp "$REPO/LICENSE" "$share"/

# 5. Entry point --------------------------------------------------------------------
# Replaces python-appimage's generic AppRun: explicit about every variable.
cat > "$APPDIR/AppRun" <<EOF
#!/bin/bash
# Deadband AppImage entry point (generated by packaging/appimage/build-appimage.sh)
HERE="\$(dirname "\$(readlink -f "\$0")")"
export APPDIR="\${APPDIR:-\$HERE}"
export LD_LIBRARY_PATH="\$APPDIR/usr/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export DEADBAND_LIBUSB="\$APPDIR/usr/lib/libusb-1.0.so.0"
export DEADBAND_APPIMAGE=1
# -s: ignore ~/.local site-packages, so a user's own PySide6/hidapi can't shadow
# the bundled ones (a libusb-backend hidapi there would break every open).
exec "\$APPDIR/$PYREL" -s "\$APPDIR/usr/share/deadband/deadband.py" "\$@"
EOF
chmod 755 "$APPDIR/AppRun"
rm -f "$APPDIR"/*.desktop "$APPDIR"/*.png "$APPDIR/.DirIcon"
cp "$REPO/packaging/deadband.desktop" "$APPDIR/deadband.desktop"
cp "$REPO/assets/icon.png" "$APPDIR/deadband.png"
ln -sf deadband.png "$APPDIR/.DirIcon"

# 6. Smoke test inside the AppDir before packing ---------------------------------
say "Checking the bundle imports"
APPDIR="$APPDIR" LD_LIBRARY_PATH="$APPDIR/usr/lib" \
DEADBAND_LIBUSB="$APPDIR/usr/lib/libusb-1.0.so.0" \
  "$PYBIN" -s -c "
import sys; sys.path.insert(0, '$share')
import PySide6, hidcompat, controller_profile, bridge
from vendors.gamesir import usb_transport
libusb = usb_transport.library_version()
print('PySide6', PySide6.__version__, '| hid', hidcompat.IMPL, '| libusb', libusb)
# DEADBAND_LIBUSB points at the bundled copy only, so None means IT is broken.
sys.exit(0 if libusb else 'the bundled libusb-1.0 does not load')"

# The glibc floor: the newest GLIBC_x.y any bundled ELF file asks for. PySide6's
# wheels set it (2.34); anything above means a host-built file slipped in.
say "Checking the glibc floor (must be <= $GLIBC_MAX)"
command -v objdump >/dev/null || die "objdump is needed for the glibc check"
floor=0 worst="" over=()
# One objdump per file into a variable, no early-exiting readers in a pipe: with
# pipefail, a grep that matches nothing (or a grep -q that stops early) would
# abort the build or miss a match.
while IFS= read -r -d '' f; do
  case "$(file -b "$f")" in ELF*) ;; *) continue ;; esac
  syms="$(objdump -p -T "$f" 2>/dev/null || true)"   # -p: version needs (GNU2_TLS)
  case "$syms" in *GLIBC_ABI_GNU2_TLS*) over+=("GNU2_TLS  ${f#"$APPDIR"/}") ;; esac
  v="$(printf '%s\n' "$syms" | sed -nE 's/.*GLIBC_([0-9]+\.[0-9]+(\.[0-9]+)?).*/\1/p' | sort -V | tail -n1)"
  [ -n "$v" ] || continue
  if [ "$(printf '%s\n%s\n' "$v" "$floor" | sort -V | tail -n1)" = "$v" ] && [ "$v" != "$floor" ]; then
    floor="$v" worst="${f#"$APPDIR"/}"
  fi
  if [ "$(printf '%s\n%s\n' "$v" "$GLIBC_MAX" | sort -V | tail -n1)" != "$GLIBC_MAX" ]; then
    over+=("$v  ${f#"$APPDIR"/}")
  fi
done < <(find "$APPDIR" -type f \( -name '*.so*' -o -perm -u+x \) -print0)
[ ${#over[@]} -eq 0 ] || { printf '   %s\n' "${over[@]}" >&2; die "bundled files need a glibc newer than $GLIBC_MAX"; }
say "glibc floor: $floor (from $worst)"

# 7. Pack ----------------------------------------------------------------------------
say "Packing"
curl -fsSL -o "$WORK/appimagetool" "$APPIMAGETOOL_URL"
chmod +x "$WORK/appimagetool"
mkdir -p "$OUT"
ARCH=x86_64 "$WORK/appimagetool" --no-appstream "$APPDIR" "$OUT/Deadband-x86_64.AppImage"
[ -z "${HOST_OWNER:-}" ] || chown -R "$HOST_OWNER" "$OUT"
say "Done: $OUT/Deadband-x86_64.AppImage"
echo "    Users still need the udev rule once (README: 'Any distro (AppImage)')."
