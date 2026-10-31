# Changelog

Notable changes to Deadband — the Linux configuration app for GameSir controllers
and Logitech mice — newest first. This is the
curated, user-facing summary; the complete history is in git. Format loosely follows
[Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- **G7 Pro Wuchang wireless configuration** on its `3537:10a8` receiver (#17).
- A **Swap** setting on the Lights page for Cyclone 2 units whose Home and
  Profile lights are wired the other way round (#48).
- **macOS support (early).** Deadband runs on macOS from source; tested on
  Apple Silicon with a Cyclone 2, a Tarantula Pro 8K and a G502 X (remaps,
  live input, profiles, lighting, mouse pages). A Cyclone 2 dongle there leaves
  its settings interface without a driver, so Deadband reaches it over USB
  directly (PyUSB + libusb-package). `--doctor` gives a Mac-specific report.
  Press-to-select, and configuring the G7 Pro / Kaleid / G7 SE, stay
  Linux-only for now. Setup: [docs/macos.md](docs/macos.md).
- **Controller picture**: Settings → Appearance can swap the drawn controller
  for your own image (per controller model, kept on your computer), with a
  template export to line the art up with the buttons. Thanks to
  [@sinchrotron](https://github.com/sinchrotron) for the idea (#42).

- **G7 Pro 8K PC, newer plain black units** (`1034` wired, `1035` receiver),
  from three owners' reports (#29, #44, #46). Its plain-HID mode (`10b8`) now
  says it needs a kernel setting to stay in XInput, and the Manual has a new
  troubleshooting entry for that (also covers the G7 SE's `10a0`, #41).
- **G7 Pro 8K: L5/R5 light up when pressed, and the Share button can be
  remapped.** Contributed by
  [@SemiRealProductions](https://github.com/SemiRealProductions) (#49, #50).
- `--probe` also asks the input-only modes of known controllers, such as the
  G7 SE's `10a0` (#41).

### Changed
- The Tarantula Pro 8K is drawn in the same slate style as the other
  controllers instead of its orange product colours.

### Fixed
- G7 Pro native `1022`: correct the false sequential-button-layout warning (#17).
- Switching paddles on the Macros tab showed the previous paddle's macro, and
  the next edit then saved it onto the paddle you'd switched to, so one
  paddle's macro could overwrite another's (#51).
- The navigation, numpad and media keys in the remap and macro pickers sent
  different keys than their labels said (Delete came out as Page Down, for
  example). Every one has now been checked on a Cyclone 2 and an 8K, and
  bindings made in GameSir's app show their real names (#47).
- A controller macro made shorter kept playing the old macro's leftover steps,
  because the controller doesn't stop at the step count. Saving a macro now
  clears the rest of its steps. On the G7 Pro 8K, macros are capped at 31 steps
  so they no longer overwrite a setting stored after them (#51).
- The G502 X first-time setup didn't appear on a mouse whose profile list names
  its factory sectors instead of being blank, which is how at least one fresh
  G502 X ships (#28).
- The G502 X macros tab opened empty for a button that already had a macro
  saved on the mouse. Saved macros now load into the editor; one made in
  another app that the editor can't represent says so instead.

## [0.6.0] — 2026-10-23

### Added
- **G502 X first-time setup**: a mouse that never met G HUB is still on its
  read-only factory profiles, which Deadband refused to edit ("profile CRC not
  OK"). The mouse pages now offer a one-time **Set up editable profiles** that
  copies them into editable slots, the way G HUB does (#28, thanks
  [@Odecam1](https://github.com/Odecam1) for the diagnostics).
- **Gruvbox theme, and theme import/export**. Contributed by
  [@JoaoVitorSCS1999](https://github.com/JoaoVitorSCS1999) (#35).
- **RGB and HEX inputs** in the colour picker. Contributed by
  [@JoaoVitorSCS1999](https://github.com/JoaoVitorSCS1999) (#34).
- `deadband --help`, `deadband --version`, and Bash / Zsh / Fish completions.
  Contributed by [@JoaoVitorSCS1999](https://github.com/JoaoVitorSCS1999) (#33).
- **GameSir G7 SE firmware 6.64** (`3537:1069`): every button's remap
  (including LT/RT), sticks (deadzones, curves, sensitivity, invert,
  trajectory), triggers (deadzones, curves, hair trigger), grip and trigger
  vibration with motor tests, per-profile report rate, and Backup & Restore.
  The `1082` fallback is no longer mistaken for a Kaleid, and a pad held on
  `10a0` is described as input-only. Contributed and hardware-tested by
  [@guarienteherbert-ux](https://github.com/guarienteherbert-ux) (#31). See
  [docs/g7se.md](docs/g7se.md#firmware-664-35371069).
- `deadband --doctor --probe`: opt-in, read-only device questions for bug
  reports — a G502 X's firmware, onboard-profile layout and per-profile
  checksums (and where a mismatched one really sits), whether an unsupported
  GameSir controller answers the family protocol, and the full button records
  of a connected Cyclone 2 / G7 Pro 8K / Tarantula (to learn how GameSir's app
  stores key combinations).

### Changed
- On systems whose hidapi bindings install both backends (`hidraw` and the
  libusb `hid`), Deadband now uses `hidraw`. The libusb one can't open
  `/dev/hidraw` devices, which showed up as a misleading "reinstall hidapi"
  warning (#36, thanks [@Barracuda72](https://github.com/Barracuda72)).

### Fixed
- Closing Deadband printed hundreds of "Cannot read property … of null" lines;
  the interface is now torn down before the parts it reads from.
- Closing Deadband could also print HID errors from cleanup running during
  Python's shutdown. Contributed by [@ry2x](https://github.com/ry2x) (#38).

## [0.5.0] — 2026-10-13

### Added
- **G7 Pro Wuchang edition** (wired `3537:10a7`), plus G7 Pro **gyro settings**
  (Aim / Tilt), **live gyro and accelerometer readings**, and **a test button for
  each of the four vibration motors**. Contributed and hardware-tested by
  [@sinchrotron](https://github.com/sinchrotron) (#20). A G7 Pro whose gyro block
  was never filled in gets the documented defaults on its first gyro edit.
- **Cyclone 2 Continuous Trigger** (tap to hold, tap to release) for every
  remappable button, and View / Menu / Capture as remap targets. Contributed by
  [@b1naryblaz3](https://github.com/b1naryblaz3) (#22).
- **G7 Pro 8K PC Championship edition** (`10b7` wired, `10b9` dongle), verified
  by its owner (#23). The README now lists the 8K editions.
- **Deadzones are typable** as well as draggable, which makes the 8K's fine
  (0.1%) steps usable. Dragging back to the controller's own value no longer
  counts as a change.
- The diagnostics report shows each controller's **USB link speed** and the real
  maximum report rate it allows.
- The Tarantula Pro 8K has its own controller drawing.
- **GameSir G7 SE** (`3537:1010`, firmware descriptor 6.30): persistent L4/R4
  gamepad remapping across the three Nexus profiles and controller-wide
  250/500/1000 Hz report-rate settings, staged Save with durable
  originals and verified rollback, automatic cold-connection authentication,
  and live trigger/stick readouts. Release returns the controller to games.
- **GameSir Kaleid — lighting support.** The Xbox-licensed Kaleid doesn't answer
  the GameSir hidraw vendor protocol every other model here uses; that collection
  is present on the pad but vestigial. Deadband now reaches it the way the vendor's
  own app does, with the same GameSir register protocol tunnelled through **Xbox
  GIP** on its `3537:1012` identity. Its lighting turned out to be the Cyclone 2's
  engine byte for byte — the pad's four stored records hold palettes identical to
  this project's captured Cyclone presets, matching on keyframe count and speed —
  so it gets the full keyframe editor, minus the slot selector, power block and
  play/pause it doesn't have. Write round-trip verified by [@bloodrizer](https://github.com/bloodrizer) on their pad.
- **The light map is per model now.** A controller profile can override which
  render-frame positions each addressable light drives (`lighting_lights`), and one
  light may drive several. The Cyclone's four lights sit one per position with a
  dead position at 2; the Kaleid measured as **two** lights, left and right, each
  flooding a whole side from a pair of positions, with its dead position at 3. The
  Lights page sizes its zone list off the model instead of assuming four.
- The Kaleid's other two modes (`1082` DirectInput, `1086` XInput) are recognised
  and named, with a prompt to press `M + Xbox`, instead of falling through to the
  Cyclone map and reporting a misleading "not in Xbox mode".
- A startup check that no two controller profiles claim the same USB product id.
  With eight profiles and ids a few digits apart, a duplicate would silently
  resolve to whichever is listed first — and hand the loser the winner's map.

### Fixed
- **The Reset profile button had been missing since September 8**; it's back.
- **Two quick Saves to a profile you weren't on could write the second one to the
  wrong profile.** Deadband trusted the controller's last-known profile right
  after switching back; it now waits for a fresh answer.
- **Restoring a backup failed on every controller except the G7 Pro.** Since G7
  Pro support arrived (early September), exports from the Cyclone 2, G7 Pro 8K,
  Tarantula and Kaleid were labelled with the G7 Pro's backup format number, and
  Restore then refused them unless a G7 Pro was connected. Exports are labelled
  correctly again, and backups made in the meantime restore normally — nothing
  in them was wrong, only the label.
- **Export, Restore and "Reset all profiles" now confirm each profile switch**
  before reading or writing that profile, re-sending a dropped switch. Before, a
  dropped switch could export one profile's settings under another's name, or
  write to a profile that wasn't active. If a profile won't switch, they say which
  one and touch nothing in it, and an Export interrupted by a profile change
  mid-read is refused rather than saved. All of them (and Save) now share one
  switch routine.
- **Clicking a profile could briefly show the previous profile's settings** on
  the Cyclone 2, G7 Pro 8K and Tarantula: its settings were read before the
  controller had finished switching, and a profile only answers while it's the
  active one. Deadband now waits for the switch to be confirmed first.
- **"Restore default lighting" on the Cyclone 2** put a static red/blue in the
  first lighting profile, while "Reset profile" puts GameSir's default Flow
  there; both now use GameSir's Flow. The restore is also tied to the controller
  it started on, so swapping controllers mid-write can't land it on another.
- **G7 Pro 8K:** a ring effect or sleep time Deadband doesn't know showed as
  "Off"; it now shows no selection rather than a wrong one.
- "Reset all profiles" now reports a profile whose defaults couldn't all be
  written, and writes the shared lighting once instead of once per profile.
- G7 Pro: unusual firmware-version text could end the configuration session.
- **Mouse (G502 X): saved changes weren't felt until the profile was switched.**
  The mouse loads a profile only when it's selected, so a DPI or button change
  saved to the profile it's running stayed unused. Deadband now has the mouse
  reload it after saving (and after a factory reset).
- **Mouse (G502 X): not found over its wireless receiver on newer kernels.**
  Linux 7.2's Logitech receiver driver answers with the mouse's receiver
  address (1) where older kernels translated it, and Deadband ignored those
  replies, so a mouse in use the whole time showed as missing. Deadband now
  tries both addresses, and finds the mouse faster (0.7 s instead of up to ~8 s).
- **Mouse (G502 X):**
  - A change made while an Apply was running (including the macro editor's own
    auto-save) was silently dropped; only what the Apply wrote is now cleared.
  - One failed read no longer wipes everything staged; it says what went wrong.
  - With the receiver plugged in and the mouse off, Deadband no longer reports
    a permissions problem.
  - Picking another profile during an operation, or a factory reset that fails,
    no longer loses or mislabels staged changes.
  - A profile named by other software (Solaar) can be edited again.
  - Emoji names over the 24-character limit get a clear message, out-of-range
    macro scroll amounts and buttons are refused instead of wrapping, and a
    failed write only says "reverted" once the revert is confirmed.
- The macro editor's number boxes (hold, delay, Duplicate ×) silently ignored a
  value above their limit; they now clamp it, and always show what was applied.
- **Lighting records could be read back misaligned on a transport with a smaller
  reply.** The 124-byte record was always read in 56-byte chunks, which is the
  Cyclone's hidraw limit; GIP carries 55, and the pad answers short rather than
  refusing, so every byte after the first chunk shifted and decoded into a
  plausible but wrong palette. The chunk size now comes from the controller
  profile, and a short reply fails the read instead of stitching misaligned bytes.
  Only reachable on the Kaleid, which is new here, so no released model was
  affected.

### Changed
- **One Save path for the Cyclone 2, G7 Pro 8K, Tarantula and Kaleid:** Save
  records the current values in a recovery file, writes, reads every change back,
  and restores the originals if anything doesn't match. Recovery files are capped
  at the newest 20.
- **Lighting waits for Save, like every other page.** Presets, colours, keyframes,
  brightness, speed, power settings, and the G7 Pro 8K's ring and dock settings
  used to be written to the controller the moment you touched them, with nothing in
  the app showing a change had been made. They're now staged in the pending bar
  (Discard puts the page back), and Save writes them through the same
  backup / verify / roll-back path as the rest. The Lights page also highlights
  the preset that's on the controller, and the separate "Apply colors" / "Apply
  animation" buttons are gone. A preset, its speed and its brightness are one
  write to the pad but count as separate changes in the bar.
- Save sends a write once more if its read-back doesn't match before treating it
  as a failure: these controllers occasionally drop a vendor write.
- The Lights page explains that lighting profiles are separate from controller
  profiles, and the README no longer says profiles 2–4 are read-only (they aren't).
- A **Sponsor** button (Ko-fi) on the GitHub page.
- The "Configure controller / Release to games" session and its released-state
  overlay are now driven by whether a model is configured over a *claimed USB
  interface*, rather than by "is this a G7 Pro" — the Kaleid is the second such
  model.
- Controllers with no editable profile banks no longer show the profile-editor
  tabs, instead of offering pages that can read but never write.
- `control.set_profile()` refuses on a controller whose profile declares no
  software profile switch. On the Kaleid the vendor's profile-select command
  (`0x07`) doesn't select anything — it writes a byte in the *profile* banks that
  links a profile to its lighting record, collapsing several of the on-pad chords
  onto one. Guarded at the single place the command is sent.

## [0.4.0] — 2026-10-02

### Added
- **GameSir Tarantula Pro 8K** (in its PC mode, `3537:103d`): rebinds for all
  nine programmable buttons (L4, R4, C1–C4, T1–T3), macros, sticks, triggers,
  gyro and poll rate up to 8000 Hz. Lighting isn't supported yet. Write-tested on
  my own pad.
- **More G7 Pro editions.** Amazon edition, wired (`10ba`) and on its dongle
  (`10bb`), write-tested on my own pad. White Trimode, on the cable (`1003`) and on
  its charging dock (`1004`), confirmed by an owner. Zenless Zone Zero (`105e`) is
  recognised but not configured yet.
- **G7 Pro 8K Royal2 edition** (`1032` / `1033`), contributed by
  [@kakxem](https://github.com/kakxem) in #12.
- **An active-profile dot on every controller**, showing which profile the pad is
  actually running, separately from the one you're editing.
- **Poll rate is a dropdown in the tab row**, next to the profile it belongs to.
- **Diagnostics:** each GameSir device's declared vendor channel, its interface
  classes and drivers, which HID library is in use, and plain explanations for a
  pad in the wrong mode.

### Changed
- **Motion edits now wait for Save to Profile**, with Discard, like every other
  settings page. They used to be written the moment you clicked. The Macros tab,
  which still saves as you edit, now says so on screen.
- G7 Pro: sliders (not five fixed steps) for vibration, trigger motors and dock
  brightness; the Device page laid out like the other tabs; "Release to games"
  no longer looks like a fifth profile; L5/R5 drawn on the top edge as the
  shoulder buttons they are.
- Tabs follow what the controller has, so a pad without rumble motors or mapped
  lighting doesn't get an empty page.
- "Sleep timer" is called the same thing on every controller.
- **Firmware backup and restore have been removed.**

### Fixed
- **The profile bar had been missing for every controller since v0.3.0.**
- G7 Pro: X and Y swapped in the input view; paddles read from the wrong byte.
- Selected buttons and pills were hard to read on the Emerald and Amber themes.
- **SteamOS install** (#13, #19): no more pacman conflict with the Deck's own
  hardware support, and no `pip` or compiler needed.
- **"My G7 Pro was renamed to a T4 Kaleid"** (#14): the White Trimode's dock ID
  is also the T4 Kaleid's ID in the Linux kernel, which labels it wrongly and gets
  no input from it. Deadband no longer confuses the two; nothing writes a pad's
  identity.
- Diagnostics: couldn't see the Amazon edition at all; checked the wrong place for
  the udev rule on packaged installs; reported harmless permission denials as
  errors.

## [0.3.0] — 2026-09-06

### Added
- **GameSir G7 Pro configuration** — contributed by
  [@brcly](https://github.com/brcly) and verified on their hardware. Config rides a
  vendor-class USB interface that exposes no hidraw node, reached through a native
  `libusb` transport (no extra Python package; the system `libusb-1.0` runtime is
  now a dependency). The mode switch this project had written off as untriggerable
  from Linux turns out to be a physical button combo. Targets the
  **Shadow Ember** edition (`3537:109b` wired, `3537:109c` dongle), transitioning
  `3537:100a` automatically.
- **Other G7 Pro editions are recognised and named** — White Trimode, Zenless Zone
  Zero, and an Amazon edition — so their owners get "config isn't supported for this
  edition yet" instead of a bare USB id. They deliberately have no write path: the
  register map looks common to all editions, but nobody has confirmed that on
  hardware, and a guess isn't worth someone's stored config.
- **Mouse profiles (G502 X)** — all five onboard profiles. Pick which one you're
  editing without switching to it, rename them (stored on the mouse), double-click to
  make one active, and restore any of them to the copy the mouse itself shipped with
  in ROM. Verified on hardware.
- **Per-macro playback speed** for mouse macros, which offsets the mouse's own
  per-step overhead — a recorded macro otherwise plays back slightly slower than it
  was typed.
- **App version and git commit in the diagnostics report**, so a bug report
  identifies which build is running (the AUR package tracks `main`).
- **Issue templates** that ask for the diagnostics report.
- **Offline checks** (`vendors/logitech/offline_checks.py`) — 20 hardware-free
  regressions over the mouse write paths that can damage stored settings.

### Fixed
- **Editing a mouse macro no longer burns a flash slot.** Flash can't be rewritten in
  place, so replacing a macro stranded its old sector; an apply now sweeps
  unreferenced sectors automatically.
- **A crash no longer leaves a controller inert.** Claiming a USB interface displaces
  the kernel driver, and the kernel does not rebind it when the holder dies — measured
  as `usbhid` → `usbfs` → nothing. An atexit hook and a chained SIGTERM handler now
  release it on the exits Python can observe.
- **The live stick on the Rebinds page** read as a low frame rate: it tweened its
  position over 40ms while input arrives every 16ms, so every sample restarted an
  animation that never finished and the dot permanently chased the thumb.
- **Poll rate did nothing** — a `@Slot(str, int)` declaration on a one-argument
  method, now guarded by an AST check in the smoke test.
- **Unnamed mouse profiles showed boxes** instead of falling back to "Profile N":
  `0xFF` name padding decodes to U+FFFF, which is unprintable but not empty.
- **"Free unused slots" was hiding itself** exactly when it was needed — it only
  appeared once slots were nearly exhausted.
- Mouse **backups now precede the first flash write** and work on an installed app.

### Removed
- **Firmware backup & restore.** It needed an external tool that was never
  bundled, so in practice it did nothing for anyone who installed the app, and
  it widened the project's scope well past configuring a controller. Suggested
  by a GameSir community moderator, and I agreed. Reading the firmware *version*
  is unaffected — that's just a USB descriptor and it still shows in the header.

### Changed
- **Documentation brought back in line with the app.** The manual had no mouse
  section at all; RESEARCH.md had no G502 X section and contradicted its own summary
  table; both still described a Cyclone-only project.

## [0.2.0] — 2026-09-02

### Added
- **Multi-controller support** — a top-bar picker to choose which connected
  controller the app drives, plus press-to-select (press a button on a pad to switch
  to it). Identical units are told apart by USB port.
- **GameSir G7 Pro** recognised, with live input over evdev. *(Config editing was
  still blocked on Linux at this point — see the Unreleased section above.)*
- Per-controller **profile abstraction**, so the whole config / lighting / backup
  stack follows the active controller instead of hard-coded Cyclone constants.
- **Startup smoke test** (`smoke_test.py`) that fails if a background thread crashes
  on launch or the QML doesn't load.
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
- **Documentation restructured** into a lean [README](README.md) (overview), a
  [Manual](MANUAL.md) (how to use each feature, troubleshooting, FAQ), and
  [RESEARCH.md](docs/RESEARCH.md) (protocol, architecture, and per-controller findings).

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

### Firmware Backup & Restore (advanced, optional)
- Back up the Cyclone 2's firmware and restore your own backup — wired only, brick-
  safe, and gated by an on-chip identity check. Needed the external jl-uboot-tool
  (never bundled). *Removed in a later release — see Unreleased.*

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
