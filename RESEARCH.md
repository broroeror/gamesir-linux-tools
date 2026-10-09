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
| **G7 Pro** *(Shadow Ember, Amazon)* | `109b` (wired config) · `109c` (dongle config) · `10ba` / `10bb` (Amazon wired / dongle config) · `100a` (transition) · `1022` (native/GIP) · `1003` / `1004` (White Trimode wired / dock; 1004 shared with the T4 Kaleid) · `105e` (recognised, detect-only) | ✅ evdev or claimed USB telemetry | ✅ four profiles + core/extras | **Writes on 109b/109c/10ba/10bb/1003/1004** — 109b/109c contributed and verified by [@brcly](https://github.com/brcly); 10ba/10bb write round-trip verified on my own pad; 1003/1004 confirmed by an owner (#9) |
| **Kaleid** *(Xbox-licensed)* | `1012` (Xbox/GIP, configurable) · `1082` (DirectInput) · `1086` (XInput) — cycled with `M + Xbox` | ✅ mainline `xpad` (matches by interface class, no PID quirk) | ✅ lighting only — full keyframe editor; profile banks read-confirmed, not written | **Supported for lighting**, write round-trip verified by @bloodrizer on their pad |
| G7 SE *(not owned)* | `1010` | ✅ mainline `xpad` | n/a | Reference only |
| **G7 Pro 8K PC** | `10c5`–`10c8` + `1032`/`1033` (Royal2) edition pairs | ✅ vendor `0x12` | ✅ full incl. motion/macros/lights | **Fully supported** |
| **Tarantula Pro 8K** | `103d` (PC/XBOX mode) · `103c` (auto-detected non-PC mode, no config) | ✅ vendor `0x12` | ✅ rebinds (9 extras), macros, sticks, triggers, motion, poll rate — no lighting yet | **Supported**, write round-trip verified on my own pad |
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
native/GIP identity. Holding **SHARE + MENU** together leaves that mode and exposes a configuration identity — confirmed on a fw 2.36 Amazon-edition pad. It is also what upstream g7ctl documents as the only recovery for a wedged read path, and it **erases every non-native binding on the active profile and the Shift layer**, so it is not free. GameSir's manual separately documents VIEW + MENU held 2s as an XInput/Switch mode cycle; that did *not* reach a configuration identity on the pad tested here. The
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

## GameSir Tarantula Pro 8K — supported in PC mode (`3537:103d`)

**✅ Resolved 2026-10-02.** The "dead channel" below was a property of the
`103c` identity, not of the pad. The Tarantula auto-detects its host (GameSir's
manual); Windows put it in **PC/XBOX mode, `3537:103d`**, where it speaks the
ordinary family protocol on its HID interface — read `0f 04`, write `0f 03`,
profile `0f 07`/`0f 0b`, firmware `0f 09`. The pad kept that mode when moved back
to Linux, and every command answered there.

Its register map is **the 8K's plus five more `0xa9`-byte button blocks** (nine
programmable buttons: L4 R4 C1 C2 C3 C4 T1 T2 T3), so everything after the blocks
sits `5 × 0xa9 = 0x34d` higher. Decoded from 18 Windows USB captures of GameSir
Connect v1.16.7 (kept privately with the other raw captures):

