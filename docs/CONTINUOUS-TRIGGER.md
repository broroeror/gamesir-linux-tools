# Cyclone 2 onboard Continuous Trigger

Continuous Trigger turns a mapped button into a toggle: the first tap holds its
output, the second tap releases it. It's stored in the controller's profile, so
it keeps working after Deadband closes. It was added by
[@b1naryblaz3](https://github.com/b1naryblaz3) in #22.

## Use in Deadband

Select a profile (1–4), open **Rebinds**, select the physical source button,
choose its output, then enable **Continuous Trigger → Tap to hold / release**
and press **Save**. For example, **L4 → RT** makes the left back paddle toggle
the right-trigger output. Any target works: a controller button, keyboard key or
mouse button.

It applies to all 19 remappable sources: face buttons, D-pad directions,
shoulders, stick clicks, LT/RT, paddles, View, Menu and Capture. The switch is
disabled while a paddle macro is enabled. Turbo is a separate rapid-fire
feature. Mouse-wheel steps and other instantaneous outputs have no sustained
hold to toggle.

## Format

Each remappable source has a mapping record in the profile bank (1–4): an enable
byte, up to three outputs, then the Continuous Trigger flag, **four bytes after
the enable byte** (`01` on, `00` off). That holds for the 7-byte button records
and for the longer paddle and trigger records, whose layouts otherwise differ.

| Physical source | Flag address |
| --- | --- |
| D-pad Up / Down / Left / Right | `0046` / `004d` / `0054` / `005b` |
| LB / RB / LS / RS | `0062` / `0069` / `0070` / `0077` |
| A / B / X / Y | `007e` / `0085` / `008c` / `0093` |
| View / Menu / Capture | `00a1` / `00a8` / `00af` |
| L4 / R4 paddles | `00b6` / `0155` |
| LT / RT triggers | `01f9` / `0215` |

View, Menu and Capture are also new remap *sources* (records at `009d`, `00a4`,
`00ab`) and *targets* (codes `0e`, `0f`, `10`). The record at `0096` is Home,
which isn't remappable. The write is the ordinary Cyclone register write; a
one-byte L4 enable on profile 1 is:

```text
0f 03 01 00 b6 01 01 [zero padding to 64 bytes]
```

[g7ctl's protocol research](https://github.com/questionablesyntax/g7ctl/blob/main/PROTOCOL.md#continuous-trigger-byte-4-of-a-buttons-record)
independently found the same byte-4 flag on the G7 Pro, with its own hardware
tests; the G7's trigger records and transport differ, so the option is enabled
only for the Cyclone 2 here.

## Verified on hardware

2026-10-06, a Cyclone 2 connected wired (`3537:1053`, firmware 3.52):

1. **Read only, first:** every flag byte read `00` on all four profiles, the
   View/Menu/Capture records were empty as unmapped records are, and existing
   L4/R4 remaps sat exactly where the map puts them.
2. **L4 → RT with Continuous Trigger on**, saved: in a gamepad tester, a tap on
   L4 held RT and a second tap released it.
3. **View → A**, saved: pressing View registered as A.
4. Both set back and saved. A full dump of all four profiles then matched the
   pre-test backup byte for byte.

Not yet checked: behaviour after a reconnect or power cycle, RT as a source,
and keyboard outputs.

## Write safeguards

Deadband reads the flag before enabling the editor, stages changes until Save,
pins them to the session and profile they were read from, and refuses unknown
values. A Save that includes a Continuous Trigger change re-reads every changed
register, saves a recovery file before writing (in
`~/.local/share/deadband/controller-backups/`, importable through Backup &
Restore), compares a read-back, and attempts a verified restore on failure.

## Offline checks

Run `python3 -m unittest continuous_trigger_tests -v` from the repository root.
With PySide6 available, run
`QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python3 continuous_trigger_ui_test.py`.
Both harnesses block hardware access. The first checks the bridge methods, frame
bytes, profile boundaries, unknown values, stale sessions and recovery; the
second exercises the real QML for all 19 sources.
