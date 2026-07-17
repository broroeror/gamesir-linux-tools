# Changelog

Notable changes to the GameSir Cyclone 2 Linux app, newest first. This is the
curated, user-facing summary; the complete history is in git. Format loosely follows
[Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- **Multi-controller support** — a top-bar picker to choose which connected
  controller the app drives, plus press-to-select (press a button on a pad to switch
  to it). Identical units are told apart by USB port.
- **GameSir G7 Pro** recognised, with live input over evdev. *(Its config editor is
  blocked on Linux — see [RESEARCH.md](RESEARCH.md) for the full reason.)*
- Per-controller **profile abstraction**, so the whole config / lighting / backup
  stack follows the active controller instead of hard-coded Cyclone constants.
- **Startup smoke test** (`smoke_test.py`) that fails if a background thread crashes
  on launch or the QML doesn't load.

### Added
- **Name your controllers** (Settings → Controllers) — call them "Black" and "White"
  instead of "Cyclone 2 #1/#2"; the top-bar picker shows your name. Each entry shows a
  wired (plug) or wireless (bands) icon and whether a controller is actually connected.
  Names are remembered **per USB port**: identical units are genuinely indistinguishable
  to the computer (same PID, same firmware version, and a USB serial that's a constant
  shared across models), so the port is the only stable key — moving a dongle to another
  port leaves its name behind. The UI shows the port so this is never a surprise.

### Changed
- **"Restore default lighting" moved to the Lights page** (it was buried in Settings)
  — and it now actually works on the **G7 Pro 8K**, which previously had no factory
  baseline to restore, so the button silently did nothing there.

### Fixed
- **Empty dongles no longer masquerade as controllers.** A dongle with nothing paired
  to it still enumerates (and still streams empty input), so it showed up as a phantom
  controller — a wired 8K appeared twice, and dongles for powered-off pads listed as
  connected pads. The picker now shows each device's real state: a **wired (plug) or
  wireless (signal bands) icon**, and "No controller" for an idle adapter.
- **8K home-ring selection is legible again** — the selected quadrant's "shadow" was
  black against a dark card, i.e. invisible. Selected wedges now get an outer glow plus
  an inner shadow, driven by a new themeable **"Selection glow"** colour (light themes
  get a dark halo, since a white one on a white card is invisible).
- **8K home-ring colours** — the ring's hue register is 16-bit (the colour angle in
  degrees, 0–359), but only the low byte was being written. That capped the ring at
  255° so the top of the wheel (magenta/pink/red) was unreachable and came out purple,
  and it stranded a stale high byte that shifted every later edit on that quadrant by
  256° — the cause of a quadrant appearing "stuck" or refusing to match the colour you
  picked. Hue is now written in full, so the whole wheel works and the picker matches
  the physical ring. Backups also now capture the complete per-quadrant colour.
- **Controller switching** — the picker dropdown and press-to-select now both
  actually switch the driven controller (the dropdown taps weren't reaching the
  backend; press-to-select had crashed on a stale import after a script move).
- **Robustness / hardening** — imported backups are validated against the known
  register map before any write; the live reader survives malformed or short USB
  reports and truncated capture files. *(Local single-user threat model.)*
- **UI fit** — the top bar is responsive (the settings gear always stays reachable),
  and the Sticks / Triggers / Lights pages no longer clip at the default or minimum
  window size.

### Changed
- **Documentation restructured** into a lean [README](README.md) (overview), a
  [Manual](MANUAL.md) (how to use each feature, troubleshooting, FAQ), and
  [RESEARCH.md](RESEARCH.md) (protocol, architecture, and per-controller findings).

### Firmware Backup & Restore (advanced, optional)
- Back up the Cyclone 2's firmware and restore your own backup — wired only, brick-
  safe, and gated by an on-chip identity check. Needs the external jl-uboot-tool
  (not bundled). See [FIRMWARE.md](FIRMWARE.md).

## [0.1.0-alpha.2]

### Added
- **Config editor** — deadzones, anti-deadzones, stick trajectory, sensitivity curves
  (presets **and** a draggable custom-curve editor), trigger tuning (hair-trigger +
  response curve), vibration, poll rate, and button remap.
- **Lighting** — per-light RGB, effect presets, brightness / speed, power settings
  (audio-reactive / pick-up-to-wake / sleep), and a custom keyframe animation editor.
- **Backup / Restore** — snapshot all four profiles + lighting to JSON and write it
  back, with write-verify-retry (verified end-to-end on hardware).
- **Mouse-mode toggle** — turn KDE/KWin's sticks-drive-the-cursor behaviour off (or on
  for "couch mode"), with a desktop-agnostic EVIOCGRAB fallback.
- **One-command install** (`install.sh`) with a `.desktop` launcher, icon, and udev
  rule; plus a `packaging/PKGBUILD` for Arch.