| What | Where / encoding |
|---|---|
| Profiles | banks 1–4 (the manual's four configurations); a bank 5 exists, role unknown |
| Poll rate | `0x002e`, codes 0–5 = 250 / 500 / 1000 / 2000 / 4000 / 8000 Hz — **the pad re-enumerates on change** |
| Standard remaps | the Cyclone's slots (A `0x007a`), `[enable, target]` |
| Programmable-button blocks | L4 `0x00b2`, R4 `0x015b`, C1 `0x0204`, C2 `0x02ad`, C3 `0x0356`, C4 `0x03ff`, T1 `0x04a8`, T2 `0x0551`, T3 `0x05fa` |
| Block layout | +0 remap enable · +1…+4 target(s) ("multiple" fills +2 onward) · +5 macro enable · +6/+7 unknown 16-bit · +8 step count · +9… steps `[target, hold BE16, delay BE16]` × 32 |
| Sticks / triggers / motion | the 8K's blocks + `0x34d` (LS deadzone `0x06e4`, motion activation `0x0729`) |
| Lighting (global, bank `0x20`) | mode `0x0000`; logo hue/sat/brightness around `0x0011`–`0x0012` — partly mapped |

Target codes are the family's (D-pad `01`–`04`, LB/RB `05`/`06`, LS/RS `07`/`08`,
A/B/X/Y `09`–`0c`, LT/RT `13`/`14`, none `ff`, plus the shared keyboard and mouse
tables), with **View `0e`, Menu `0f`, Screenshot `10` and Shift layer `e7`** added.

GameSir Connect's stick macros are **recorded by the pad**
(`0f 16 11 01` start / `02` stop, read back with opcode `0f 10`), quantised to
full-strength directions: left stick up `0x15`, down `0x16`, left `0x17`,
up-left `0x2c`, up-right `0x2d` (right is predicted `0x18`). A partial push is
stored as the full direction — there is no magnitude in the step format.

**Verified on the project's own pad (firmware 2.42), through the app:** a read of
every field matching a raw dump; then remaps (A → B, C1 → X), an L4 macro, a stick
deadzone save, a poll-rate change (the pad re-enumerates and Deadband reconnects),
and the gyro driving the left stick — each confirmed in an external gamepad
tester or by the app's read-back. Restored afterwards: a full dump showed **zero
setting differences** from the pre-test backup (only the stick curve tables,
which the pad recomputes itself, moved).

Not yet: lighting (top-button modes + the logo's hue/saturation/brightness live in
bank `0x20` and are only partly mapped), and the pad's fifth bank (possibly the
Shift layer).

### 2026-09-30 notes — the `103c` mode (still accurate for that mode)

Measured live on 2026-09-30 by reading report descriptors and a 20-second
passive capture. **Nothing has been written to this controller.** Recording it
here because an earlier session derived most of this and left no trace, so it
had to be done twice.

**Two HID interfaces, both 64-byte, both on `usbhid`.** No mode switch exists
on this pad — it is PC-only — so the "put it in Xbox mode" step that unlocks
the Cyclone's vendor channel has no equivalent here. Do not go looking for one.

| iface | node | collections | live? |
|---|---|---|---|
| 0 | `hidraw15` | Gamepad in `0x01`; LED-page out `0x02`; **vendor `0xfff0`**: out `0xa2` / in `0x43`, 36 bytes | `0x01` streams; `0x43` never seen |
| 1 | `hidraw16` | Consumer `0x02`; Keyboard `0x03`; Mouse `0x09`; **vendor `0xfff0`**: out `0x0f` / in `0x10`, `0x12`, 63 bytes | `0x03` seen; `0x10`/`0x12` never seen |

**The family channel is declared and DEAD — proven, not assumed.** Interface 1
advertises exactly the Cyclone's command channel: `0x0f` out, `0x10` and `0x12`
in, 63-byte payloads. It answers nothing.

Getting that to mean anything took a control, and the first two attempts had
none. A sweep of 16 documented Cyclone registers came back 0/16 on the
Tarantula — but 0/16 on the Cyclone too, because the Cyclone was asleep, and a
sleeping family device streams all-zero `0x12` frames and answers no commands.
A silent result from a run where the *known-good* device is also silent says
nothing about the unknown one.

The run that settled it had `3537:1053` awake in the same sweep, answering
15/16 and then 30/30 on a wider pass. Same tool, same frames, same moment:

| device | answered |
|---|---|
| `3537:1053` (XInput mode) | **30/30** |
| `3537:103c` Tarantula 8K | **0/30** |
| `3537:0575` Cyclone (asleep) | 0/30 — not a valid control |

