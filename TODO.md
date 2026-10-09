# Deadband — TODO / Roadmap

Open bugs, proposed changes, and reverse-engineering questions. **Completed work
moves to the [CHANGELOG](CHANGELOG.md)** (and the full history is in git), so this
stays a forward-looking list. Linked from the [README](README.md). Hobby project —
**fork it and customize it however you like.**

Keep entries short (a date helps). Tick items off (`- [x]`) as they land, then move
them into the CHANGELOG so this file doesn't grow stale.

---

## 🐞 Known bugs / rough edges

- [ ] *(environment, not this app)* **KWin 6.7 logout SIGSEGV** in
      `RenderLoop::activeWindowControlsVrrRefreshRate()` during compositor teardown,
      on multi-output + hybrid NVIDIA/AMD. Workaround: System Settings → Display →
      Adaptive Sync → *Never*. Worth reporting upstream to KDE.

## ✨ Enhancements / proposed changes

- [ ] **Bind the mouse-mode toggle to a controller button** via the controller's
      macro/keybind system (the original stretch goal). No longer blocked on a
      capture — per-paddle gamepad macros ship, so the command format is known.
      What's left is deciding what the pad should send and having the app watch
      for it. *(unblocked 2026-09-06)*
- [x] **Publish the package to the AUR** *(DONE — `deadband-git`, live and updated
      since)*. There is also a community NixOS flake, linked from the README.
- [ ] **Collapse overlapping helper modules** (`gs_common` / `gs_state` vs the
      `gamesir_*` modules) for a leaner runtime surface. *(The RE-script reorg into
      `research/` is already done — see the CHANGELOG.)*
- [ ] **Restore: per-block verify detail.** The write-verify-retry already reports
      pass/fail; could add a "verify only" action or a list of any unconfirmed blocks.
- [x] **8K lighting hue accuracy** *(DONE 2026-07-17 → CHANGELOG)*. Root cause: the ring's
      hue register is **16-bit big-endian** (`[hue_hi, hue_lo, sat, bright]` per quadrant at
      `0x000c/0x0010/0x0014/0x0018`) holding the angle in **degrees 0..359, perfectly linear**
      — there was never a colour-correction curve. We wrote only the low byte, which capped
      the ring at 255° (purple) and left a stale high byte offsetting later edits by 256°.
      Fixed + live-verified (0/300/120/359 all round-trip exact).
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

The project's north-star goals — larger efforts. Hardware on hand: **two Cyclone 2s**,
a **G7 Pro 8K PC**, and a **Logitech G502 X LIGHTSPEED**. The plain **G7 Pro** was
passed on to family before it ever worked, so that support is contributed rather
than mine. *(Full per-device findings in **[RESEARCH.md](RESEARCH.md)**.)*

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
- [x] **Confirm the G7 Pro register map on a second edition.** Done: Amazon
      (`10ba`/`10bb`, round-tripped here) and White Trimode (`1003`/`1004`, owner-
      confirmed on #9). Zenless (`105e`) still recognised without a write path.
- [ ] **Upstream an xpad fix for `3537:1004`.** Its T4 Kaleid table entry
      (`XTYPE_XBOX360`) captures the White Trimode's GIP dock identity, which then
      gets no input (#14).
- [ ] **PS4 / Switch-mode input parsing** — the vendor channel is Xbox-only; other
      modes need their own report parser.
- [ ] **Kaleid: a software profile switch.** The vendor's `0x07` is destructive on
      this pad (it writes the profile banks' `0x3f`, the profile → lighting-record
      link) and `0x06` answers with noise, so selecting a profile stays an on-pad
      chord. Needs a capture of GameSir Nexus against the Windows GIP stack.
- [ ] **Kaleid: write-verify the profile banks.** They read cleanly and decode
      against the G7 Pro's map — four vibration strengths at the family default of
      75, the stride-7 remap table from `0x42` — but nothing there has been written,
      so rebinds/sticks/triggers/vibration stay off. One read/write round-trip on
      the hardware is all that's missing.
- [ ] **Kaleid: the GIP host handshake** (announce → power-on). Not needed for
      claim/release any more — the pad keeps its `1012` identity across a release
      (measured: still `1012` 90s later, untouched), so the owner is asked for
      nothing. Still likely why GIP `STATUS` and `SERIAL_NUMBER` stay silent, and
      it would let the session read battery and firmware.
- [ ] **Kaleid: input telemetry.** Telemetry streams on the same channel (sticks
      rest at `0x80`) but its frame layout is unmapped, so the live view is blank
      during a session. Also untried: GIP rumble, which the pad should accept.
      (The lighting zones are mapped: two lights, each driven by a pair of render
      positions, with a dead position at 3.)

---

*GameSir controllers need Xbox / XInput mode; see [README.md](README.md) for setup
and the [CHANGELOG](CHANGELOG.md) for what's shipped.*
