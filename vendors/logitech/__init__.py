"""Logitech HID++ 2.0 backend for Deadband.

First device: the Logitech G502 X LIGHTSPEED (046d:c098 wired / via the
Lightspeed receiver 046d:c547). Unlike the GameSir controllers (a bespoke
0xFFF0 vendor protocol), Logitech mice speak the well-documented HID++ 2.0
feature protocol, and everything configurable on this mouse lives in a 256-byte
onboard-profile memory sector reached through feature 0x8100.

Modules:
  hidpp    - HID++ 2.0 transport (hidraw framing, feature discovery, 0x8100 I/O)
  onboard  - the 256-byte onboard-profile codec (READ path first; write later)

This backend is deliberately independent of the GameSir code: the app SHELL
(window, device picker, theme, settings, backup) is the shared layer; each
vendor brings its own transport + codec.
"""
