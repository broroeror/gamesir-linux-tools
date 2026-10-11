"""Super Nova <-> the app's editor: read the blocks behind the four features
with verified writes and decode them into the config keys the QML pages
already use, and turn staged edits back into verified block writes.

The app stages edits as {(bank, addr): bytes}, with addresses from the
profile's fields. For this pad those are virtual (protocol.VADDR_*): this
module is the only place that decodes them. `link` is anything with
request(name, payload) -> body (config.write_block's contract): the control
adapter in the app, a FakePad in tests.

Features and their blocks:
    vib_l / vib_r          vibrate_param byte 0 / 1, percent
    st/rs/lt/rt _dz_min    stick_curve / trigger_param begin deadzone,
                           curve x rescaled exactly as GameSir's app does
    remap{name: code}      key_mapping, gamepad -> gamepad (-1 = default)
"""

from vendors.gamesir.models.supernova import config as nova
from vendors.gamesir.models.supernova import protocol as sn

# A mapping this editor can't represent (keyboard, mouse, several buttons,
# macro -- made in GameSir's app). Shown as such, and left alone unless the
# user picks a new target for that button.
REMAP_FOREIGN = 0x100

_SOURCES = dict(sn.REMAP_SOURCES)
_SOURCE_BY_CODE = {c: n for n, c in sn.REMAP_SOURCES}
_TARGET_CODES = frozenset(c for _n, c in sn.REMAP_TARGETS)
_STICKS = {0: 'st', 1: 'rs'}
_TRIGGERS = {0: 'lt', 1: 'rt'}


def _blocks_for_read():
    yield nova.BLOCKS['vibrate_param']
    for i in (0, 1):
        yield nova.BLOCKS[f'stick_curve/{i:02x}/00']
        yield nova.BLOCKS[f'trigger_param/{i:02x}']
    for _name, code in sn.REMAP_SOURCES:
        yield nova.BLOCKS[f'key_mapping/00/{code:02x}']


def decode_remap(data):
    """-1 for a button mapped to itself, its target code for one gamepad
    button, REMAP_FOREIGN for anything else."""
    own = data[sn.KEY_SOURCE]
    if data[sn.KEY_TYPE] != sn.KEY_TYPE_GAMEPAD or data[sn.KEY_COUNT] != 1:
        return REMAP_FOREIGN
    target = data[sn.KEY_CODES]
    if target == own:
        return -1
    return target if target in _TARGET_CODES else REMAP_FOREIGN


def decode(blocks):
    """Config dict from {block key: bytes}."""
    vib = blocks['vibrate_param']
    cfg = {'vib_l': vib[sn.VIB_LEFT], 'vib_r': vib[sn.VIB_RIGHT], 'remap': {}}
    for i, side in _STICKS.items():
        b = blocks[f'stick_curve/{i:02x}/00']
        cfg[side + '_dz_min'] = b[sn.STICK_POINTS + sn.P_DZ_BEGIN]
        cfg[side + '_dz_max'] = b[sn.STICK_POINTS + sn.P_DZ_END]     # read-only
    for i, side in _TRIGGERS.items():
        b = blocks[f'trigger_param/{i:02x}']
        cfg[side + '_dz_min'] = b[sn.TRIG_POINTS + sn.P_DZ_BEGIN]
        cfg[side + '_dz_max'] = b[sn.TRIG_POINTS + sn.P_DZ_END]      # read-only
    for name, code in sn.REMAP_SOURCES:
        cfg['remap'][name] = decode_remap(blocks[f'key_mapping/00/{code:02x}'])
    return cfg


def read_config(link):
    """Confirm the pad is a Super Nova, read every block behind the four
    features, and return (config dict, {block key: bytes})."""
    nova.check_is_super_nova(link)
    blocks = {b.key: nova.read_block(link, b) for b in _blocks_for_read()}
    return decode(blocks), blocks


def _target_block(addr):
    """(block, how to change it) for one virtual address."""
    hi, lo = addr >> 8, addr & 0xFF
    if addr in (sn.VADDR_VIB + sn.VIB_LEFT, sn.VADDR_VIB + sn.VIB_RIGHT):
        return nova.BLOCKS['vibrate_param'], ('vib', lo)
    if hi == sn.VADDR_STICK_DZ >> 8 and lo in _STICKS:
        return nova.BLOCKS[f'stick_curve/{lo:02x}/00'], ('dz', sn.STICK_POINTS)
    if hi == sn.VADDR_TRIG_DZ >> 8 and lo in _TRIGGERS:
        return nova.BLOCKS[f'trigger_param/{lo:02x}'], ('dz', sn.TRIG_POINTS)
    if hi == sn.VADDR_KEY >> 8 and lo in _SOURCE_BY_CODE:
        return nova.BLOCKS[f'key_mapping/00/{lo:02x}'], ('key', lo)
    raise nova.PadError(f'no Super Nova feature at {addr:#06x}')


def _change(block_data, how, data):
    kind, arg = how
    data = bytes(data)
    if not data:
        raise nova.PadError('empty edit')
    if kind == 'vib':
        if data[0] > 100:
            raise nova.PadError(f'vibration {data[0]} is not a percentage')
        out = bytearray(block_data)
        out[arg] = data[0]
        return bytes(out)
    if kind == 'dz':
        try:
            return sn.with_begin_deadzone(block_data, arg, data[0])
        except ValueError as e:
            raise nova.PadError(str(e))
    # key: the bridge stages [1, target] or [0, 0] (= default, map to itself)
    if not data[0]:
        target = arg
    elif len(data) < 2 or data[1] not in _TARGET_CODES:
        raise nova.PadError(f'cannot map to {data[1:2].hex() or "nothing"}')
    else:
        target = data[1]
    return sn.with_key_target(block_data, target)


def plan_edits(link, edits):
    """[(block, old bytes, new bytes)] for staged edits {addr: bytes}, several
    edits to one block folded into one write. Reads, never writes."""
    order, per_block = [], {}
    for addr, data in edits.items():
        block, how = _target_block(addr)
        if block.key not in per_block:
            old = nova.read_block(link, block)
            per_block[block.key] = [block, old, old]
            order.append(block.key)
        entry = per_block[block.key]
        entry[2] = _change(entry[2], how, data)
    return [tuple(per_block[k]) for k in order if per_block[k][1] != per_block[k][2]]


def apply_edits(link, edits):
    """Write staged edits as verified block writes, all or nothing, then save
    once. On any failure, blocks already written are put back and nothing is
    saved; the PadError is re-raised. Returns the list of block keys written."""
    nova.check_is_super_nova(link)
    writes = plan_edits(link, edits)
    done = []
    try:
        for block, old, new in writes:
            nova.write_block(link, block, new)     # verifies; undoes itself on mismatch
            done.append((block, old))
    except Exception:
        for block, old in reversed(done):
            try:
                nova.write_block(link, block, old)
            except Exception:
                pass                               # report the original failure
        raise
    if done:
        nova.save(link)
    return [b.key for b, _ in done]
