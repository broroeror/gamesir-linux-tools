# GameSir Cyclone 2 (Linux) — TODO / Roadmap

Open bugs, proposed changes, and reverse-engineering questions. **Completed work
moves to the [CHANGELOG](CHANGELOG.md)** (and the full history is in git), so this
stays a forward-looking list. Linked from the [README](README.md). Hobby project —
**fork it and customize it however you like.**

Keep entries short (a date helps). Tick items off (`- [x]`) as they land, then move
them into the CHANGELOG so this file doesn't grow stale.

---

## 🐞 Known bugs / rough edges

- [ ] **Restore only covers the active profile + lighting.** Banks `0x02`–`0x04`
      (the stored, non-active profiles) appear read-only when written directly, so
      Restore can't push them. Likely fix: switch to profile N so it loads into
      bank `0x01`, write there, repeat — depends on the profile-switch→bank-sync
      question below.
- [ ] *(environment, not this app)* **KWin 6.7 logout SIGSEGV** in
      `RenderLoop::activeWindowControlsVrrRefreshRate()` during compositor teardown,
      on multi-output + hybrid NVIDIA/AMD. Workaround: System Settings → Display →
      Adaptive Sync → *Never*. Worth reporting upstream to KDE.

## ✨ Enhancements / proposed changes

- [ ] **Bind the mouse-mode toggle to a controller button** via the controller's
      macro/keybind system (the original stretch goal). Needs a USB capture of the
      official app's macro/keybind screen to learn the command format.
- [ ] *(blocked, external)* **Publish the package to the AUR.** Waiting on AUR account
      creation, which is disabled upstream for the maintainer right now. Not on the
      critical path — both install routes work without it. Revisit when registration
      reopens.
- [ ] **Collapse overlapping helper modules** (`gs_common` / `gs_state` vs the
      `gamesir_*` modules) for a leaner runtime surface. *(The RE-script reorg into
      `research/` is already done — see the CHANGELOG.)*
- [ ] **Restore: per-block verify detail.** The write-verify-retry already reports
      pass/fail; could add a "verify only" action or a list of any unconfirmed blocks.
- [ ] **Couch-cursor / stick-to-mouse as a *feature* on Windows & macOS** *(2026-07-08)*.
      Note this is the **inverse** of the Linux mouse-mode toggle: on KDE the app
      *suppresses* KWin's built-in stick→pointer plugin (`gamesir_kwin.py`); Windows
      and macOS have no such OS feature to suppress, so here we'd **generate** the
      cursor input ourselves — a brand-new, cross-platform module sharing ~no logic
      with the KWin/EVIOCGRAB paths. Approach: read the pad (Windows: XInput / raw HID;
      macOS: `GCController` / IOKit HID) → synthesize mouse move+click (Windows:
      `SendInput`; macOS: `CGEvent`). macOS needs **Accessibility** (TCC) permission;
      Windows runs unprivileged. Prior art: Steam Input, JoyToKey, DS4Windows. Depends
      on the portability work below landing first (device discovery via `hid.enumerate()`).
- [ ] **Cross-platform portability (macOS / Windows).** The core — PySide6 + hidapi +
      the pure-Python protocol — already runs anywhere. The one Linux-coupled
      chokepoint is device discovery in `gs_common.find_vendor_nodes()`
      (globs `/sys/class/hidraw`, opens `/dev/hidraw*`). Swap it for `hid.enumerate()`
      (select by vendor id `0x3537` + interface) and macOS/Windows are unblocked —
      ~one function, Linux behaviour unchanged. Mouse-mode, the evdev diagnostics, and
      the installer stay Linux/KDE-only and degrade gracefully. Needs a Mac/Windows box
      to test.

## 🚀 Long-term / big bets

The project's north-star goals — larger efforts. Hardware on hand: **two Cyclone 2s**
and a **GameSir G7 Pro**. *(Full per-controller findings in **[RESEARCH.md](RESEARCH.md)**.)*

- [ ] **Audio responsiveness via the headset jack.** Investigate forcing system audio
      out through the controller's 3.5 mm jack, and driving the audio-reactive LEDs from
      real audio via a host-side PipeWire capture → amplitude → the audio-reactive
      lighting stream (see the streaming-format RE question below).

## 🔬 Open reverse-engineering questions (need USB captures)

- [ ] **Verify the RT trigger block** (currently inferred as the LT block mirrored at
      `+0x1c`) against a capture of an RT-setting change.
- [ ] **Audio-reactive lighting: reverse the host-streaming format.** The enable flag
      (`0x20` / `0x026d`) is known, but the effect is *host-driven* (no mic on the
      controller), so the PC must stream audio levels. Needs a live USBPcap of the
      official app with audio-reactive **on** over loud/quiet/loud music to learn the
      streaming command, then a PipeWire monitor → amplitude → stream pipeline.
- [~] **Reprogram View / Menu / L4 / R4 — vendor-protocol *target* codes.** *Target
      codes now known* from the G7 captures (`LB=05, RB=06, LS=07, RS=08, A=09, B=0a,
      X=0b, Y=0c, LT=13, RT=14`, written `[01 <target>]` to a source slot; `[00 00]`
      clears). Remaining: capture the **Cyclone** applying an L4/R4 + View/Menu remap
      to confirm those *source*-slot addresses on the Cyclone specifically (the G7 slot
      bases may differ) and that it accepts the writes.
- [ ] **Profile-switch → bank sync:** how a `SET-PROFILE` syncs bank `0x01` to a store.
      Unlocks restoring profiles 2–4 (above).
- [ ] **PS4 / Switch-mode input parsing** — the vendor channel is Xbox-only; other
      modes need their own report parser.

---

*Hardware: GameSir Cyclone 2 in Xbox / XInput mode (use the Start / pause buttons). See
[README.md](README.md) for setup and the [CHANGELOG](CHANGELOG.md) for what's shipped.*
