# GameSir G7 SE support

Tested on Linux with USB identity **3537:1010**, firmware descriptor **6.30**
(`bcdDevice=0630`), and Windows GameSir Nexus Legacy 1.5.3.0 packet captures.
Firmware **6.64** (`3537:1069`) is covered in [its own section](#firmware-664-35371069).
Other firmware remains input-only.

## Firmware 6.64 (3537:1069)

Firmware 6.64 has three identities: `10a0` (XInput, first enumeration),
`1069` (Xbox GIP, configurable) and `1082` (DirectInput fallback, input only).
Linux hot-plug ends at `1082`, because the pad picks its mode from how the host
enumerates it. A pad the PC firmware enumerated first stays at `1069`: unplug
it, reboot, plug it in at the boot menu (Dell: F12), then boot Linux. A kernel
quirk for `10a0` is under review upstream
([linux-usb](https://lore.kernel.org/linux-usb/20261002-master-v2-1-24b05d8792b5@gmail.com/)).

On `1069` the startup, GIP authentication and register channel are the 6.30
ones, except that replies carry the pad's own sequence counter. The 421-byte
profile banks follow the **G7 Pro register map**. The editable fields are
listed in `SETTINGS_664` and `REMAP_SLOTS` in `vendors/gamesir/models/g7se/protocol.py`:

| Page | Fields |
|---|---|
| Rebinds | D-pad, LB/RB, LS/RS, A/B/X/Y, View, Menu, LT/RT (2-byte flag + target), L4/R4 (1-byte target); report rate per profile |
| Sticks | deadzone / anti-deadzone, response curve, sensitivity, invert X/Y, trajectory |
| Triggers | deadzone / anti-deadzone, response curve, hair-trigger mode |
| Vibration | grip motors and trigger motors, with test buttons (GIP rumble) |
| Backup & Restore | whole-bank images; restore writes only the fields above |

How each was verified: L4/R4 and the report rate match Nexus 2.5.8 USBPcap
writes byte for byte. Everything else uses the G7 Pro encoding, and every address
in `SETTINGS_664` and `REMAP_SLOTS` was written on bank 3 by
`tools/g7se_write_test_664.py`: left and right copies, each deadzone and
anti-deadzone byte, and all four curve blocks. Each write changed exactly its own
bytes, and the bank was restored byte-exact. That proves storage; the effect on the pad
was checked for front-button remaps and the motors. Factory banks hold zeros in
the trigger curve blocks, so a trigger curve's effect on the pad is untested. On the pad, an app Save of
a front-button remap took effect. Saves of the LT remap and the hair-trigger mode
read back verified. Grip and trigger motors were felt through the test buttons
and `tools/g7se_trigger_rumble_test_664.py`. Stick resolution and the trigger
motors' Force/Sync stay hidden, because their meaning on this pad is unknown.
Factory banks store hair mode `01`, which is shown as Off.

The report rate offers **500 Hz and 1000 Hz** only: Nexus wrote codes `01` and
`02`, and `00` (250 Hz on 6.30) was never captured, so it is neither offered
nor accepted from a backup. With a G7 SE connected, Restore accepts only its own
`g7se-banks` backups; other formats would use the generic path, which has no
rollback.

## Supported behavior

Select the G7 SE in Deadband; the app automatically claims it for configuration.
Select **profile 1, 2 or 3** and edit **L4/R4** on Rebinds, or choose
**250 Hz, 500 Hz or 1000 Hz** in the **Poll rate** dropdown. Then **Save** and
**Release to games**. Three remap profiles match the Nexus UI. Selecting a
profile chooses which bank to edit; it does not switch the controller's active profile. Poll rate applies to the whole controller, regardless
of the profile being edited. Saving it writes the same rate byte to all four
banks, matching Nexus. Bank 4 is not an editable remap profile; only its rate
byte can be written.

Targets: D-pad directions, LB/RB, L3/R3 (shown as LS/RS), A/B/X/Y, View and Menu.
Default clears the remap record. Keyboard, mouse, macros, calibration, stick or
trigger settings, vibration configuration, reset and
general backup import/export are unavailable for this model. Rebinds includes
read-only LT/RT percentages and stick X/Y values, plus the live controller diagram.

Rate and remap edits stay staged until Save. A rate choice counts as one pending
change; Discard restores the displayed original value. Switching the edited
profile discards staged changes, including the controller-wide rate choice.
If valid rate values differ across banks, the dropdown shows **Mixed** and a
new selection makes them consistent. Missing or unknown values disable rate
editing while leaving rear-button remapping available.

Before writing, the app saves the original complete remap records and each
affected bank's original rate byte to its durable recovery directory. It verifies
each write by reading the value back and attempts verified rollback on failure. Edits, reads and
writes are pinned to the selected device, USB session and edited profile.
Disconnects or selection changes stop the operation. Recovery files remain
available if a disconnected controller prevents immediate restoration.

## Transport and startup

The app uses system `libusb-1.0`, interface 0 interrupt endpoints **02/82**.
Selecting the controller temporarily claims the interface; Release and cleanup return it to
`xpad`. Install the included `70-gamesir.rules` and reconnect for USB access.
Cold startup additionally requires the system **OpenSSL CLI**. No Python USB
or cryptography package is required.

Two strictly matched profile reads detect an already initialized connection.
Otherwise startup performs Xbox GIP identification and a fresh version-1
authentication exchange. Fresh nonces, RSA PKCS#1 encryption, SHA256 transcript
hashing and HMAC verification are used; captured session cryptograms are never
replayed. Completion is sent only after verifying the controller's finished
transcript, and two matching profile reads are required before binding the app's
register channel. Startup checks USB identity and selection throughout, with a
25-second budget and a 4,096-packet limit per response.

The exchange verifies the fresh session transcript, not a Microsoft certificate
trust chain. Protocol framing was independently implemented using supplied
captures and the [xone authentication](https://github.com/dlundqvist/xone/tree/master/auth)
and [Linux xpad](https://github.com/torvalds/linux/blob/master/drivers/input/joystick/xpad.c)
protocol references.

## Verified packets

| Operation | Encoding |
|---|---|
| Read | 9-byte `0f 00 seq 05 04 bank offset_hi offset_lo length` |
| Read reply | 64-byte `10 00 seq 3c 05 bank offset_hi offset_lo length data…` |
| Rear write | 64-byte `0f 00 seq 3c 03 bank offset_hi offset_lo 08 record…`, zero-padded |
| L4 record | Eight bytes at `00ab`; target byte at `00b2` |
| R4 record | Eight bytes at `00c7`; target byte at `00ce` |
| Remap record | `04 00 00 00 00 00 01 target` |
| Default record | Eight zero bytes |
| Rate write | 64-byte `0f 00 seq 3c 03 bank 00 36 01 code`, zero-padded; banks 1–4 |
| Rate codes | `00` = 250 Hz, `01` = 500 Hz, `02` = 1000 Hz |

Targets are 1–4 for D-pad directions, 5/6 for LB/RB, 7/8 for LS/RS,
15–18 for A/B/X/Y, and 22/23 for View/Menu.
Replies must match sequence, bank, offset and length, with complete payloads.
Report-rate writes are read back and verified in every bank. Unlike the 8K and
Tarantula paths, G7 SE rate writes do not skip verification or assume a reconnect.
The rate labels describe the configured setting; physical USB polling frequency
has not been measured.

Profiles contain 421 readable bytes. Discovery compared four readable banks,
including the unexposed fourth bank, to check unrelated settings.

## Diagnostics and validation

Close Deadband before running diagnostics:

```sh
python3 tools/g7se_probe.py --app-startup-reads --output /tmp/g7se-startup.json
```

This runs production startup and repeat full-profile reads without writing
settings. Select an exact USB sysfs path with `--sysfs` if multiple G7 SEs are
connected. The default probe also tests read-only candidates on interface 0,
then interface 2 alternate setting 1 bulk endpoints 01/81 if necessary; it
restores the alternate setting and releases interfaces. Bulk is diagnostic-only
because verified configuration needs only interrupt transfers. Other explicit
probe modes are hardware validation tools; `--help` identifies modes that write
temporary remaps or restore supplied recovery records.

Confirmed packets are preserved in [small test fixtures](../tests/fixtures/README.md).
Tests cover identity isolation, rate and remap allowlists, framing, reply matching,
malformed packets,
timeouts, disconnects, selection/session changes, interface cleanup, staged
edits, Save readback, rollback and unsupported sources/targets/profiles.

Rate validation (close Deadband first):

```sh
python3 tools/g7se_probe.py --rate-roundtrip --output /tmp/g7se-rates.json
# Unplug/reconnect the same controller to the same USB port, then:
python3 tools/g7se_probe.py --verify-rate-reconnect /tmp/g7se-rates.json --output /tmp/g7se-rates-reconnected.json
```

The round-trip mode uses actual Qt staging and Save for all three rates, compares
full profiles after each setting, then restores each bank's original rate. It
saves a durable full baseline before the first write. The reconnect check is
read-only and compares every profile byte with that baseline. If restoration
could not finish, `--restore-rate-originals /tmp/g7se-rates.json` explicitly
retries only the four rate bytes; provide a new `--output` path. Keep these
owner-specific artifacts local. Existing output files are never overwritten.

Hardware checks completed:

- On 2026-10-11, actual app Save at 250/500/1000 Hz returned four verified
  rate readbacks each; all other profile bytes remained unchanged. Original
  settings were restored, and all 1,684 bytes matched after physical reconnect.
- Full-record remap, Default and restoration readbacks in editable banks.
- Actual Qt reader/bridge staging and Save of L4→A/R4→B, followed by restoration.
- Linux input events confirmed A/B after release and unplug/reconnect.
- Fresh authentication enabled repeatable reads on cold USB connections.
- Production startup after reconnect verified the original L3/R3 records and
  all 1,684 readable bytes against the original baseline; `xpad` was reattached.

Run software validation with `python3 -m unittest discover -s tests` and
`python3 smoke_test.py` (with the app closed). Raw PCAPs, Windows application
bundles and device-specific diagnostic/recovery files stay local and are not
required by the tests or distributed with support.
