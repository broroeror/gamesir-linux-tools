# feat(gamesir): full button support, battery display fix, and PID 0x103c for Tarantula 8K

## Summary
Provide complete button support, battery-less UI handling, and `0x103c` / `0x103d` detection for the GameSir Tarantula 8K controller:

1. **In-App Battery Indicator Fix (`has_battery=False`):**
   - The wired-only Tarantula 8K has no internal battery, so bytes 35 and 36 of the `0x12` input report do not carry battery percentage or charging state (previously causing the top bar to show a red `0%` / flickering `⚡`).
   - Added `has_battery: bool = True` to `ControllerProfile` (`has_battery=False` on `TARANTULA_PRO_8K`), exposed `bridge.hasBattery`, suppressed battery/charging decoding in `parse_enhanced`, and hid the battery readout in `StatusPill.qml` when `bridge.hasBattery` is false.

2. **Full Button Support (`C1–C4`, `T1–T3`, `L4`, `R4`, `LT`, `RT`, `View`, `Menu`, `Share`, `Home`, `M`):**
   - **Live Input Highlights:** Added `c1`–`c4` (`0x01`–`0x08`) and `t1`–`t3` (`0x10`–`0x40`) decoding from byte 63 of the `0x12` report in `vendors/gamesir/enhanced.py`, tracked them in `gs_state.py` (`state` and `EXTRA_BTNS`) and `bridge._poll_input`, and added live press highlights for the Tarantula's `Home` (`G`) and `M` buttons in `ControllerView.qml`.
   - **Complete Remap Slots & Self-Code Defaults:** Added `LT` (`0x06ac`), `RT` (`0x06cc`), `View` (`0x009d`), `Menu` (`0x00a4`), and `Share` (`0x00ab`) to `TARANTULA_PRO_8K.REMAP_SLOTS` (all 26 remappable buttons). Added `REMAP_DEFAULTS` for the programmable button blocks and triggers (`L4=0x11`, `R4=0x12`, `LT=0x13`, `RT=0x14`, `C1–C4=0x1f–0x22`, `T1–T3=0x23–0x25`) so factory self-code records decode as `Default` (`-1`) instead of raw hex codes and resetting to `Default` restores `[0x01, self_code]`.
   - **Motion Activation Buttons:** Added the Tarantula's full button set (`View`, `Menu`, `Share`, `L4`, `R4`, `C1–C4`, `T1–T3`) to `TARANTULA_PRO_8K.motion['buttons']`.

3. **PID `0x103c` Support & High-Rate Probe Fix:**
   - Added `0x103c` alongside `0x103d` in `TARANTULA_PRO_8K`, ensured `find_vendor_hidraw` / `pick_live_node` select the interface declaring vendor report IDs (`0x0f`/`0x10`/`0x12`), added a Tarantula-specific `modeMessage` (`Home + X` for 2s), and fixed `doctor._ask` to only sleep when `dev.read(64)` returns empty so `--doctor --probe` does not overflow the hidraw queue on 1000–8000 Hz controllers.

## Verification
- Unit tests: `python3 -m pytest tests/` (258 passed)
- Smoke tests: `python3 smoke_test.py` (PASS)
- Syntax check: `python3 -m py_compile $(git ls-files '*.py')`
- Live hardware diagnostic & probe: `python3 deadband.py --doctor --probe` (all 26 button records verified on `/dev/hidraw15`)