So the Tarantula's vendor page is a descriptor entry its firmware does not
service. **Configuration is not reachable over this channel.**

⚠️ Any future "device X does not answer" result is meaningless unless a
known-good device answered IN THE SAME RUN. Check the control first.

**Input does not arrive on the family channel.** It comes over the ordinary
gamepad report `0x01` on interface 0:

```
01 BB BB HH LX LY RX RY LT RT      BB = 15 button bits, HH = hat (0x0f neutral)
01 00 00 0f 80 80 80 80 00 00      neutral
```

So the Cyclone's `enhanced.py` (`0x12`) input path does not apply to this pad
at all; it reads like a plain HID gamepad.

**One button emits a keyboard key.** Report `0x03` on interface 1 fired with
keycode `0x46` (HID Keyboard PrintScreen) in byte 3 — an extra/function button
shipped bound to a key, in the same spirit as the Cyclone's M button.

**evdev uses the SEQUENTIAL button layout.** It advertises `BTN_C` and all 15
codes `0x130`–`0x13e` contiguously, so the kernel numbered its buttons straight
through and every name shifts (see the `_key_map` note in `reader.py`). Button
identities must be measured by pressing them, not assumed from the order.

**What would unblock configuration.** The `0x0f` channel is now ruled out. Two
routes remain:

1. **The `0xa2` / `0x43` channel on interface 0** (36-byte reports) — the one
   the descriptor makes look purpose-built, and the only vendor channel not yet
   tried. Not attempted here because probing it means sending an unknown opcode
   to a working controller: on the family protocol `0x04` is "read register",
   but nothing guarantees it means that on a different channel, and a wrong
   guess could write. Worth doing only with a capture to copy frames from, or
   on hardware we are willing to risk.
2. **A Windows USB capture of GameSir's own app** configuring this pad. Slower,
   but it is the route that cannot fail, and it answers the framing question for
   both channels at once. See "Methodology & tools".

---

### `10ba` / `10bb` (Amazon edition) — write round-trip verified 2026-09-30

On this project's own pad, firmware 2.3.6, wired. `10ba` enumerates with two
`ff/47/d0` (Xbox GIP) interfaces and no hidraw node; interface 0 is bound to
`xpad` until Deadband claims it (`usbfs`) and returns to `xpad` on release.

1. **Session.** 1,709 vendor telemetry frames, zero standard XInput frames, so
   the "wrong kind of identity" guard never fired. Active profile (1) and
   firmware answered from the pad.
2. **Read.** The app's own export read 46/46 chunks: all four profile banks plus
   the dock block, decoding to factory defaults (vibration 75/75, stick
   deadzones 10–100, trigger 5–95, every remap unmapped).
3. **UI.** Profile bar rendered four profiles with the active dot on profile 1.
4. **Write, verified from outside the app.** L4 → A on profile 1 through the GUI,
   Apply, Release to games. With Deadband closed the kernel's `xpad` node emitted
   `BTN_SOUTH` for L4; before the write it emitted nothing.
5. **Unbind.** L4 back to unmapped, Apply. A full-pad diff against the pre-write
   backup showed **zero** differences, so the cycle touched nothing but L4.

The same session confirmed the X/Y mapping on hardware: `xpad` emits `0x133` for
the physical X button and `0x134` for Y, as the `_KEY_TO_STATE` fix assumes.

⚠️ **Harness trap.** `control.clear_device()` drops every stored read result by
design, so none leak into a later session. A test script that prints results
*after* its session's `finally: clear_device()` reports 0/N answered for reads
that all succeeded. That cost one false alarm here.

**Dongle: `10bb`.** Over the wireless dongle the pad enumerates as `1022` (dongle
firmware 1.00, two plain HID interfaces on `usbhid`) — the same identity issues
#10 and #17 reported. Holding **SHARE + MENU** re-enumerates the dongle as
**`3537:10bb`** (firmware 1.46): `10ba + 1`, the same wired/dongle pairing as
Shadow Ember's `109b`/`109c`, with interfaces identical to `10ba`. Same test
sequence: the export read 46/46 chunks and matched the wired read with zero
differences, so the dongle relays the pad's own config rather than holding its
own. L4 → A applied over wireless, confirmed in an external browser gamepad
tester with Deadband released; unbound; full-pad diff zero.

