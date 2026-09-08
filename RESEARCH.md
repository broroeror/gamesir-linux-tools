# Reverse-engineering findings — per device

Results from reverse-engineering gaming input devices on Linux for this project:
the GameSir controller family, and the Logitech G502 X mouse (a different vendor
and an entirely different protocol). Each device gets a section with its USB
identities, config/input protocols, and an honest Linux support verdict — including the walls we hit, so nobody has to
re-tread them. This is a hobby RE effort; corrections and additions welcome.

> Everything here was found from the Linux side (hidraw/evdev/`usbmon`/libusb) plus
> USB captures of the official Windows apps (**GameSir Connect** for the Cyclone,
> **GameSir Nexus** for the G7 Pro). The G502 X work needed no captures — HID++ 2.0
> is documented enough to probe directly, with Solaar and libratbag as references. See [Methodology & tools](#methodology--tools).

## Summary

| Device | USB IDs | Input on Linux | Config editor on Linux | Verdict |
|---|---|---|---|---|
| **Cyclone 2** *(GameSir, VID 0x3537)* | `0575` / `100b` / `1053` | ✅ vendor `0x12` | ✅ full | **Fully supported** |
| **G7 Pro** *(Shadow Ember)* | `109b` (wired config) · `109c` (dongle config) · `100a` (transition) · `1022` (native/GIP) | ✅ evdev or claimed USB telemetry | ✅ four profiles + core/extras | **Supported on 109b/109c** — contributed and verified by [@brcly](https://github.com/brcly), not on my hardware |
| G7 SE *(not owned)* | `1010` | ✅ mainline `xpad` | n/a | Reference only |
| **G7 Pro 8K PC** | `10c5`–`10c8` edition pairs | ✅ vendor `0x12` | ✅ full incl. motion/macros/lights | **Fully supported** |
| **G502 X LIGHTSPEED** *(Logitech, VID 0x046d)* | `c098` (wired) · `409f` / `c547` (receiver) | ✅ standard HID | ✅ full — profiles, G-Shift, DPI, macros | **Fully supported** |
| 8BitDo *(future)* | — | — | — | Not started |

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

## Logitech G502 X LIGHTSPEED — fully supported

A different vendor and a completely different protocol from the GameSir family:
**HID++ 2.0** over hidraw, rather than a register read/write channel on report
`0x0F`. Settings live in the mouse's own flash, so they persist with the device and
nothing needs to run in the background.

**USB identities:** `046d:c098` (wired) and `046d:409f` (LIGHTSPEED receiver). The
receiver also enumerates as `046d:c547`, its generic-receiver identity.

**Features used:** `0x8100` onboard profiles (the whole config surface), `0x1004`
unified battery, `0x2201` adjustable DPI (for the sensor's real range — this mouse
reports up to 25600, so the range shown isn't a hardcoded guess).

### Memory model

16 sectors of 255 bytes. Sector `0x0000` is the live profile directory; **`0x0100`
is the ROM directory**, listing the out-of-box profiles the mouse shipped with
(`oob_count` says how many — two on this unit, at `0x0101`/`0x0102`). Profiles
occupy sectors 1–5; everything above `profile_count` is the macro region, so this
mouse has **10 macro slots**. All of it is device-reported, not assumed.

Within a profile sector: report rate at byte 0, the active/shift DPI indices at 1–2,
five DPI stages at 3–12, RGB at 13–15, the write counter at 18–19, the primary
button bank at 32, the **G-Shift bank at 96**, the name at **160–207** (UTF-16LE, 24
characters), and a CRC-16/CCITT-FALSE over everything but the trailing two bytes.

Encoding is read-modify-write from the original sector rather than rebuilt from
scratch, so unmodelled regions (power modes, angle snapping, timeouts) survive an
edit. Blanking the whole sector is what wipes G-Shift on other tools.

### Three findings that cost real time

**`memoryWriteEnd` returns error `0x04`, and the write commits anyway.** The
firmware's CRC check is *soft*: it rejects the sector and stores the bytes. Treating
that error as failure is what made macros look impossible for a long time — the fix
is to swallow the `0x04` and prove the write by reading the sector back. Confirmed
independently by `cvuchener/hidpp` and libratbag PR #1850.

**ROM profiles don't carry a CRC that verifies.** Every one of the five RAM profiles
verifies through the same read path; both ROM copies fail. So a factory restore
can't gate on the stored CRC — it validates the *content* (DPI stages in range,
plausible report rate, indices in bounds) and recomputes the CRC for the copy it
writes, which is the one that has to be valid.

**An unnamed profile's name field is `0xFF` filler**, which decodes from UTF-16LE to
U+FFFF — unprintable, but *not empty*. Anything that tests a name for emptiness has
to filter unprintable characters, or the padding survives as tofu boxes and defeats
the caller's fallback label.

### Macros

A small bytecode: `DELAY 0x40`, `KEY_PRESS 0x43` / `KEY_RELEASE 0x44`, `MOUSE_PRESS
0x41` / `MOUSE_RELEASE 0x42`, `MOUSE_WHEEL 0x20`, `CONSUMER 0x45`/`0x46`, `JUMP
0x60`, `END 0xFF`; operand length comes from the opcode's top three bits. A macro
longer than a sector is split at opcode boundaries and JUMP-chained across up to
four sectors.

Flash can't be rewritten in place, so replacing a button's macro writes a new sector
and strands the old one. Reclaiming those is safe only behind a **complete**
reference walk: the scan raises on anything it can't fully decode — an unknown
opcode, a stream running past the sector end — because a silently truncated walk
would classify a live chain's tail as an orphan and blank it. Foreign macros (G HUB's)
can use opcodes this project doesn't model, and a blank sector is a legal instant-END
macro, so an erased sector that something still points at must not be reallocated.

Playback runs slightly slower than recorded. The captured timings are exact; the
mouse's macro engine simply spends a little time per step, and there are roughly four
steps per typed character.

---

## To be tested

- **Other G7 Pro editions.** The editions differ only by USB product id — White
  Trimode (`1003`/`1004`), Zenless Zone Zero (`105d`), and an Amazon edition
  reporting `10ba`. The register map looks common to all of them (upstream `g7ctl`
  keeps its variant table to names and PIDs, branches on the variant nowhere, and
  drives PIDs it has never seen), but nobody here owns one to confirm it, so they're
  recognised and named without a write path. Confirming one would unblock the rest.
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
