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
| **G7 Pro** | `109b` (wired config) · `109c` (dongle config) · `100a` (transition) · `1022` (native/GIP) | ✅ evdev or claimed USB telemetry | ✅ four profiles + core/extras | — (different chip) | **Supported on 109b/109c** |
| G7 SE *(not owned)* | `1010` | ✅ mainline `xpad` | n/a | — | Reference only |
| **G7 Pro 8K PC** | `10c5`–`10c8` edition pairs | ✅ vendor `0x12` | ✅ full incl. motion/macros/lights | ❌ | **Fully supported** |
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

## GameSir G7 Pro — configuration over `3537:109b` / `3537:109c`

The earlier “input only” conclusion was based on the controller's `3537:1022`
native/GIP identity. Holding **MENU (START)+SHARE** together leaves that mode. The
controller may first enumerate as transitional HID identity `3537:100a`; Deadband
then sends the official-app `gamesirapp` handshake as five two-character chunks,
with a flush between chunks, and waits on the same physical USB port for it to
reappear. The configuration-ready result is `3537:109b` when wired or `3537:109c`
through the dongle.

On both ready identities interface 0 is vendor class (`0xff`) with interrupt OUT
`0x02` and IN `0x82`. Linux binds `xpad` to that interface, so configuration
requires a temporary native libusb claim: Deadband detaches `xpad`, configures the
controller, and reattaches it on release. The transport binds the system C runtime
directly and uses no Python USB package. The controller therefore cannot be used by
a game while Deadband owns the interface; the UI makes this state explicit. A
20-byte standard XInput stream is rejected as the wrong configuration channel
instead of being displayed as zeroed battery and controls.

Packets are 64 bytes: `0f 00 <seq> <command> ...`. Heartbeat is command `02`,
writes use `3c`, and chunked reads use `05 04 <category> <offsetHi> <offsetLo>
<length>`. Replies and the unprompted input/IMU/battery stream share report `0x10`
and are distinguished by their echoed marker. Each default profile is a 480-byte
category (`01`–`04`); dock configuration is global category `20`.

Deadband exposes all 21 default-layer remap sources, stick/trigger deadzones and
curves, trajectory, report rate, stick resolution/inversion/sensitivity, four
vibration motors plus Force/Sync flags, D-pad swap/diagonal lock, and dock power/
brightness. Long-form deadzone and D-pad writes carry neighbouring register bytes,
so the app reads and replays a fresh suffix before every such write rather than
using capture-time constants. Schema-4 backups store only these documented fields.

Not yet exposed: the shared Shift layer, per-button Continuous Trigger, advanced
directional/mouse stick output, G7 motion configuration, Bluetooth, and the native
`1022` protocol. Protocol mapping was cross-checked against the Apache-licensed
`pyg7` research in [questionablesyntax/g7ctl](https://github.com/questionablesyntax/g7ctl).

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
   reader ──────fills──▶ gs_state.state ──reads──▶ GUI (deadband)
   (connect/read loop)     (shared dict)                  │
          ▲                                                │
          └────── vendors.gamesir.control ◀───────────────┘
                    (send_cmd / write_reg, thread-safe)
```

- **`reader`** — the background loop: finds the controller, keeps it open,
  sustains the heartbeat, polls profile + lighting, parses the `0x12` stream into
  `state`, and survives unplugs, mode switches, and hidraw node renumbering.
- **`gs_state.state`** — a dependency-free dict, the single source of truth the GUI
  renders. The reader writes it; the GUI reads it each frame.
- **`vendors.gamesir.control`** — the only writer to the device. One hid handle is shared
  across threads behind a lock; every command goes through it, and the handle is
  **rebound on each reconnect**, so nothing caches it.
- **The GUI** (`deadband`, Qt/QML) is pure view.

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
**active** one by USB product id. `vendors.gamesir.control` refuses state-changing writes to an
**unrecognized** device — the map falls back to the Cyclone's, and firing
Cyclone-framed writes at an unknown device could corrupt it. One guard behind every
write path, and the seam that makes adding controllers an extension, not a rewrite.

**Layout.** The core is vendor-neutral and lives at the root — `bridge`, `reader`,
`backup`, `controller_profile`, `gs_state`, `gs_common` (vendor-interface discovery
+ the `bcdDevice` firmware read), plus `kwin`/`mousegrab` (desktop integration, no
controller content) and `kf_cache`. Everything that speaks a manufacturer's protocol
sits under `vendors/<vendor>/`, so adding a maker is a new sibling package rather than
edits to the core:

```
vendors/gamesir/
    control  config  enhanced  motion  macro   — shared across GameSir models;
    flash                                        per-model differences are DATA,
                                                 carried by ControllerProfile
    models/cyclone2/  led  led_factory  factory  — keyframe RGB + captured baselines
    models/g7_8k/     led                        — bank-0x20 home ring
```

Only what genuinely differs per model gets a `models/` entry — in practice that's
lighting and captured factory images; addresses and capabilities are profile data.

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
Xbox-mode envelope, decode register writes out of the captures, and distinguish the
`1022`, `100a`, `109b`, and `109c` identities. Comparing official-app traffic
identified the replayable `gamesirapp` transition handshake used at `100a`; the
physical MENU (START)+SHARE combination is still required to leave `1022`.

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
- **G7 Pro identity/transition:** `gamesir_g7pro_probe.py` (read-only vendor-channel
  probe) plus the `g7pro_msos_*` / `g7pro_modeswitch` / `g7pro_write_test`
  experiments used to separate physical mode switching from the `100a` software
  handshake.

The register/config protocol is normal controller configuration, not firmware; these
tools never touch the bootloader.
