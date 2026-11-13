#!/usr/bin/env bash
# Build a self-contained AppImage for Deadband.
#
#   ./packaging/appimage/build-appimage.sh
#   OUT_DIR=~/Downloads ./packaging/appimage/build-appimage.sh
#
# The result is dist/Deadband-<version>-<arch>.AppImage. It bundles its own
# CPython, PySide6, hidapi and libusb, so the target machine does not need
# Python or Qt installed. It still uses the host's graphics stack (X11/Wayland,
# OpenGL) and the kernel's hidraw interface.
#
# Build prerequisites: curl, tar, zstd, git, and a network connection. We pin
# the Python/PySide6/hidapi versions below; override them with the matching
# environment variables when updating the bundle. Downloads are verified
# against pinned SHA-256 checksums (or the Anaconda API for conda-forge).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_NAME="Deadband"
APP_ID="deadband"

# Pinned inputs. On x86_64, PySide6 6.9 is the newest line with
# manylinux_2_28 wheels (Qt 6.10+ requires glibc 2.34). The arm64 wheel needs
# glibc 2.39 regardless of the Qt line.
PYTHON_VERSION="${PYTHON_VERSION:-3.12.16}"
PBS_RELEASE="${PBS_RELEASE:-20261026}"          # python-build-standalone release
PYSIDE_VERSION="${PYSIDE_VERSION:-6.9.3}"
HIDAPI_VERSION="${HIDAPI_VERSION:-0.15.0}"
APPIMAGETOOL_VERSION="${APPIMAGETOOL_VERSION:-1.9.1}"

# Runtime helper libraries. Qt's own QtNetwork links libgssapi, and our
# libkrb5 needs keyutils + OpenSSL 3. Conda-forge builds these against a very
# old glibc, so bundling them does not raise the AppImage's floor.
KRB5_VERSION="${KRB5_VERSION:-1.21.3}"
KEYUTILS_VERSION="${KEYUTILS_VERSION:-1.6.3}"
OPENSSL_VERSION="${OPENSSL_VERSION:-3.4.8}"

ARCH="${ARCH:-$(uname -m)}"
case "$ARCH" in
  x86_64)
    PBS_ARCH="x86_64"
    CONDA_SUBDIR="linux-64"
    APPIMAGE_ARCH="x86_64"
    # Checksums for the pinned x86_64 inputs.
    PYTHON_SHA256="${PYTHON_SHA256:-ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20}"
    APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0}"
    ;;
  aarch64|arm64)
    ARCH="aarch64"
    PBS_ARCH="aarch64"
    CONDA_SUBDIR="linux-aarch64"
    APPIMAGE_ARCH="aarch64"
    # Checksums for the pinned arm64 inputs.
    PYTHON_SHA256="${PYTHON_SHA256:-bb4b6392670c5d3f93876996fcaa19858a4a413a0c7720144c18b0d6f1f0db2d}"
    APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158}"
    ;;
  *)
    echo "Unsupported architecture: $ARCH (AppImage builds are x86_64 or aarch64)" >&2
    exit 1
    ;;
esac

BUILD_DIR="${BUILD_DIR:-$HERE/build/appimage}"
OUT_DIR="${OUT_DIR:-$HERE/dist}"
CACHE_DIR="${CACHE_DIR:-$BUILD_DIR/cache}"
APPDIR="$BUILD_DIR/$APP_NAME.AppDir"
TOOLS_DIR="$BUILD_DIR/tools"
LIB="$APPDIR/usr/lib"
SITE="$APPDIR/usr/lib/python3.12/site-packages"

VERSION="$(sed -n "s/^__version__ = '\(.*\)'/\1/p" "$HERE/version.py")"
[ -n "$VERSION" ] || { echo "Could not read the version from version.py" >&2; exit 1; }

mkdir -p "$BUILD_DIR" "$CACHE_DIR" "$TOOLS_DIR" "$OUT_DIR"
command -v git >/dev/null || {
  echo "git is required to list the tracked application files" >&2
  exit 1
}

download() {
  local url="$1" out="$2" sha="${3:-}"
  if [ ! -s "$out" ]; then
    echo "  downloading $(basename "$out")"
    curl -fL --retry 3 --connect-timeout 20 -o "$out.part" "$url"
    mv "$out.part" "$out"
  fi
  if [ -n "$sha" ]; then
    echo "$sha  $out" | sha256sum -c - >/dev/null \
      || { echo "Checksum mismatch for $out" >&2; exit 1; }
  fi
}