---

### 8K macro targets beyond buttons — stick directions exist (2026-10-02)

Found by accident: R5 on the project's own 8K (Nioh, dongle `10c8`) made the
left stick move, in Deadband and in an external browser gamepad tester alike.
Not the gyro — Motion activation was Off on all four profiles. R5's paddle block
on the **active profile (1)** held an enabled macro (profiles 2–4 empty):

```
R5 block @0x2ad, bank 1:  00 00 00 00 00 01 00 00 03 15 00 74 00 70 2d 00 …
                                         ^en      ^n  [tgt hold  delay] …
step 1: target 0x15  hold 116 ms  delay 112 ms
step 2: target 0x2d  hold  96 ms  delay  92 ms
step 3: target 0x15  hold  12 ms  delay   0 ms
```

Neither code is in Deadband's target table (it stops at LT `0x13` / RT `0x14`),
and Deadband has no controller-macro recorder, so the app did not write this —
most likely GameSir's own app, origin unknown. Captured passively from the
kernel's evdev node over four presses, identical each time:

| t | left stick | step |
|---|---|---|
| 0 ms | **full up** (LY −100%) | 1 · `0x15` |
| ~112 ms | **full up + full right** | 2 · `0x2d` |
| ~205 ms | full up | 3 · `0x15` |
| ~214 ms | centred | — |

So **`0x15` = left stick up** and **`0x2d` = left stick up-right**, a single
diagonal code (up stays held right through step 2; the timings match the stored
hold/delay exactly).

**What this settles for #15:** the firmware has stick-direction targets — at
least as macro events. **Still open:** whether remap slots accept them too,
whether any code gives a *partial* deflection (every step here was full), and
the rest of the code space (the other directions, the right stick). A capture of
GameSir's app picking these targets would answer all three at once.

Deadband shows unknown codes as raw hex (`0x15`) and preserves them on save —
editing another step does not rewrite them.

---

## GameSir Kaleid — lighting over Xbox GIP (`3537:1012`)

The Kaleid is Xbox-licensed, and it does **not** answer the GameSir hidraw vendor
protocol every other model here uses. That collection is present on the pad but
vestigial: it accepts reports and never replies. Deadband reaches it the way the
vendor's own app does instead — the same GameSir register protocol (`0x0f` out /
`0x10` in, `0x03` write / `0x04` read / `0x05` reply) tunnelled inside **Xbox GIP**
vendor messages on interface 0, which is GIP class `ff/47/d0`.

Three USB identities, cycled on the pad with **M + Xbox**, and only one is
configurable:

| identity | interfaces | use |
|---|---|---|
| `3537:1012` | GIP `ff/47/d0` ×2 | the only configurable one |
| `3537:1086` | `ff/5d/01` | XInput |
| `3537:1082` | HID ×2 | DirectInput |

Mainline `xpad` matches GameSir pads **by interface class, not product id**, so input
needs no quirk — but it binds interface 0, and configuration therefore needs the same
temporary libusb claim with `xpad` detached that the G7 Pro uses. The GIP framing is
`[0x0f, options, sequence, 0x3c]` then the register command; `options` must be `0x00`
and the sequence must be 1..255, as GIP reserves 0. Channel `0x3c` is verified for
both reads and writes. Note the GIP body carries only **55** payload bytes where
hidraw carries 56, which is what `ControllerProfile.read_chunk` exists for.

Releasing the claim does not change the identity — the pad stays at `1012` and
`xpad` re-binds, measured still `1012` 90 seconds after a release with the pad
untouched — so configuring costs the owner nothing. Deliberately not implemented: the
GIP host handshake (announce → power-on), which is the likely reason GIP `STATUS` and
`SERIAL_NUMBER` stay silent. Also never sent: GIP command `0x0c` (FIRMWARE).

