# GameSir Tarantula Pro (original, "T3Pro") on Linux

The original Tarantula Pro (2024, firmware 2.06) is not the Tarantula Pro 8K.
Its configuration protocol is GameSir's **SAPJoy** command set, which the
official app drives through `sapjoyuniapis_x86_v1.0.16.dll`. That is a
different wire format from the Cyclone/8K register protocol.

Everything here was decoded on Linux:
- GameSir Connect 1.17.5 ran under Proton with `PROTON_ENABLE_HIDRAW=1`, and
  `strace -P /dev/hidrawN` recorded the dongle traffic.
- The SDK header and struct definitions bundled in the app's `main.js` gave the
  field meanings.
- Every write below was replayed from Linux and read back on a real pad.

## Identities

| USB id | What | Notes |
|---|---|---|
| `3537:103e` | "GameSir-Dongle", pad in XInput mode | iface 0 XInput (xpad), iface 1 HID kbd/mouse/consumer **+ vendor page `0xFFA0`** |
| `054c:09cc` | DS4 mode (dongle or cable) | hid-playstation; gyro works natively, no config channel |
| `057e:2009` | Switch mode, probed first on plug | often fails enumeration and moves on |
| `3537:1050` | wired config identity named by the app | not observed yet |

## Framing (vendor collection, page 0xFFA0)

```
OUT report 0x07 (32 bytes): 07 LEN GRP OP payload...   LEN = 3 + len(payload)
IN  report 0x06 (64 bytes): 06 LEN GRP OP payload...   replies echo GRP/OP
```
OP is `01` set, `02` get, `03` set (indexed) and `04` get (indexed).
`08 03` saves the active profile to flash. Most sets return `06 04 GRP OP 00`.

## Commands seen from the official app (the only ones the tool sends)

| GRP OP | Name | Payload |
|---|---|---|
| 0a 01 | GetDeviceInfo | → `id, fw_hi, fw_lo, mac[6], battery` |
| 0a 02 | SetGamepadStateReport | `mode` (0 off, 1 original, 2 mapped) |
| 0a 04 | SetVibrateTest | `left, right, 0, 0`. Motors take **0-255** |
| 06 01 / 06 02 | Set/GetVibrateLevel | `left%, right%, 0, 0, 0, 0` (0-100) |
| 05 01 / 05 02 | Set/GetKeyMapping | get: `page, key`; body below |
| 01 01 / 01 02 | Set/GetMacroStep | get: `key, index`; body below |
| 07 01 / 07 02 | Set/GetLightParam | `brightness, speed, mode` |
| 07 03 / 07 04 | Set/GetLightColor | `zone, (h,s,v) x4`: h 0-255, s/v 0-100 |
| 09 01 / 09 02 | Set/GetDPadParam | `type, mode, layout, smartStartStop, fastTrigger, macroSwitch` |
| 04 01 / 04 02 | Set/GetMotionSenseCurve | |
| 04 03 / 04 04 | Set/GetMotionSenseMapping | `angle, range, mode, type, shootingMode, key, trigger, sensX, sensY, ...` |
| 02 02 / 02 04 | GetStickMapping / GetStickCurve | |
| 03 02 | GetTriggerParam | |
| 08 03 | SaveConfigPage | |

Never send: the app's quick-update path (`setISPMode`, which puts the dongle
in ISP mode) or anything not in this table.

### Lights
- Modes: 0 off, 1 solid, 2 breathing, 3 phantom, 4 streamer, 5 radar.
- Zones: `00` = Home, `04` = bar/panel (visible in solid mode; the animated
  modes draw their own colours there), `05` = A/B/X/Y (one segment each),
  `06` = presumably the swapped-layout (BAYX) set.

### Key mapping body (16 bytes)
`page, trigger, colour[4], key, toggle, turboMode, turboTimes, mappingType, count, codes[4]`.
`mappingType` 0 = Vacant, 1 = gamepad. Key ids follow `SAPJoyUniKey`:
B 0, A 1, Y 2, X 3, LB 4, LT 5, L3 6, RB 7, RT 8, R3 9, View 10, Menu 11, D-pad 12-15,
stick directions 16-31, gyro 32-35, L4 36, R4 37, T1-T3 38-40, C1-C4 41-44, Camera 45.

### Macros
- Only L4/R4/T1-T3/C1-C4 take a macro, up to 12 steps.
- A key plays its macro only when its mapping is **Vacant**.
- To write one: set the mapping Vacant, send a Clear step (`key, 0xff, 0...`),
  then steps `0..n`. Each step is
  `key, index, trigger(1 oneshot / 2 hold), loop, loopTime_hi, loopTime_lo, 1, 1, button, 0, 0, 0, start_hi, start_lo, end_hi, end_lo`.
- Times are **milliseconds** despite the SDK's "In10MS" names. Checked on
  hardware: 0-300 / 900-1200 played A 300 ms, a 600 ms gap, then B 300 ms.
- `macroSwitch` in the D-pad param is the **on-pad macro record mode**, not
  "enable". Leave it 0.

### Live state (after `0a 02 01|02`)
`06 1a 0a 03` arrives at about 76 Hz. Offsets count from byte 4 of the report:

| Offset | Content |
|---|---|
| 0-3 | sticks |
| 4-5 | analog triggers |
| 6 | B A Y X LB LT L3 RB |
| 7 | RT R3 View Menu Left Right Up Down |
| 8 | Home Camera M |
| 9 | L4 R4 T1 T2 T3 C1 C2 C3 |
| 10 | bit 0 = C4 |
| 11-16 | accel, big-endian int16 x3, about 4096/g |
| 17-22 | gyro, big-endian int16 x3, about 13.4 LSB per deg/s |
| 23 on | live LED colours |

Pad frame: x right, y toward the player, z up.

## Tools
- `tools/t3pro.py`: `info`, `backup`, `light`, `color`, `macro`, `vibration`,
  `rumble`. Every write is read back and compared.
- `tools/t3pro_bridge.py`: turns the mapped state into a virtual DualShock 4 via
  `/dev/uhid`. hid-playstation and Steam accept it, so Steam Input gets the
  gyro, and DS4 rumble is forwarded to the pad. It grabs the real XInput node.
- `packaging/t3pro/`: a udev rule that hides the raw XInput pad and starts the
  per-user `t3pro-bridge.service` when the dongle appears.
- `tools/t3pro_imu_cal.py`: a guided axis, sign and scale check.
