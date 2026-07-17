# Reverse-engineering findings — per controller

Results from reverse-engineering GameSir controllers on Linux for this project.
Each controller gets a section with its USB identities, config/input protocols, and
an honest Linux support verdict — including the walls we hit, so nobody has to
re-tread them. This is a hobby RE effort; corrections and additions welcome.

> Everything here was found from the Linux side (hidraw/evdev/`usbmon`/libusb) plus
> USB captures of the official Windows apps (**GameSir Connect** for the Cyclone,
> **GameSir Nexus** for the G7 Pro). See [Methodology & tools](#methodology--tools).

## Summary

| Controller | USB IDs (VID 0x3537) | Input on Linux | Config editor on Linux | Firmware flash | Verdict |
|---|---|---|---|---|---|
| **Cyclone 2** | `0575` / `100b` / `1053` | ✅ vendor `0x12` | ✅ full | ✅ (JieLi BR23) | **Fully supported** |
| **G7 Pro** | `1022` (PC/HID) · `100a`/`10ba`/`10bb` (Xbox/GIP) | ✅ evdev | ❌ blocked (see below) | — (different chip) | **Input only** |
| G7 SE *(not owned)* | `1010` | ✅ mainline `xpad` | n/a | — | Reference only |
| G7 Pro 8K *(incoming)* | TBD | TBD | *likely ✅* — uses **Connect** | TBD | To be tested |
| 8BitDo *(future)* | — | — | — | — | Not started |

The shared thread: **GameSir's config protocol is a register read/write protocol on
HID report `0x0F`**, the same across the family — only the framing and the transport
mode differ per model.

---

## GameSir Cyclone 2 — fully supported

**USB identities.** All VID `0x3537`. `0575` = extras/keyboard-macro mode, `100b` =
pure XInput, `1053` = the identity a unit takes on after flashing a firmware-library
image. The controller exposes **two** vendor interfaces when wired (one streams an
empty `0x12` report, the other the live one) — the app probes and picks the live one.

**Config protocol** — GameSir register protocol, **bare** framing on report `0x0F`
(64-byte output report = ID + 63 payload):

| Command | Bytes | Reply |
|---|---|---|
| Heartbeat / keep-alive | `0f f2` | — |
| Get active profile | `0f 0b` | `10 0c …` |
| Read register | `0f 04 <bank> <addrHi> <addrLo> <len>` | `10 05 <bank> <addrHi> <addrLo> <len> <data…>` |
| Write register | `0f 03 <bank> <addrHi> <addrLo> <len> <data…>` | — |
| Rumble test | `0f 20 66 55 <l> <r>` | — |
| Enter firmware loader | `0f 17 55 88` | *(re-enumerates as JieLi loader)* |

Banks `0x01`–`0x04` map to the four profiles and `0x20` holds lighting/dock
settings, but in practice only the **active** profile bank and `0x20` reliably accept
writes — banks `0x02`–`0x04` (the stored, non-active profiles) appear read-only on this
controller. Deadzones, anti-deadzones, stick trajectory, response curves, trigger
tuning (hair-trigger + curve), vibration, poll rate and button remaps are all
register fields. Live **input** is the `0x12` vendor report (sticks, triggers,
buttons incl. the firmware-only L4/R4/M paddles, battery, charging).

**Lighting & keyframes** (register bank `0x20`). The active-slot selector is at
`0x0000` (0–3, and a reliable readback of the M + right-stick gesture). Each slot's
record is 124 bytes at `0x0001 + slot*0x7c`: a 4-byte header `[type, 05, param,
brightness]` then a palette of RGB triplets laid out as repeated **5-triplet frames**,
where frame position maps to a light — `0` = left grip, `1` = right grip, `2` = (no
LED), `3` = profile, `4` = home. A solid per-light colour is `type 0x01` with one
frame tiled across the record. Animated **effect presets** are distinct `type` bytes
(`0x05` Flow, `0x08` Rainbow, `0x02` Pulse, `0x06` Alarm, `0x01`+palette Standoff).
**Custom keyframe animations** reuse the `0x05` engine: the header is `[count, 0x05,
speed, brightness]` — byte 0 is the keyframe **count** (1–8), recovered on readback —
and each keyframe is one 5-triplet frame. **Play/pause** is vendor command
`0f 0d <state> <frame>` (byte 2 = `1` play / `0` pause; byte 3 = the 1-based keyframe
to freeze on).

**Firmware.** The MCU is a **JieLi BR23** (AC635N/AC695N; 1 MB SPI-NOR). `0f 17 55 88`
reboots it into its BR23 UBOOT loader (mass-storage, `4c4a:2342` "BR23UBOOT1.00"), a
JieLi mask-ROM protocol reachable over SCSI. The part is inherently recoverable — the
mask-ROM re-enters UBOOT on a bad image. The one real hazard is the **2.4 GHz dongle**:
it is a *separate* BR23 chip that must never be written with controller firmware. The
two are distinguishable in the loader by the flash-header product-id string at offset
`0x1010` — a controller reads `GS_C2_ADC_DEVICE`, a dongle reads `GS_C2_Dongle`. That
identity is version-independent (observed across fw 3.26/3.46/3.52 and dongle 1.16–1.21).

**Verdict:** full support — input, profiles, lighting + keyframe editor, config
editor, backup/restore, and reversible firmware up/downgrade.

---

## GameSir G7 Pro — input works, config blocked (and why)

The G7 Pro was a deep investigation. Short version: **input works on Linux; the config
editor does not, and can't be made to without host-controller-level work — the reason
is a USB reset-level personality switch that Linux can't trigger.**

> Note: earlier captures/notes in this project labelled "G7" are actually the **G7 Pro**
> in its Xbox mode — the plain G7 is a separate, older model we don't own.

### Two personalities

The G7 Pro is a **tri-mode** pad (Xbox / PC / mobile-wireless, per its product
listings), and it presents a *different USB device* depending on the host:

| Identity | Interface | Where it appears | Config channel |
|---|---|---|---|
| `3537:1022` | HID composite (gamepad + vendor `0xfff0`) | **Linux** only (wired *and* 2.4 GHz) — the ETW trace found no `1022` phase on Windows | present but **inert** |
| `3537:100a` | GIP (Xbox) | Windows, initial | — |
| `3537:10ba` | GIP (Xbox) | Windows, wired, after handshake | **live** (Nexus configures here) |
| `3537:10bb` | GIP (Xbox) | Windows, via 2.4 GHz receiver | live |

### The config protocol (fully reverse-engineered)

In its Xbox/GIP mode the G7 Pro speaks the **same register protocol as the Cyclone**,
wrapped in a sequenced envelope on report `0x0F`, interrupt endpoint `0x02`:

```
0f 00 <seq> 3c | <inner cmd>          inner = 03/04/… exactly as the Cyclone
```

From the Nexus captures we mapped the bank-`0x01` register layout — grip/trigger
vibration, dpad options, report rate, stick resolution, trigger blocks (LT base
`0x00cf`, RT = `+0x1c`), stick blocks (LS base `0x013d`, RS = `+0x20`), and the 7-byte
button-remap slots with their target codes (`A=0x09, B=0x0a, X=0x0b, … LT=0x13,
RT=0x14`). So the protocol is **not** the problem.

### The wall: a reset-level mode fingerprint

The problem is that Linux only ever gets the `1022` "PC/HID" personality, whose vendor
channel (`hidraw14`, output `0x0F`, input `0x10`/`0x12`) is **inert** — it stalls
register reads *and* ignores register writes (verified wired and wireless). The
config-capable GIP mode only appears to Windows. We chased how the pad decides, and
ruled every accessible mechanism out:

- **Not a replayable command.** `1022` *stalls* the vendor requests the Windows
  handshake uses, so the `100a→10ba` sequence can't be driven from `1022`.
- **Not a race window.** `usbmon` of a Linux replug shows `1022` returned at the very
  first descriptor (address 0) — no transient `100a`.
- **Not the enumeration scheme.** Toggling `usbcore old_scheme_first` had no effect
  (Linux already reads the full 64-byte device descriptor first, like Windows).
- **Not the Microsoft OS descriptor.** The pad *does* carry a `0xEE` MS-OS string
  descriptor (`MSFT100`, vendor code `0x90`) — a classic mode-switch fingerprint — but
  an **ETW trace** (which captures the address-0 window USBPcap can't) proved it's a
  red herring: on Windows the pad is `3537:100a` **from its first descriptor**, with no
  `1022` phase and **no `0xEE` request anywhere in the trace**.
- **Not persistent state.** Linux always re-gets `1022`, so it's re-decided each plug-in.

**Conclusion:** the Xbox-vs-PC choice is made *below the descriptor layer* — at the USB
bus-reset/electrical level, based purely on which host controller performs the reset.
Nothing in Linux software (userspace or a kernel quirk) can key on it. Only a hardware
USB analyzer could observe the difference, and a "fix" would be host-controller/firmware
level — out of scope. **This is a genuine, exhaustively-characterized wall.**

### What works anyway

Input is fully functional over evdev (sticks, buttons, dpad, triggers; the L4/R4/L5/R5
paddles are firmware-only and need the vendor channel, so they don't surface). And
because the G7 Pro stores **profiles on the device** (Nexus writes whole profile banks
— seen in the captures), config set in Nexus on Windows should carry over to Linux,
since the firmware applies the active profile before it emits HID reports. *(That's how
on-device profiles work; we haven't specifically A/B-tested a Windows-set change showing
up on Linux.)* You just can't edit it from Linux. No RGB on this model (confirmed by the
owner), so there's no lighting gap.

---

## GameSir G7 SE — reference only (not owned; from mainline `xpad`)

Listed in mainline Linux `xpad` as `3537:1010`, `XTYPE_XBOXONE` (added in kernel 6.14)
— alongside GameSir T4 Kaleid `1004` and Nova 2 Lite `100f` (both `XTYPE_XBOX360`).
Being an Xbox-One entry, it presents a GIP identity that `xpad`/`xone` bind directly.
**Whether it also has a PC/HID mode like the tri-mode Pro is unknown to us** — we don't
own one; this section is reference, not a tested finding. Source:
[`drivers/input/joystick/xpad.c`](https://github.com/torvalds/linux/blob/master/drivers/input/joystick/xpad.c).

---

## To be tested

- **GameSir G7 Pro 8K (PC edition).** Uses **GameSir Connect**, not Nexus — the same
  app that drives the Cyclone with the register protocol we already own. As a
  PC-specific (non-Xbox-licensed) variant it likely skips the Xbox-mode enumeration
  switch entirely, so its vendor channel may be **live on Linux out of the box**. The
  most promising untested target. *(Ordered — findings to be added here.)*
- **8BitDo controllers.** Planned; not started.

---

## Architecture — the Linux app

How the control app is built (the *software* design; the wire protocol is per
controller above). One background thread owns the USB connection; the GUI never
touches `hidraw` directly. They meet through a shared state dict and a thread-safe
command channel:

```
        USB  (hidraw, vendor report 0x0F)
          │
          ▼
   gamesir_reader ──fills──▶ gs_state.state ──reads──▶ GUI (gamesir_qt)
   (connect/read loop)        (shared dict)                    │
          ▲                                                    │
          └──────────── gamesir_control ◀──────────────────────┘
                    (send_cmd / write_reg, thread-safe)
```

- **`gamesir_reader`** — the background loop: finds the controller, keeps it open,
  sustains the heartbeat, polls profile + lighting, parses the `0x12` stream into
  `state`, and survives unplugs, mode switches, and hidraw node renumbering.
- **`gs_state.state`** — a dependency-free dict, the single source of truth the GUI
  renders. The reader writes it; the GUI reads it each frame.
- **`gamesir_control`** — the only writer to the device. One hid handle is shared
  across threads behind a lock; every command goes through it, and the handle is
  **rebound on each reconnect**, so nothing caches it.
- **The GUI** (`gamesir_qt`, Qt/QML) is pure view.

**Register reads are asynchronous.** The reader owns the handle, so callers **queue**
reads (`request_regs`); the reader pumps them one-in-flight, resending on timeout (the
controller drops back-to-back commands), and stores replies callers **poll**
(`reg_result`). A full backup snapshot is ~180 sequential reads — hence the few
seconds it takes.

**Sessions & generations.** Every (re)bind bumps a **generation** counter; a
multi-step op (config Apply, backup restore) captures it once and passes it into each
write, so a mid-operation controller switch makes the remaining writes **refuse**
rather than land on the wrong unit.

**One recognized model at a time.** `controller_profile.py` holds a `ControllerProfile`
per model (register map, write framing, input style, USB product ids) and tracks the
**active** one by USB product id. `gamesir_control` refuses state-changing writes to an
**unrecognized** device — the map falls back to the Cyclone's, and firing
Cyclone-framed writes at an unknown device could corrupt it. One guard behind every
write path, and the seam that makes adding controllers an extension, not a rewrite.

**Domains:** `gamesir_led` (bank `0x20` lighting; `gamesir_kf_cache` keeps exact
keyframe colours for perfect round-trips), `gamesir_config` (per-profile register
map), `gamesir_backup` (JSON export/restore, validated + write-verify-retry),
`gs_common` (vendor-interface discovery + the `bcdDevice` firmware-version read).

---

## Methodology & tools

**Capture.**
- **USBPcap** (Windows / Wireshark) — the workhorse for the official-app config
  traffic. Caveat: it can't see the address-0 enumeration (it attaches after the device
  is addressed).
- **`usbmon`** (Linux) — the Linux-side enumeration, including address 0.
- **ETW / `logman`** (Windows, `USBXHCI FullDataBusTrace`, exported via `tracerpt` to
  XML) — the only software tool that captures the pre-address enumeration; this is what
  settled the G7 Pro question.

**Analysis.** Linux-side decoders and read-only probes were written to unwrap the
Xbox-mode envelope, decode register writes out of the captures, and poke the `1022`
vendor channel. Each mode-switch hypothesis above (replayable command, race window,
enumeration scheme, MS-OS descriptor, unconfigured window) was checked with a small,
non-destructive experiment and ruled out — the record of those negative results is the
point of this document.

**Decoders & probes (this repo).** All under `research/`, run from the repo root,
non-destructive unless noted:

- **Register / config:** `gamesir_regdump.py` (dump + auto-diff a register range),
  `gamesir_regread.py` (single register), `gamesir_regwrite_test.py`
  (read-modify-readback-restore write validator), `gamesir_profile_axis.py`
  (profile → bank probe), `gamesir_verify.py` (post-restore verifier).
- **Capture analysis:** `gamesir_parse_capture.py` (decode a USBPcap `.pcapng` into
  vendor commands; `--writes` filters to register writes), `gamesir_g7_parse.py`
  (the same for the G7's enveloped traffic).
- **Input / mouse-mode:** `gamesir_input_diag.py` (grab evdev nodes one at a time to
  find which one the compositor reads for the cursor), `gamesir_input_map.py` (raw
  input → evdev codes).
- **G7 Pro mode-switch:** `gamesir_g7pro_probe.py` (read-only vendor-channel probe)
  plus the `g7pro_msos_*` / `g7pro_modeswitch` / `g7pro_write_test` experiments that
  ruled out each mode-switch hypothesis above.

The register/config protocol is normal controller configuration, not firmware; these
tools never touch the bootloader.
