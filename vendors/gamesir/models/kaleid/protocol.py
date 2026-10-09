"""GameSir Kaleid vendor protocol — the family register channel over Xbox GIP.

The Kaleid is an Xbox-licensed pad, so its configuration channel is NOT the
GameSir hidraw vendor collection the Cyclone 2 / G7 Pro 8K / Tarantula use. That
collection is declared on this pad's HID identities and is VESTIGIAL: probed over
hidraw and over raw libusb, in all three modes, with every framing in this
project plus the `gamesirapp` handshake, it never answers. What does answer is the
same GameSir register protocol carried as an Xbox GIP vendor message.

Reverse-engineered 2026-10-08 on a Kaleid reporting "GameSir-K1 Controller for
Xbox", bcdDevice 0165 (firmware 1.65); full notes and captures in the research
trail (see README's Kaleid section). The decisive find was the GIP IDENTIFY
descriptor's `client_commands` list, which advertises 0x0f out / 0x10 in with a
60-byte payload -- exactly the family's register commands.

IDENTITIES. `M + Xbox` cycles the pad between three USB identities. Only the GIP
one is configurable:

    3537:1082   03/00/00 x2 (HID)            DirectInput / PC mode
    3537:1086   ff/5d/01 + 03/00/00          XInput mode
    3537:1012   ff/47/d0 x2                  GIP / Xbox mode  <- configurable

In 1012, interface 1 is also ff/47/d0 but its altsetting 0 has zero endpoints --
it is the zero-bandwidth placeholder of the Xbox headset-audio interface, not a
second vendor channel. The register channel is interface 0 only.

xpad on a current kernel matches this vendor by INTERFACE CLASS, not product id
(`usb:v3537p*...icFFisc47ipD0`), so both 1086 and 1012 bind for input with no PID
quirk; nothing here is needed to make the pad work in games.

⚠ GIP MODE IS NOT STICKY. After interface 0 is claimed and released, the pad
re-enumerates back to 1082. Its own host handshake (announce / power-on) is not
implemented here, which is the likely cause and also why GIP STATUS and
SERIAL_NUMBER stay silent. The consequence for a session is benign but visible:
configuration holds the claim for as long as it is open, and the owner cycles
back to Xbox mode with `M + Xbox` afterwards.
"""

from __future__ import annotations

from vendors.gamesir.usb_transport import InterruptHandle

VID = 0x3537
PID_GIP = 0x1012        # GIP / Xbox mode -- the only configurable identity
PID_HID = 0x1082        # DirectInput / PC mode
PID_XINPUT = 0x1086     # XInput mode
CONFIG_PIDS = (PID_GIP,)
# The two non-GIP modes. Recognised so the app can name the pad and say which
# chord reaches a configurable mode, never opened and never written.
OTHER_MODE_PIDS = (PID_HID, PID_XINPUT)
ALL_PIDS = CONFIG_PIDS + OTHER_MODE_PIDS

IFACE = 0
EP_OUT = 0x02
EP_IN = 0x82

# --- wire format (verified; every chunk answered first try, zero retries) ----
#   request:  0f 00 <seq> 3c | 04 <bank> <hi> <lo> <len>          + zero pad to 60
#   write:    0f 00 <seq> 3c | 03 <bank> <hi> <lo> <len> <data>
#   reply:    10 00 <seq> 3c | 05 <bank> <hi> <lo> <len> <data>
#
# Byte 0 is the GIP command, byte 1 its OPTIONS and byte 2 the sequence, so the
# bodies are the project's BARE register commands (`03 …` / `04 …`) -- the GIP
# header already carries what the G7 Pro's path wraps by hand. Worth noting that
# the G7's `0f 00 <seq>` prefix IS a GIP header: that path has been speaking GIP
# all along, which is why its write framing transfers here unchanged.
COMMAND = 0x0F          # host -> device vendor message
REPLY = 0x10            # device -> host
# OPTIONS must be 0x00. With 0x20 (GIP_OPT_INTERNAL) register reads go silent
# while the input telemetry carries on, which reads as a dead channel.
OPTIONS = 0x00
# The G7 Pro sends reads on command byte 0x05 and writes on 0x3c; on this pad
# 0x3c is verified for BOTH. 0x05 was never tried here, so the read path uses the
# channel that is known to answer rather than the one that looks symmetrical.
VENDOR_CHANNEL = 0x3C