# Resolve a pinned conda-forge package for the target architecture and unpack
# it into $BUILD_DIR/conda/<name>.
fetch_conda() {
  local name="$1" version="$2"
  local info url sha file dest="$BUILD_DIR/conda/$name"
  info="$(curl -fsSL "https://api.anaconda.org/package/conda-forge/$name" \
    | "$PY" -c '
import json, sys
version, subdir = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin)
files = [f for f in d.get("files", [])
         if f.get("version") == version
         and (f.get("attrs") or {}).get("subdir") == subdir]
if not files:
    sys.exit(f"conda-forge has no {version} build for {subdir}")
files.sort(key=lambda f: f.get("upload_time") or "")
# "basename" is the path within the channel (e.g. linux-64/foo.conda).
f = files[-1]
print("https://conda.anaconda.org/conda-forge/%s" % f["basename"])
print(f.get("sha256") or "")
' "$version" "$CONDA_SUBDIR")"
  { read -r url; read -r sha; } <<< "$info"
  [ -n "$sha" ] || {
    echo "The Anaconda API did not report a SHA-256 for conda-forge/$name $version ($CONDA_SUBDIR)" >&2
    exit 1
  }
  file="$CACHE_DIR/$(basename "$url")"
  download "$url" "$file" "$sha"

  rm -rf "$dest"
  mkdir -p "$dest"
  case "$file" in
    *.tar.bz2)
      tar -xjf "$file" -C "$dest"
      ;;
    *.conda)
      command -v zstd >/dev/null || {
        echo "zstd is required to unpack $(basename "$file")" >&2
        exit 1
      }
      local tmp="$dest/.conda"
      mkdir -p "$tmp"
      "$PY" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
        "$file" "$tmp"
      zstd -dc "$tmp"/pkg-*.tar.zst | tar -xf - -C "$dest"
      rm -rf "$tmp"
      ;;
    *)
      echo "Unknown conda package format: $file" >&2
      exit 1
      ;;
  esac
}

echo "==> Building Deadband $VERSION AppImage ($ARCH)"

# 1. Portable CPython --------------------------------------------------------
# install_only means no compiler is needed here; pip installs wheels only.
PBS_ASSET="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${PBS_ARCH}-unknown-linux-gnu-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_ASSET//+/%2B}"
PBS_TAR="$CACHE_DIR/$PBS_ASSET"
download "$PBS_URL" "$PBS_TAR" "$PYTHON_SHA256"

echo "==> Unpacking CPython $PYTHON_VERSION"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr"
tar -xzf "$PBS_TAR" -C "$APPDIR/usr" --strip-components=1
PY="$APPDIR/usr/bin/python3"

# 2. Python dependencies -----------------------------------------------------
echo "==> Installing PySide6 $PYSIDE_VERSION and hidapi $HIDAPI_VERSION"
PIP_CACHE="$CACHE_DIR/pip"
mkdir -p "$PIP_CACHE"
"$PY" -m pip install --disable-pip-version-check --no-warn-script-location \
  --cache-dir "$PIP_CACHE" \
  "PySide6==$PYSIDE_VERSION" "hidapi==$HIDAPI_VERSION"

# 3. The application ---------------------------------------------------------
echo "==> Installing the application"
SHARE="$APPDIR/usr/share/$APP_ID"
mkdir -p "$SHARE"
# Copy the tracked top-level modules only, so untracked local scripts do not
# end up in the AppImage. The four dev-only test scripts are the same set the
# PKGBUILD drops.
APP_PY_LIST="$BUILD_DIR/app-py.list"
git -C "$HERE" ls-files -z -- ':(glob)*.py' \
  ':(exclude,glob)smoke_test.py' \
  ':(exclude,glob)continuous_trigger_tests.py' \
  ':(exclude,glob)continuous_trigger_ui_test.py' \
  ':(exclude,glob)macro_page_ui_test.py' > "$APP_PY_LIST"
[ -s "$APP_PY_LIST" ] || {
  echo "No tracked Python modules found; is $HERE a git checkout?" >&2
  exit 1
}
while IFS= read -r -d '' py; do
  cp "$HERE/$py" "$SHARE/"
done < "$APP_PY_LIST"
cp -r "$HERE/vendors" "$HERE/qml" "$HERE/assets" "$HERE/completions" "$SHARE"/
cp -r "$HERE/translations" "$SHARE"/
cp "$HERE/70-gamesir.rules" "$SHARE"/
mkdir -p "$SHARE/packaging/udev"
cp "$HERE/packaging/udev/70-deadband-g502x.rules" "$SHARE/packaging/udev/"
cp "$HERE/LICENSE" "$HERE/MANUAL.md" "$SHARE"/
find "$SHARE" -name '__pycache__' -type d -prune -exec rm -rf {} +