**Lighting is the Cyclone 2's engine, byte for byte.** Bank `0x20`, same selector at
`0x0000`, same five 124-byte records at `0x0001 + slot*0x7c`, same
`[count, 0x05, speed, brightness]` header and 8×5-triplet palette. Proven rather than
assumed: the pad's own stored records hold palettes **identical** to this project's
captured Cyclone presets, agreeing on keyframe count and speed too. So
`lighting_style='cyclone_keyframe'` drives it unchanged, and the whole keyframe editor
came for free. Confirmed on hardware: colours are plain RGB, the `count` byte is
honoured (a 1-frame record renders static), and speed is inverted exactly as on the
Cyclone — device `1` ≈ 4 frames/s, device `20` ≈ one frame per 8 seconds.

**Its light map is not the Cyclone's**, which is why `lighting_lights` is now a
per-model profile field. Measured one zone at a time with the pad released:

| frame position | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| Cyclone 2 | left grip | right grip | *(no LED)* | profile | home |
| Kaleid | left | right | left | *(no LED)* | right |

A lit position floods an **entire side** at 90–100% brightness with only a faint
positional bias, so the Kaleid has two usable lights, each driven by a pair of
positions, and its dead position is 3 where the Cyclone's is 2. Hence a light that
owns several positions, and a Lights page that sizes its zone list off the model.

**⚠ The animation idles out on a quiet claimed interface.** While the interface is
claimed the pad keeps animating only as long as traffic flows; after roughly 15–30
seconds of silence it stops on whatever frame it reached, and it resumes when the
claim drops. Writes have nothing to do with it — measured silent/polled × with/without
a write. The session's once-a-second poll of the active slot is therefore
**load-bearing** (`kaleid.KEEPALIVE_SECS` against `kaleid.ANIM_IDLE_TIMEOUT`), not
just how the editor follows the slot, and two tests guard the margin.

**⚠ Vendor command `0x07` is destructive here.** On the Cyclone it selects a profile;
on the Kaleid it writes profile-bank offset `0x3f`, the profile→lighting link, and
collapses the `M + Y/B/A/X` chords so several chords select the same profile. Guarded
centrally by `software_profile_switch=False`, which makes `control.set_profile()` a
no-op for this pad. Recovering it needs the link byte written back per profile.

**Scope is lighting only, deliberately.** The profile banks read cleanly and decode
against the G7 Pro's map (four vibration strengths at the family default of 75, a
stride-7 remap table from `0x42`), but no write to them has ever been confirmed — so
`profile_banks=()`, no analog/remap/vibration addresses, and those tabs are hidden
rather than shown writing into the dark. GIP rumble untried. Input telemetry does
stream on the same channel (sticks rest at `0x80`, so 8-bit axes) but its frame layout
is unmapped, so it is dropped rather than guessed at and the live view stays blank
during a configuration session.

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

- **Zenless Zone Zero (`105e`).** Recognised and named, no write path yet: no
  owner has confirmed config reads back correctly on it. The register map is now
  confirmed on Shadow Ember, Amazon and White Trimode, so it is likely — but an
  edition earns a write path through evidence from a real pad, not resemblance.
- **White Trimode writes.** `1003`/`1004` are enabled on an owner's report that
  every value read back exactly as set on Windows (#9). Nobody has yet watched a
  write land on one the way `10ba` was tested.
- **`3537:1004` in mainline `xpad`.** The White Trimode's dock identity collides
  with xpad's T4 Kaleid entry (`XTYPE_XBOX360`), so the kernel names a docked
  White Trimode "GameSir T4 Kaleid" and drives its GIP interface with the Xbox
  360 protocol — no input in games (#14). The fix belongs in xpad (match on the
  interface class, as its vendor-wide GameSir entries already do); a good
  upstream contribution.
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
physical SHARE + MENU combination is still required to leave `1022`.

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
