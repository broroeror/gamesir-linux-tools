# Deadband — Linux device configuration manual

The user guide for the **[GameSir Cyclone 2 Linux app](README.md)**: how to use each
feature, how to get out of trouble, and the questions that tend to come up. For
install and a quick overview start with the [README](README.md); for the protocol,
the app's architecture, and reverse-engineering findings, see
[RESEARCH.md](RESEARCH.md).

## Contents

- [Using the app](#using-the-app) — every feature, what it does and how to use it
- [Troubleshooting & recovery](#troubleshooting--recovery) — when something isn't working
- [FAQ](#faq) — the questions that come up

## Using the app

Launch it from your app menu as **Deadband**, or run `deadband` from a terminal.
Everything below assumes the controller is connected and in **Xbox / XInput
mode**. A G7 Pro at `3537:100a` is transitioned automatically to wired `3537:109b`
or dongle `3537:109c`. If it shows `3537:1022`, hold **MENU (START)+SHARE**
together; use the Start / pause mode control on the other supported GameSir
controllers. The header shows a warning until the expected identity is available.

### Live input view

The main view mirrors the controller in real time: sticks, triggers, D-pad, every
face and shoulder button, the extra **L4 / R4 / M** paddles (plus Home / Share),
battery level and charging state, and the firmware version. It's the quickest way to
confirm a control works — and to watch a config change take effect as you make it.

### Profiles

The controller stores **four profiles**. The app shows the active one and lets you
switch between them (1–4); a **rumble test** button fires both motors so you can
check your vibration settings. On the G7 Pro, the pills choose which stored bank
to edit without changing the profile currently active on the controller.

### Lighting

- **Per-light colour** — set the left grip, right grip, profile, and home lights
  individually.
- **Effect presets** — Flow, Rainbow, Pulse, Alarm, Standoff — one click each, with
  **brightness** and **speed** sliders.
- **Power settings** — audio-reactive lighting, pick-up-to-wake, and the sleep
  timeout.
- **Keyframe editor** — build your own animation: add up to **8 keyframes**, set each
  one's colours, randomize, and **play / pause** (Pause holds the frame you're
  viewing). Your exact keyframes are remembered per slot, so switching profiles and
  back restores them precisely.

### Config editor

Tune how the sticks and triggers behave, per profile:

- **Sticks** — deadzone min/max, anti-deadzone, trajectory, and a **response curve**
  (presets **or** a draggable custom curve), for both sticks.
- **Triggers** — deadzones, a **hair-trigger** point, and a response curve.
- **Vibration** — left / right motor strength.
- **Poll rate.**

Edits read the selected profile's current values and are staged in the pending bar.
Choose **Apply** to persist the batch to the controller. Take a **backup** first if
you're experimenting (see below).

### Button remap

Remap any input to another: pick a source button and a target, or clear a remap to
restore the default. Remaps are part of the profile, so a backup captures them.

### Backup / Restore

**Backup / Restore → Export** snapshots **all four profiles + device settings** to a JSON
file (default name `deadband_<model>_<timestamp>.json`). To restore, pick that file — an
inline **"Write loaded backup to controller"** button appears; it writes every block
back, reads it back to confirm, re-sends anything that didn't take, and reports a
clear pass/fail. The G7 Pro backup is semantic: it contains only the settings the
app understands, including its dock settings, and can address all four banks
directly. Think of this as your undo button: snapshot before experimenting,
restore to return.

### Mouse-mode toggle

On KDE Plasma the sticks can end up driving the desktop cursor — that's a KWin
feature, not the controller. The app's **Stop mouse mode** toggle suppresses it on
demand; the cleaner permanent fix is a KDE setting. Both are in
[Troubleshooting](#troubleshooting--recovery).

## Troubleshooting & recovery

Most problems are one of three things: the controller isn't in Xbox mode, the
udev rule isn't applying, or the compositor grabbed the sticks. Start here.

### The app can't see the controller ("not connected" / empty input)

- **Is it in Xbox / XInput mode?** A G7 Pro at `3537:100a` transitions
  automatically. For `3537:1022`, hold **MENU (START)+SHARE** together to expose
  wired `3537:109b` or dongle `3537:109c`. Use the Start / pause mode control for
  the other supported GameSir controllers. The header shows the appropriate warning.
- **Is the udev rule installed and applied?** From the repo directory:
  ```sh
  sudo cp 70-gamesir.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```
  Unplug and replug the controller, then confirm its node has a `user:<you>:rw-`
  ACL. G7 Pro configuration uses `/dev/bus/usb/BBB/DDD`; other models use
  `/dev/hidrawN`.
- **Filename-ordering gotcha.** The rule must sort *before* `73-seat-late.rules`
  (the rule that actually applies the `uaccess` ACL). The shipped `70-` prefix is
  correct — don't renumber it to `73`+, or the ACL is silently never granted.
- **Headless / no local seat?** `uaccess` only grants to a logged-in *local*
  desktop seat. On a remote box, swap it for a group rule
  (`MODE="0660", GROUP="input"`) and add yourself to that group.
- **Last resort:** run with `sudo` (root owns the nodes by default) — but then
  backups default to `/root/`, so prefer the udev rule.

### The "not in Xbox mode" warning won't clear

The controller is using an identity where its supported configuration protocol is
unavailable. On a G7 Pro, Deadband automatically handles `3537:100a`; for
`3537:1022`, hold **MENU (START)+SHARE** together to reach wired `3537:109b` or
dongle `3537:109c`. On the other controllers, use the Start / pause mode control.

### Settings don't stick, or a restore reports unconfirmed blocks

The controller **silently drops a command sent right after another**, so a naïve
write can lose a block. The app writes **write-verify-retry** — it reads every
block back and re-sends whatever didn't take, over a few passes, then reports
pass/fail. If a restore says some blocks are unconfirmed:

- **Stored profiles 2–4** (register banks `0x02`–`0x04`) appear **read-only** on
  this controller, so only the **active profile + lighting** are guaranteed to
  restore. The status line calls this out — it's expected, not a failure.
- For the **active profile / lighting**, just run **Restore** again; a second pass
  almost always lands the dropped block.

### Moving the sticks drives the desktop cursor

That's not the controller emulating a mouse — on Plasma 6.7 it's **KWin's Game
Controller plugin** reading the joystick evdev node directly. Fixes, best first:

- **Disable the plugin** (permanent; games are unaffected because they read evdev
  directly):
  ```sh
  kwriteconfig6 --file kwinrc --group Plugins --key gamecontrollerEnabled false
  qdbus6 org.kde.KWin /KWin reconfigure   # or just log out/in
  ```
  There's also a **System Settings → Game Controller** toggle.
- **In-app "Stop mouse mode" toggle** — a desktop-agnostic fallback that takes an
  exclusive grab on the joystick node. While it's on, evdev games (Steam/SDL)
  won't see the pad either, so prefer the plugin toggle on KDE.

### Backups ended up in /root

You ran the app under `sudo`, where `~` resolves to `/root`. Install the udev rule
and run without `sudo` (see [Running](README.md#running)); backups then default to
your home directory.

### Recovery — back to a known-good state

- **Restore a backup.** If you exported one before experimenting (the app makes it
  one click), **Backup / Restore → Restore** writes it back and verifies it. This
  is the fastest undo.
- **Factory defaults.** The Buttons page offers a **Default profile** reset for a
  recognized controller with a captured factory image, and the controller has its
  own hardware reset. Config and lighting are ordinary settings — nothing the app
  changes is permanent.
- **Restart the app.** State is re-read live on connect, so a confused UI usually
  clears on relaunch or a controller replug.

## FAQ

**Will this brick my controller?**
Everyday use changes controller **settings** (config + lighting) — ordinary,
reversible register writes, not firmware. Take a backup first (**Backup / Restore →
Export**) and you can always undo. Nothing in normal use touches the bootloader.

**Does it phone home? Do I need an account?**
No. It's all local USB — no network, no telemetry, no account. Even the firmware
*version* is read straight from the USB descriptor, not fetched online.

**Will it work with my other GameSir controller?**
Only the **Cyclone 2** and **G7 Pro** have been tested; anything else is
unsupported and untested. The app **refuses state-changing writes to a device it
can't positively recognize**, so an unknown model reads but won't be written.

**Do I need `sudo`?**
No — install the udev rule once and your user gets access. `sudo` is only a
fallback, and under it backups land in `/root/`. See [Running](README.md#running).

**Does it work over the 2.4 GHz wireless dongle?**
Yes for monitoring and control — the reader survives a switch from cable to dongle
and keeps going. A direct cable is the most reliable for a long batch of writes
(a big restore).

**Wayland / KDE?**
The Qt/QML app is KDE-native and runs on Wayland. The sticks-drive-the-cursor
behaviour is a KDE feature with a KDE fix, plus a desktop-agnostic fallback — see
[Troubleshooting](#troubleshooting--recovery).

**Is this official / affiliated with GameSir?**
No. It's an independent, hobby reverse-engineering project for interoperability,
not affiliated with or endorsed by GameSir; trademarks belong to their owners.

**How do I add support for another controller, or help reverse-engineer one?**
Models are defined in `controller_profile.py`; capture the official app's USB
traffic and decode it with the diagnostic scripts — all documented in
**[RESEARCH.md](RESEARCH.md)** (Architecture, Methodology & tools, and the current
per-controller findings).
