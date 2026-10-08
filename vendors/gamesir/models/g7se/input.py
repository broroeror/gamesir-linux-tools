"""G7 SE standard Xbox input reports, matching Linux xpad's axis layout."""
import struct
from . import gip

_HAT = {(0, 0): 'neutral', (0, -1): 'up', (1, -1): 'up-right',
        (1, 0): 'right', (1, 1): 'down-right', (0, 1): 'down',
        (-1, 1): 'down-left', (-1, 0): 'left', (-1, -1): 'up-left'}


def decode(report):
    try:
        frame = gip.decode(bytes(report))
    except ValueError:
        return None
    if frame['command'] != 0x20 or frame['options'] != 0 or len(frame['payload']) < 14:
        return None
    buttons, lt, rt, lx, ly, rx, ry = struct.unpack_from('<HHHhhhh', frame['payload'])
    result = {key: bool(buttons & mask) for key, mask in (
        ('menu', 4), ('view', 8), ('a', 16), ('b', 32), ('x', 64), ('y', 128),
        ('lb', 0x1000), ('rb', 0x2000), ('ls', 0x4000), ('rs', 0x8000))}
    # Use the same 0..255 state scale as the evdev path. xpad complements Y
    # to make up negative; Xbox triggers use unsigned 0..1023 values.
    for key, value in (('lx', lx), ('ly', ~ly), ('rx', rx), ('ry', ~ry)):
        result[key] = round((value + 32768) * 255 / 65535)
    result.update(lt=round(min(lt, 1023) * 255 / 1023),
                  rt=round(min(rt, 1023) * 255 / 1023))
    hat = (bool(buttons & 0x0800) - bool(buttons & 0x0400),
           bool(buttons & 0x0200) - bool(buttons & 0x0100))
    result['dpad'] = _HAT[hat]
    return result
