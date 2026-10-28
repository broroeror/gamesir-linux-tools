# feat(gamesir): add PID 0x103c for GameSir Tarantula 8K variant

## Summary
Support USB product ID `0x103c` alongside `0x103d` for the GameSir Tarantula 8K controller (`3537:103c`).

Previously, Deadband did not register `0x103c` as a supported profile and `doctor.py` flagged it as an unconfigurable "non-PC mode". In reality, the Tarantula 8K under this PID enumerates two HID interfaces on Linux:
- Interface 0 (`/dev/hidraw15`): Gamepad input (`0x01`), pages `0xfff0/0xff00`, report IDs `0x43`, `0xa2`
- Interface 1 (`/dev/hidraw16`): pages `0xfff0/0xff00`, vendor report IDs `0x10`, `0x12`, `0x0f`

The vendor channel on interface 1 declares the standard family protocol reports (`0x0f` output commands, `0x10` responses, `0x12` live telemetry).

## Changes
- **`controller_profile.py`**: Added PID `0x103c` to `TARANTULA_PRO_8K.usb_products` and `wired_products`.
- **`doctor.py`**: Removed the verdict warning that flagged `0x103c` as non-PC / unconfigurable. Devices under `0x103c` are now correctly recognized as configurable GameSir pads and report `GameSir device access: OK.`.
- **`gs_common.py`**: Added `_declares_vendor_channel` check to ensure `pick_live_node` and `find_vendor_hidraw` route to the interface declaring the vendor command channel (`0x0f`/`0x10`/`0x12`) when multiple interfaces are present on a device.
- **`bridge.py`**: Added model-specific `modeMessage` instructions for `TARANTULA_PRO_8K` (holding Home + X for 2 seconds to enter PC mode).
- **`tests/test_detection.py`**: Added `test_tarantula_pid_variants_resolve_to_tarantula_profile` unit test.

## Verification
- Unit tests: `python3 -m pytest tests/` passed (256/256 passed).
- Smoke tests: `python3 smoke_test.py` passed with returncode 0.
- Syntax: `python3 -m py_compile $(git ls-files '*.py')` compiled cleanly.
- Diagnostic & Probe: `python3 deadband.py --doctor --probe` tested against the connected Tarantula 8K controller:
  - Recognized as `GameSir 103c` / `Tarantula Pro 8K`.
  - Vendor channel identified on `/dev/hidraw16` (`pages 0xfff0/0xff00, report ids 0x10 0x12 0x0f`).
  - Probed under button records without being marked as unconfigurable.