# 4. Runtime libraries Qt expects from the system ----------------------------
# QtNetwork links libgssapi; libkrb5 links libkeyutils and OpenSSL 3. We bundle
# them instead of assuming a desktop has the Kerberos stack installed.
echo "==> Bundling Kerberos/OpenSSL libraries"
fetch_conda krb5 "$KRB5_VERSION"
fetch_conda keyutils "$KEYUTILS_VERSION"
fetch_conda openssl "$OPENSSL_VERSION"

for lib in libgssapi_krb5.so.2.2 libkrb5.so.3.3 libk5crypto.so.3.1 \
           libkrb5support.so.0.1 libcom_err.so.3.0 libverto.so.0.0; do
  cp -L "$BUILD_DIR/conda/krb5/lib/$lib" "$LIB/"
done
ln -sf libgssapi_krb5.so.2.2 "$LIB/libgssapi_krb5.so.2"
ln -sf libkrb5.so.3.3       "$LIB/libkrb5.so.3"
ln -sf libk5crypto.so.3.1   "$LIB/libk5crypto.so.3"
ln -sf libkrb5support.so.0.1 "$LIB/libkrb5support.so.0"
ln -sf libcom_err.so.3.0    "$LIB/libcom_err.so.3"
ln -sf libverto.so.0.0      "$LIB/libverto.so.0"

cp -L "$BUILD_DIR/conda/keyutils/lib/libkeyutils.so.1.10" "$LIB/"
ln -sf libkeyutils.so.1.10 "$LIB/libkeyutils.so.1"
cp -L "$BUILD_DIR/conda/openssl/lib/libssl.so.3" "$LIB/"
cp -L "$BUILD_DIR/conda/openssl/lib/libcrypto.so.3" "$LIB/"

# libusb is loaded by ctypes.util.find_library('usb-1.0') for the G7 Pro
# transport. The hidapi wheel already ships a copy; put it where sitecustomize
# below can find it, without depending on the host having libusb installed.
LIBUSB="$(find "$SITE/hidapi.libs" -maxdepth 1 -name 'libusb-*.so.*' -print -quit)"
if [ -n "$LIBUSB" ]; then
  cp -L "$LIBUSB" "$LIB/libusb-1.0.so.0"
fi

# 5. Start-up glue -----------------------------------------------------------
echo "==> Writing AppRun"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
# Deadband AppImage launcher. The AppImage runtime exports APPDIR; keep the
# fallback so this also works when run directly from an extracted AppDir.
SELF="$(readlink -f "$0")"
APPDIR="${APPDIR:-$(dirname "$SELF")}"
export APPDIR

PY="$APPDIR/usr/bin/python3"
APP="$APPDIR/usr/share/deadband/deadband.py"
SITE="$APPDIR/usr/lib/python3.12/site-packages"
QT="$SITE/PySide6/Qt"

export PYTHONHOME="$APPDIR/usr"
export PYTHONPATH="$APPDIR/usr/share/deadband:$SITE${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$APPDIR/usr/lib:$QT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="$QT/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
export QML2_IMPORT_PATH="$QT/qml${QML2_IMPORT_PATH:+:$QML2_IMPORT_PATH}"
export QML_IMPORT_PATH="$QT/qml${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}"

exec "$PY" "$APP" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# ctypes.util.find_library() consults ldconfig, which cannot see an AppImage's
# bundled libs. Point it at the libusb we ship; --doctor reports the version
# through this path too. This file is inside the AppImage only.
cat > "$SITE/sitecustomize.py" <<'EOF'
"""AppImage helper: expose the bundled libusb-1.0 to ctypes.util.find_library."""
import ctypes.util
import os

_bundled = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "libusb-1.0.so.0"))
if os.path.exists(_bundled):
    _find_library = ctypes.util.find_library

    def _find_library_with_bundle(name):
        if name == "usb-1.0":
            return _bundled
        return _find_library(name)

    ctypes.util.find_library = _find_library_with_bundle
EOF

# 6. Desktop integration -----------------------------------------------------
cp "$HERE/packaging/deadband.desktop" "$APPDIR/$APP_ID.desktop"
cp "$HERE/assets/icon.png" "$APPDIR/$APP_ID.png"
ln -sf "$APP_ID.png" "$APPDIR/.DirIcon"

