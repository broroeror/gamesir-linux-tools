# GameSir Cyclone 2 — Linux control app

A Linux GUI for the GameSir Cyclone 2 controller, driven over the controller's
vendor (hidraw) interface, reverse-engineered from scratch. It covers:

- **Live input view** — sticks, triggers, all buttons (incl. the L4/R4/M/Home/
  Share extras), D-pad, battery + charging, firmware version, and a mode warning.
- **Profiles** — read the active profile and switch (1–4); rumble test.
- **Lighting** — per-light RGB, captured effect presets, brightness/speed,
  audio-reactive / pick-up-to-wake / sleep timeout, and a **custom keyframe
  animation editor** (add/remove keyframes, randomize, play/pause).
- **Config editor** — deadzones, anti-deadzones, stick trajectory, sensitivity
  curves (presets **and** a draggable custom-curve editor), trigger tuning
  (hair-trigger + response curve), vibration, poll rate, and button remap.
- **Backup / Restore** — snapshot all 4 profiles + lighting to a JSON file and
  write it back later.
- **Mouse-mode toggle** — turn KDE/KWin's gamepad-drives-the-cursor behaviour
  off (normal gamepad) or on (sticks-as-cursor "couch mode") from the app, plus a
  non-KDE EVIOCGRAB fallback (Wayland; see Status).

![status: input, battery, profiles, RGB + keyframes, full config editor, remap, and JSON backup/restore working]

**Version:** `0.1.0-alpha.2` — the full Qt/QML app (lighting + keyframe editor,
config editor, button remap, backup/restore, one-command install). Known-good
snapshot (git tag `v0.1.0-alpha.2`).
**Going deeper?** The **[Manual](MANUAL.md)** is the user guide — how to use each
feature, troubleshooting & recovery, and an FAQ. **[RESEARCH.md](RESEARCH.md)** is the
developer side — protocol, architecture, the diagnostic tools, and per-controller
findings. See also **[CONTROLLER_MAP.md](CONTROLLER_MAP.md)** (what each control
reports to Linux) and **[TODO.md](TODO.md)** (roadmap + open questions).

This is a hobby reverse-engineering project; fork it and customize it however you like.

> ### ⚠️ Tested hardware
> Everything here has only been developed and verified on a **GameSir Cyclone 2**
> and a **GameSir G7 Pro** — **nothing else.** Other GameSir controllers, other
> dongles, and firmware revisions we haven't seen are **unsupported and untested**
> and may misbehave. The app won't send config writes to a device it can't
> positively recognize, but please don't treat it as proven-safe on hardware it has
> never seen. Use it at your own risk.

## The app

There are two frontends over the same reverse-engineered core:

- **`gamesir_qt.py`** — the **Qt/QML app** (PySide6): a polished, KDE-native UI
  with a live controller render, per-zone RGB + keyframes, stick/trigger curves,
  button remap, vibration, backup/restore, and a mouse-mode toggle. This is the
  one you install below.
- **`gamesir_gui.py`** — the original Dear PyGui app, kept as a lean fallback.

## Install (Qt app)

On **Arch / KDE**, one command after cloning:

```sh
git clone https://github.com/broroeror/gamesir-PenGUIcken.git
cd gamesir-PenGUIcken
./install.sh
```

`install.sh` installs into your home (`~/.local`), so the only step that needs
`sudo` is the one-time udev rule that lets you open the controller without root —
and it **prompts before running anything privileged**, showing the exact commands
first. You can decline the udev step; the app still installs and launches, it just
can't reach the controller until the rule is in place. Afterwards **GameSir
Cyclone 2** appears in your app launcher (or run `gamesir-cyclone2`). Remove it
with `./uninstall.sh`.

Prefer the Arch-native route? A [`packaging/PKGBUILD`](packaging/PKGBUILD) is
included. It is **not published to the AUR yet**, so `yay`/`paru` can't find it by
name — build it from the included file instead (no AUR account needed):

```sh
cd packaging && makepkg -si
```

## Requirements

