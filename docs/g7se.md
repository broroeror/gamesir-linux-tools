# GameSir G7 SE support

Tested on Linux with USB identity **3537:1010**, firmware descriptor **6.30**
(`bcdDevice=0630`), and Windows GameSir Nexus Legacy 1.5.3.0 packet captures.
Other firmware remains input-only. G7 SE has its own controller profile and
protocol modules; its identity is outside the G7 Pro allowlist.

## Supported behavior

Choose **Configure controller**, select **profile 1, 2 or 3**, edit **L4/R4** on
Rebinds, then **Save** and **Release to games**. Three profiles match the Nexus
UI. Selecting a profile chooses which bank to edit; it does not switch the
controller's active profile. Bank 4 was readable during discovery but is neither
exposed nor writable through the app.

Targets: D-pad directions, LB/RB, L3/R3 (shown as LS/RS), A/B/X/Y, View and Menu.
Default clears the remap record. Keyboard, mouse, macros, calibration, stick or
trigger settings, polling-rate changes, vibration configuration, reset and
general backup import/export are unavailable for this model. Rebinds includes
read-only LT/RT percentages and stick X/Y values, plus the live controller diagram.

Edits stay staged until Save. Before writing, the app saves the original complete
records to its durable recovery directory. It verifies each write by reading
the record back and attempts verified rollback on failure. Edits, reads and
writes are pinned to the selected device, USB session and edited profile.
Disconnects or selection changes stop the operation. Recovery files remain
available if a disconnected controller prevents immediate restoration.

## Transport and startup

The app uses system `libusb-1.0`, interface 0 interrupt endpoints **02/82**.
Configure temporarily claims the interface; Release and cleanup return it to
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

Targets are 1–4 for D-pad directions, 5/6 for LB/RB, 7/8 for LS/RS,
15–18 for A/B/X/Y, and 22/23 for View/Menu. These differ from G7 Pro encodings.
Replies must match sequence, bank, offset and length, with complete payloads.
Profiles contain 421 readable bytes. Discovery compared four readable banks,
including the unexposed fourth bank, to check unrelated settings.

## Diagnostics and validation

Close Deadband before running diagnostics:

```sh
python3 tests/g7se_probe.py --app-startup-reads --output /tmp/g7se-startup.json
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
Tests cover identity isolation, framing, reply matching, malformed packets,
timeouts, disconnects, selection/session changes, interface cleanup, staged
edits, Save readback, rollback and unsupported sources/targets/profiles.

Hardware checks completed:

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