# 7. Trim build-only and unused runtime weight ------------------------------
echo "==> Trimming the bundle"
rm -rf "$APPDIR/usr/include" "$APPDIR/usr/share/man" \
       "$APPDIR/usr/lib/pkgconfig" \
       "$APPDIR/usr/lib/tcl9" "$APPDIR/usr/lib/tcl9.0" \
       "$APPDIR/usr/lib/tk9.0" "$APPDIR/usr/lib/itcl4.3.8" \
       "$APPDIR/usr/lib/thread3.0.6" \
       "$APPDIR/usr/lib/python3.12/idlelib" \
       "$APPDIR/usr/lib/python3.12/ensurepip" \
       "$APPDIR/usr/lib/python3.12/tkinter" \
       "$APPDIR/usr/lib/python3.12/turtledemo" \
       "$APPDIR/usr/lib/python3.12/lib2to3" \
       "$APPDIR/usr/lib/python3.12/pydoc_data" \
       "$APPDIR"/usr/lib/python3.12/config-* \
       "$SITE/pip" "$SITE"/pip-*.dist-info "$SITE/README.txt" \
       "$SITE/PySide6/include" "$SITE/PySide6/Qt/metatypes" \
       "$SITE/PySide6/Qt/libexec" "$SITE/PySide6/Qt/translations" \
       "$SITE/PySide6/doc" "$SITE/PySide6/glue" \
       "$SITE/PySide6/scripts" "$SITE/PySide6/support" \
       "$SITE/PySide6/typesystems" \
       "$SITE/PySide6/assistant" "$SITE/PySide6/designer" \
       "$SITE/PySide6/linguist" "$SITE/PySide6/lupdate" \
       "$SITE/PySide6/qmlformat" "$SITE/PySide6/qmlls" \
       "$SITE"/PySide6/Qt/resources/qtwebengine_* \
       "$SITE"/PySide6/Qt/resources/icudtl.dat \
       "$SITE"/PySide6/Qt/resources/v8_context_snapshot.bin \
       "$SITE"/PySide6/*.pyi \
       "$SITE"/PySide6/Qt/lib/libQt6WebEngine* \
       "$SITE"/PySide6/Qt/lib/libQt6WebChannel* \
       "$SITE"/PySide6/Qt/lib/libQt6WebView* \
       "$SITE"/PySide6/Qt/qml/QtWebEngine \
       "$SITE"/PySide6/Qt/qml/QtWebChannel \
       "$SITE"/PySide6/Qt/qml/QtWebView \
       "$SITE"/PySide6/Qt/plugins/designer \
       "$SITE"/PySide6/Qt/plugins/webview \
       "$SITE"/PySide6/Qt/plugins/virtualkeyboard \
       "$SITE"/PySide6/Qt/plugins/sqldrivers \
       "$SITE"/PySide6/Qt/plugins/qmltooling \
       "$SITE"/PySide6/QtWebEngine*.abi3.so \
       "$SITE"/PySide6/QtWebChannel*.abi3.so \
       "$SITE"/PySide6/QtWebView*.abi3.so
# Keep the shipped .pyc caches: the AppImage is read-only, so without them
# CPython would recompile the whole stdlib on every start.

# 8. Package -----------------------------------------------------------------
echo "==> Building the AppImage"
TOOL="$TOOLS_DIR/appimagetool-$APPIMAGE_ARCH.AppImage"
download "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-${APPIMAGE_ARCH}.AppImage" \
  "$TOOL" "$APPIMAGETOOL_SHA256"
chmod +x "$TOOL"
# appimagetool is itself an AppImage. Use its extracted mode when FUSE is not
# available (containers, some minimal systems).
if [ ! -e /dev/fuse ]; then
  export APPIMAGE_EXTRACT_AND_RUN=1
fi

OUT="$OUT_DIR/$APP_NAME-$VERSION-$APPIMAGE_ARCH.AppImage"
rm -f "$OUT"
ARCH="$APPIMAGE_ARCH" VERSION="$VERSION" \
  "$TOOL" --no-appstream "$APPDIR" "$OUT"

echo
echo "Built $OUT"
echo "Run it with: $OUT"
echo "Controller access still needs the udev rule:"
echo "    sudo cp \"$HERE/70-gamesir.rules\" /etc/udev/rules.d/"
echo "    sudo udevadm control --reload-rules && sudo udevadm trigger"
