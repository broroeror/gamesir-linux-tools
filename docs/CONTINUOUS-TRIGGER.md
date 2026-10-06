# Cyclone 2 onboard Continuous Trigger

The Cyclone 2 encoding was traced in **official GameSir Connect 1.14.2**,
obtained from the download link on GameSir's
[Connect software page](https://gamesir.com/pages/gamesir-connect-software).
The installer and app were inspected as archives and text. Neither was run,
and no controller was written during this research.

## Use in Deadband

Select a profile (1–4), open **Rebinds**, select the physical source button,
choose its output, then enable **Continuous Trigger → Tap to hold / release**.
Press **Save**. For example, **L4 → RT** makes the left back paddle toggle the
right-trigger output. Choose a controller button, keyboard key or mouse button
using the existing target picker. It applies to all 19 official remappable sources:
face buttons, D-pad directions, shoulders, stick clicks, LT/RT, paddles, View,
Menu and Capture. It is a per-mapping Advanced option in GameSir Connect.

This edits the controller's profile rather than installing a host remapper.
The intended firmware behavior is tap to hold, second tap to release, including
after Deadband closes. Turbo is a separate rapid-fire feature. Use normal
mappings; the switch is disabled while a paddle macro is enabled.

Software tests pass, but behavior after app closure, reconnection and power
cycling still needs a **physical Cyclone 2 test**. Static inspection establishes
the official encoding; it cannot establish how every firmware revision behaves.
Mouse-wheel steps and other instantaneous outputs do not have a sustained hold.

## Evidence and exact layout

The renderer's English `ToggleOnPress` label names Continuous Trigger. The C2
model selects proxy `gs`. That proxy converts profiles through `qa.fromModel`,
which uses `Ga.parseAppProfileToRawProfile`. The mapping conversion `v` sets
`toggle_en` to 1 or 0 from `key.toggleOnPress`; conversion `f` reads bit 0.

The C2 profile has a 32-byte name, 32-byte basic-settings block, sixteen ordinary
7-byte button records, two 159-byte paddle records, two 28-byte trigger records,
two 32-byte stick records and two 33-byte motion records: 680 bytes total.
The C2 serializer writes `toggle_en` after the three mapped outputs. The flag
is therefore **four bytes after `map_en`**, not after the start of an entire
trigger or paddle block. Those blocks have different prefixes and lengths.

| Physical source | Flag address |
| --- | --- |
| D-pad Up / Down / Left / Right | `0046` / `004d` / `0054` / `005b` |
| LB / RB / LS / RS | `0062` / `0069` / `0070` / `0077` |
| A / B / X / Y | `007e` / `0085` / `008c` / `0093` |
| View / Menu / Capture | `00a1` / `00a8` / `00af` |
| L4 / R4 paddles | `00b6` / `0155` |
| LT / RT triggers | `01f9` / `0215` |

This source list matches the official C2 `CanMappingKeys` list. Home is excluded
there. `Sel`, `Sta` and `Camera` are displayed as View, Menu and Capture. The
official `xa.getKeyMapValue` / `Ua` table resolves their `Fa` enum output codes
to 14, 15 and 16 respectively; those targets are also exposed for Cyclone 2.

Each address is within the selected profile bank (1–4). `gs.writeProfile`
serializes the profile, finds changed bytes, and passes their offset to
`gs.getWriteProfileCommand`. This builds the standard Cyclone register-write
report. A one-byte L4 enable on profile 1 is:

```text
0f 03 01 00 b6 01 01 [zero padding to 64 bytes]
```

Disable changes the last data byte to `00`. No firmware-loader, calibration or
flash-update command is involved. The app writes just that flag byte, preserving
other mapped outputs, Turbo fields, macro data and neighboring analog settings.
These facts are independently implemented; vendor code and firmware are not
distributed in this repository.

### Pinned provenance

Installer: `GameSir Connect Setup 1.14.2.exe` (144,789,120 bytes), from
[GameSir's CDN](https://pc-connect-update.gamesir-cdn.com/1.14.2/GameSir%20Connect%20Setup%201.14.2.exe).

| Item | SHA-256 |
| --- | --- |
| Installer | `687de26fc30a7061e8206992410b0769a2536a03b8c0a13fbc6a726ad0dd825d` |
| `resources/app.asar` | `18dc3ea692be157b8630d6a3437d1c06d9d10e74651e0627ae4df8b8ea7a32e8` |
| `dist/electron/main.js` | `b3b1596b18a177026b9faffa0dba01dfd517dceb79f277c4683bb9b4d2dfd437` |
| `dist/electron/renderer.js` | `deca9fff468dfa4e9ab9aebe724750ebcb2a4df41f885cee292e0f0d48e8694b` |

For inspection, extract `$PLUGINSDIR/app-32.7z` from the installer using an
archive utility, then extract only `resources/app.asar` from that archive.
Do not launch the installer or app. The ASAR's JSON header locates the two text
bundles above. Function names refer to this pinned minified bundle and can
change in another release.

## What the other research establishes

[NaokoAF's gist](https://gist.github.com/NaokoAF/da4c166ed80e569276beee5a57bdeba9)
and its [current InFract notes](https://github.com/NaokoAF/InFract/blob/main/InFract/Drivers/GameSir/Cyclone2Notes.md)
confirm Cyclone reports, addressed register commands and raw paddle inputs.
They do not decode Continuous Trigger. Raw input bypasses mappings, so a raw
paddle indicator alone cannot verify a held mapped output.

[g7ctl's protocol research](https://github.com/questionablesyntax/g7ctl/blob/main/PROTOCOL.md#continuous-trigger-byte-4-of-a-buttons-record)
independently identifies byte 4 of a G7 Pro button record as Continuous Trigger,
with hardware write/read/restore tests. That was a useful lead, but its trigger
records and transport differ. The Cyclone paddle and trigger addresses above
come from its own official app serializer. The UI option is currently enabled
only for Cyclone 2.

## Write safeguards and physical verification

Deadband reads the flag before enabling the editor, stages changes until Save,
pins them to the read device session and profile, and refuses unknown values.
Save freshly reads all changed registers, durably saves a recovery file before
writing, then compares read-back. Failure attempts verified recovery and retains
pending edits. Full controller backups now include these flags; older backups
without them still restore only the fields they contain.

To finish hardware validation, use a spare profile with **L4 → RT**, Turbo and
macros off. Save Continuous Trigger on; check tap/second-tap against the normal
mapped gamepad output. Close Deadband, reconnect and power-cycle, repeating the
check each time. Turn it off and verify normal hold behavior. Repeat with RT as
a source and a keyboard output. Restore the original profile afterward.
Record the controller firmware and wired/dongle transport.

A short off/on/off USBPcap capture from GameSir Connect remains useful as an
independent wire fixture. The [USBPcap guide](https://desowin.org/usbpcap/tour.html)
explains device selection. Limit saved packets to the controller, keep captures
private, and do not change firmware or calibration for this test.

## Offline checks

Run `python3 -m unittest continuous_trigger_tests -v` from the repository root.
With PySide6 available, run `QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python3 continuous_trigger_ui_test.py`. Both harnesses block hardware access.
The first checks the real bridge methods, frame bytes, profile byte boundaries,
unknown values, stale sessions/profiles, durable-backup failures and recovery.
The second exercises the actual QML for all 19 sources, source switching,
Discard, unknown flags and all controller tabs at several window sizes.