- Python 3
- [`hidapi`](https://pypi.org/project/hidapi/) (`import hid`)
- [`PySide6`](https://pypi.org/project/PySide6/) — for the Qt app
  (Arch: `pyside6`)
- [`dearpygui`](https://pypi.org/project/dearpygui/) — only for the legacy app
- `xrandr` (optional; legacy app's window placement)

```sh
# Arch
sudo pacman -S --needed python pyside6 python-hidapi
# or via pip
pip install hidapi PySide6
```

## Running

The controller must be in **Xbox / XInput mode (use the Start / pause buttons)** —
the vendor protocol is inert in PS4/DS4 and Switch modes. The app warns you in
the header when the controller isn't in Xbox mode.

**Recommended — without `sudo`.** Install the included udev rule once so your
user can open the controller's `hidraw` nodes directly (and its `input` event
nodes, for the mouse-mode fix below) - scoped to GameSir's USB vendor id, nothing
else. Run this **from the repo directory** (where `70-gamesir.rules` lives):

```sh
sudo cp 70-gamesir.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then run (no replug needed — the trigger re-applies the access ACL):

```sh
python3 gamesir_gui.py
```

The rule uses `TAG+="uaccess"`, which grants access to the user logged in at the
local desktop. **The `70-` prefix matters**: udev runs rules in filename order,
and `73-seat-late.rules` is what actually applies the `uaccess` ACL — a rule
numbered `73`+ sets the tag too late and the ACL is silently never granted. On a
headless/remote box with no local seat, `uaccess` doesn't apply; use a group
instead (`MODE="0660", GROUP="input"`) and add yourself to it.

To confirm it worked, the controller's node should show your ACL:
`getfacl /dev/hidraw0` → a `user:<you>:rw-` line.

**Fallback — with `sudo`.** If you'd rather not install the rule, the `hidraw`
nodes are root-owned by default, so:

```sh
sudo python3 gamesir_gui.py
```

Note that under `sudo`, `~` resolves to `/root`, so the default Backup path lands
in `/root/` — another reason to prefer the udev-rule route.

## Safety

Short version: this app changes controller **settings**, not firmware, and
everything it does is **reversible** and stays **on your machine**. The specifics:

- **What it writes.** Edits go to the controller's *config* registers — deadzones,
  curves, button remaps, vibration, poll rate, and lighting — over the vendor
  channel, the same settings the official app changes. Writes **auto-persist** to
  the controller (there's no separate "commit" step), but they're ordinary config,
  not firmware — nothing here touches the bootloader.
- **Back up before you experiment.** **Backup / Restore → Export** snapshots all
  four profiles + lighting to a JSON file; **Restore** writes it back. Take one
  before you start changing things and you can always return to a known-good state.
  Restore is write-verify-retry and reports a clear pass/fail. Imported backups are
  **validated against the controller's known register map before any write**, so a
  hand-edited or corrupt file can't drive writes to arbitrary registers.
- **Reversibility.** Every setting the editor exposes can be set back the same way
  it was changed. The worst realistic outcome of experimenting is a profile that
  feels wrong — fixed by Restore, re-editing, or the controller's own factory-default
  reset.
- **Xbox / XInput mode only.** The vendor protocol is inert in PS4/DS4 and Switch
  modes — there the app can't reach the controller, so it can't change anything.
  Use the Start / pause buttons for Xbox mode (the header warns you when you're not in
  it).
- **No network.** No telemetry, no account, no phone-home — it's all local USB. Even
  the firmware *version* is read straight from the USB descriptor, not fetched
  online.
- **Permissions.** Prefer the udev rule (per-user `uaccess`) over running as root —
  see [Running](#running). Under `sudo`, `~` is `/root`, so backups land there.
- **Tested hardware.** Only the Cyclone 2 and G7 Pro (see the note up top). Treat
  anything else as unproven and use it at your own risk.

## How it works

The controller exposes a **vendor HID interface** (USB VID `0x3537`) with a 64-byte
command channel. In **Xbox mode**, with a sustained heartbeat, it streams input
(enhanced report `0x12` — sticks, triggers, IMU, battery, and the L4/R4/M paddles the
standard report can't see) and accepts **register read/write** commands for config and
lighting. The firmware *version* is read from the USB `bcdDevice` descriptor — no
command, no network.

For what each control reports to Linux as a normal gamepad, see
**[CONTROLLER_MAP.md](CONTROLLER_MAP.md)**. The full command set, the lighting/keyframe
register encoding, the app's architecture, and the per-controller findings (including
the G7 Pro) live in **[RESEARCH.md](RESEARCH.md)**.

## File layout

The app is split into focused modules — the connect/read loop, the shared `state`,
the command channel, and the lighting/config/backup domains. That structure and the
`research/` diagnostic scripts are documented in **[RESEARCH.md](RESEARCH.md)**
(Architecture + Methodology & tools). One-off probes and the pre-refactor monolith
live in **`archive/`**.

## Status

**Working:** live input, battery, firmware readout, Xbox-mode warning, profile
read/switch, rumble, full per-light RGB + effect presets + lighting power settings, a
**custom keyframe animation editor** (1–8 frames, play/pause), a **config editor**
(deadzones, anti-deadzones, stick trajectory + sensitivity curves incl. a draggable
custom-curve editor, trigger tuning, vibration, poll rate), **button remap**, and
**backup / restore** — all verified end-to-end on hardware. Restore is
write-verify-retry; only the active profile + lighting are guaranteed (banks
`0x02`–`0x04`, the stored profiles, appear read-only on this controller).

**Mouse-mode gotcha (KDE Plasma 6.7):** after a dongle replug, the sticks may start
driving the desktop cursor — that's **KWin's Game Controller plugin** reading the
joystick node directly, not the controller emulating a mouse. Turn it off:

```sh
kwriteconfig6 --file kwinrc --group Plugins --key gamecontrollerEnabled false
qdbus6 org.kde.KWin /KWin reconfigure   # or log out/in
```

The app also has an in-app **Stop mouse mode** toggle (desktop-agnostic fallback);
see [Troubleshooting](MANUAL.md#troubleshooting--recovery) for the full picture.

**The config register map** (banks, offsets, remap records, the inferred RT block)
and the **open items** — verifying the RT block, some remap target codes,
profile-switch sync, PS4/Switch input parsing — live in
**[RESEARCH.md](RESEARCH.md)** and **[TODO.md](TODO.md)**.

## Firmware

The Cyclone 2's firmware can be **backed up and restored** from Linux — an advanced,
opt-in, Cyclone-2-only feature (wired connection only, never over the 2.4 GHz dongle).
It's a backup/restore tool, **not** a firmware updater, and it needs the external
[jl-uboot-tool](https://github.com/kagaimiq/jl-uboot-tool) (not bundled). See
**[FIRMWARE.md](FIRMWARE.md)**.

## License & disclaimer

Released under the [MIT License](LICENSE) — use, modify, and redistribute
freely.

This is an independent, hobby reverse-engineering project. It is **not
affiliated with, endorsed by, or supported by GameSir**, and "GameSir" and
"Cyclone 2" are trademarks of their respective owners. The protocol was
reverse-engineered for interoperability, and the repository contains **no vendor
firmware or USB captures**. Provided **as is, without warranty** — you use it, and
poke at your controller, at your own risk.
