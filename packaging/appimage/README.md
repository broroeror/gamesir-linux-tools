# AppImage

Build a portable Linux bundle of Deadband with:

```sh
./packaging/appimage/build-appimage.sh
```

The result is `dist/Deadband-<version>-<arch>.AppImage`. It bundles CPython,
PySide6, hidapi (hidraw backend) and libusb, so the target machine needs neither
Python nor Qt installed. The host still supplies the graphics stack (X11 or
Wayland, OpenGL) and the kernel's hidraw interface.

The build is offline after the first run: downloads are cached in
`build/appimage/cache/`. Build prerequisites are `curl`, `tar`, `zstd` and a
network connection. The pinned Python, PySide6 and hidapi versions are at the
top of the script; override them with the matching environment variables when
updating the bundle.

Running the AppImage does not install the controller access rule. As with a
source install, do that once:

```sh
sudo cp 70-gamesir.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then unplug/replug the controller and run the AppImage. `--doctor` works from
the AppImage too:

```sh
./Deadband-*.AppImage --doctor
```

## Notes

- The AppImage is built for the host architecture by default; `ARCH=aarch64`
  selects the arm64 bundle.
- Qt is trimmed of WebEngine and translations, which Deadband doesn't use, to
  keep the download reasonable. Everything the QML UI imports (Quick, Controls,
  Layouts, Shapes, Dialogs, Multimedia) is kept.
- PySide6 6.9 is used deliberately on x86_64: it is the newest line with
  `manylinux_2_28` wheels, so the AppImage also runs on distros older than the
  Qt 6.10+ baseline. (The arm64 wheel requires glibc 2.39.)
