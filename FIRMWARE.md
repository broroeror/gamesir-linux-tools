# Firmware Backup & Restore (Cyclone 2, Linux)

> Everyday use — config, lighting, remaps, and backup/restore of your *settings* —
> never touches firmware and lives in the [README](README.md) and
> [Manual](MANUAL.md). This page covers the one optional feature that reads/writes
> the controller's *firmware*: **backing it up, and restoring a backup.**

The app can **back up your Cyclone 2's current firmware** to a local file, and
**restore a backup you made** — e.g. snapshot a known-good image before an official
update, then roll back to it if you want. That's the whole scope: it is a
backup/restore tool, **not** a firmware updater. It will not flash an arbitrary
image, and it will not overwrite your calibration/settings.

## What it is and isn't

- ✅ **Back up** the connected controller's current firmware to `firmware/`.
- ✅ **Restore** a firmware image *you previously backed up* (config preserved).
- ❌ No arbitrary-file flashing, no full-image (config-overwriting) writes, no
  version upgrade/downgrade shopping. There is no command-line flasher.

## Optional dependency: jl-uboot-tool (not bundled)

The actual read/write to the controller's flash is done by
[`jl-uboot-tool`](https://github.com/kagaimiq/jl-uboot-tool) (kagaimiq, MIT) — a
third-party JieLi loader client. **It is not redistributed with this app.** Backup
& Restore is simply unavailable until you install it yourself; the rest of the app
is unaffected (the Firmware panel shows a short "install jl-uboot-tool" note).

To enable the feature:

```sh
# 1. Get jl-uboot-tool and place it next to the app as ./jl-uboot-tool/
git clone https://github.com/kagaimiq/jl-uboot-tool

# 2. Its Python deps + the sg kernel module
pip install crcmod pyyaml pycryptodomex tqdm
sudo modprobe sg
```

No `sudo` for the operation itself: the same [`70-gamesir.rules`](README.md#running)
udev rule grants the loader's SCSI-generic node (`/dev/sg`).

## How it works

The MCU is a **JieLi BR23** (1 MB SPI-NOR). The vendor command `0f 17 55 88` — on the
same `0x0f` channel as everything else — reboots it into its **BR23 UBOOT loader**, a
USB mass-storage device that exposes the flash over SCSI. `jl-uboot-tool` performs the
read (backup) or write (restore); the app adds loader entry, a local library, verify-
after-write, and the safety guard below. Use it from **Settings (⚙) → Firmware Backup
& Restore**.

## Safety

- **Only over a wired connection.** Connect the controller **directly by USB cable**
  (Xbox mode). Never over the 2.4 GHz dongle — the dongle is a separate chip and
  writing controller firmware to it bricks it.
- **The identity guard is the backstop.** Immediately before any write — *in the
  loader* — the app reads the target chip's own flash-header identity and refuses
  unless it reads `GS_C2_ADC_DEVICE` **and** the image matches. The dongle reads
  `GS_C2_Dongle` here and is rejected (nothing written; it's reset to normal mode).
  The check reads the silicon, not a version number, so it holds across firmware
  revisions.
- **A bad write is recoverable.** The BR23 mask-ROM re-enters UBOOT whenever the
  flash holds no valid firmware, so an interrupted restore is fixed by a power-cycle
  and running Restore again. The chipkey (the one irreversible op) is never invoked.

## The firmware library

Backups live in `firmware/` (git-ignored — **no vendor firmware is redistributed**;
you populate it yourself with **Back up current firmware**):

- `cyclone2_<ver>_fw.bin` — the firmware-only restore image; restoring it **preserves
  your calibration/settings**.
- `backups/` — full per-unit dumps kept as your safety copies.

## Recovery

- **Controller looks dead after entering the loader?** It's just *parked* there (it
  enumerates as USB mass storage, not a gamepad). Power-cycle / replug, or hold the
  reset button (back center, under the MFG sticker) ~6 s to return to normal mode.
- **A restore was interrupted?** Power-cycle so the mask-ROM re-enters UBOOT, then run
  Restore again with your backup.
