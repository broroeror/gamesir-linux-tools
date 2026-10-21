#!/usr/bin/env python3
"""G7 SE 6.64: GIP rumble on the trigger channels (LT, RT), then the grips as a control.

Developer tool: it sends rumble commands to the controller (no settings are
written); end users never need it.
Deadband must be closed. Usage: python3 -I tools/g7se_trigger_rumble_test_664.py"""
import sys, time
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)
from vendors.gamesir.models.g7se import protocol as se  # noqa: E402
se.select(0x0664)
from tools.g7se_probe import ProbeHandle  # noqa: E402
from vendors.gamesir.models.g7se.startup import Startup  # noqa: E402

root = next(d.resolve() for d in Path('/sys/bus/usb/devices').iterdir()
            if (d / 'idProduct').exists() and (d / 'idVendor').read_text().strip() == '3537'
            and (d / 'idProduct').read_text().strip() == '1069')
bus, addr = int((root / 'busnum').read_text()), int((root / 'devnum').read_text())
h = ProbeHandle.open(se.VID, (se.PID,), bus, addr, str(root), 0, 2, 0x82)
st = Startup(h, bus, addr, root)
seq = 0
try:
    print('startup:', st.run())
    for label, lt, rt, l, r in (('LEFT TRIGGER', 192, 0, 0, 0),
                                ('RIGHT TRIGGER', 0, 192, 0, 0),
                                ('GRIPS (control)', 0, 0, 192, 192)):
        print('->', label, flush=True)
        for _ in range(2):                      # 2 x 400 ms
            seq = seq % 255 + 1
            h.write(se.rumble_packet(seq, l, r, lt, rt))
            time.sleep(0.4)
        seq = seq % 255 + 1
        h.write(se.rumble_packet(seq, 0, 0))     # stop
        time.sleep(1.5)
finally:
    seq = seq % 255 + 1
    try:
        h.write(se.rumble_packet(seq, 0, 0))
        st.restore_input()
    finally:
        h.close()
print('fim')