# Command 0x10 is multiplexed; body[0] says which stream a reply belongs to.
READ_MARKER = 0x05      # register reply
INPUT_MARKER = 0xE0     # input telemetry (rests at e0 80 80 80 80 0f …)

# 5-byte body header + 55 data = 60, exactly the payload size the pad's own
# IDENTIFY descriptor advertises for 0x0f / 0x10.
READ_CHUNK = 0x37
REPORT_SIZE = 64

LIGHT_BANK = 0x20       # lighting; see models/cyclone2/led.py for the layout

# ⚠ VENDOR COMMAND 0x07 IS DESTRUCTIVE ON THIS PAD. It is `set_profile` for the
# Cyclone, where it is harmless. Here it writes offset 0x3f of the PROFILE banks
# -- the profile -> lighting-record link -- and collapses several of the on-pad
# `M + Y/B/A/X` chords onto one record. Measured: banks 0x01 and 0x04 came back
# with 0x3f clobbered to 2 (correct values 0 and 3), which the owner noticed as
# three chords selecting the same lighting. Repaired by writing 0x3f back.
#
# So the pad has no software profile switch we can use: 0x07 damages it and 0x06
# (`get_profile`) answers with noise or nothing. The profile is the owner's to
# choose with the chords, and `software_profile_switch=False` on the controller
# profile is what keeps 0x07 from ever being sent. Finding one probably needs a
# capture of the vendor's own Windows app against the Xbox GIP stack.
#
# The wider lesson, from the same episode: a command's side effects need not land
# in the bank you are working in, so keep a baseline of EVERY bank and diff them
# all. The register writes themselves were exact -- across a blink test, two
# write probes and a long interactive session, zero RGB and zero header bytes
# ended up different from the pre-write baseline.
HAZARD_COMMANDS = (0x07,)

# Profile banks 0x01..0x04 read cleanly and decode against the G7 Pro's register
# map: 0x20..0x23 are four vibration strengths at the family default of 75, and
# a stride-7 remap table runs from 0x42 exactly as in models/g7pro/protocol.py
# (this pad's own paddle remaps were sitting in the G7's L5/R4/R5 records). None
# of it is WRITE-verified, so the controller profile deliberately declares no
# banks and no analog/remap addresses: resembling a mapped device is not evidence
# about this one. Enabling any of it means a read/write round-trip on real
# hardware, the same bar every other model in this project had to clear.
PROFILE_BANKS_OBSERVED = (0x01, 0x02, 0x03, 0x04)
PROFILE_LIGHT_LINK = 0x003F

# The pad idles its lighting animation when the CLAIMED vendor interface goes
# quiet: it keeps cycling while traffic flows, stops after somewhere between ~15
# and ~30 seconds of silence, and picks up again the moment the claim is released.
# Nothing to do with writing -- measured all four ways (gip_keepalive_test.py):
# silent + no write stops; one read per second keeps it running indefinitely, with
# or without a write first. So a session that wants the animation to keep playing
# while the owner edits has to keep talking to the pad.
ANIM_IDLE_TIMEOUT = 15.0        # conservative end of the measured range
KEEPALIVE_SECS = 1.0            # how often the session polls; must stay well under it     # profile bank -> lighting record (identity 0..3)


def open_device(bus: int, address: int, sysfs: str):
    """Claim the GIP register interface of a Kaleid in Xbox mode."""
    return InterruptHandle.open(VID, CONFIG_PIDS, bus, address, sysfs,
                                IFACE, EP_OUT, EP_IN)


def register_reply(report):
    """Decode a register reply into ``(bank, addr, data)``, else None.

    Returns None for input telemetry, which shares command 0x10 -- filter on the
    body marker or a stick position will be stored as register data.
    """
    if len(report) < 9 or report[0] != REPLY:
        return None
    body = report[4:]
    if body[0] != READ_MARKER:
        return None
    length = body[4]
    return body[1], (body[2] << 8) | body[3], list(body[5:5 + length])


def is_telemetry(report):
    """Whether ``report`` is the pad's input stream rather than a register reply."""
    return len(report) >= 5 and report[0] == REPLY and report[4] == INPUT_MARKER
