"""Super Nova configuration snapshots: read every block, diff, restore, and one
verified write at a time. Transport-agnostic -- `link` is anything with
request(name, payload=b'') -> reply body (see transport.SuperNovaLink), so the
logic is tested against a simulated pad without hardware.

Every write here is read-modify-write: the bytes sent are the bytes the pad
returned with only the intended field changed, the result is read back and
compared before anything is saved, and a mismatch puts the original back
without saving.
"""

from dataclasses import dataclass

from vendors.gamesir.models.supernova import protocol as sn

BACKUP_FORMAT = 'deadband-supernova-backup/1'

# Every button id GameSir Connect reads on connect (capture 01): 0x00..0x2d.
KEY_IDS = tuple(range(0x00, 0x2E))
# Lighting zones it reads: panel, home, ABXY, BAYX (main.js SAPJoyUniLightName).
LIGHT_ZONES = (0x00, 0x04, 0x05, 0x06)


@dataclass(frozen=True)
class Block:
    kind: str                 # get_<kind> / set_<kind> in protocol.COMMANDS
    args: tuple               # get request payload
    restorable: bool          # set payload == get data, confirmed by a capture
    id_at: tuple = ()         # (offset, value) pairs the data must carry

    @property
    def key(self):
        return self.kind + ''.join(f'/{a:02x}' for a in self.args)


def all_blocks():
    out = [Block('key_mapping', (0, k), True, ((sn.KEY_SOURCE, k),)) for k in KEY_IDS]
    for s in (0, 1):
        out.append(Block('stick_mapping', (s,), True, ((0, s),)))
        out.append(Block('stick_curve', (s, 0), True, ((0, s),)))
    out += [Block('trigger_param', (t,), True, ((0, t),)) for t in (0, 1)]
    out.append(Block('vibrate_param', (), True))
    out.append(Block('light_param', (), True))
    out += [Block('light_color', (z,), True, ((0, z),)) for z in LIGHT_ZONES]
    # Read and compared, never written: their set layouts are unconfirmed.
    # (dpad: the app reads 4 bytes and writes 6.)
    out.append(Block('dpad_param', (), False))
    out.append(Block('motion_curve', (0,), False))
    out.append(Block('motion_mapping', (), False))
    return out


BLOCKS = {b.key: b for b in all_blocks()}


class PadError(RuntimeError):
    pass


def read_block(link, block):
    data = bytes(link.request('get_' + block.kind, bytes(block.args)))
    for off, val in block.id_at:
        if off >= len(data) or data[off] != val:
            raise PadError(f'{block.key}: reply does not describe this block '
                           f'(byte {off} = {data[off] if off < len(data) else None}, '
                           f'expected {val})')
    return data


def check_is_super_nova(link):
    body = link.request('get_device_info')
    kind = sn.device_type_from_info(body)
    if kind != sn.DEVICE_TYPE_ID:
        raise PadError(f'the pad reports device type {kind}, not a Super Nova '
                       f'({sn.DEVICE_TYPE_ID}); refusing to touch it')
    return body


def snapshot(link):
    """Read every block. Returns a JSON-ready dict."""
    info = check_is_super_nova(link)
    return {
        'format': BACKUP_FORMAT,
        'device_type': sn.device_type_from_info(info),
        'blocks': {b.key: read_block(link, b).hex() for b in BLOCKS.values()},
    }


def diff(before, after):
    """{key: (before_hex, after_hex)} for every block that differs."""
    a, b = before['blocks'], after['blocks']
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b))
            if a.get(k) != b.get(k)}


def _set(link, block, data):
    body = link.request('set_' + block.kind, data)
    if not sn.set_succeeded(body):
        raise PadError(f'{block.key}: the pad rejected the write (status {body.hex()})')


def write_block(link, block, new):
    """Write one block and verify it by reading it back. On a mismatch the
    original is written back and PadError raised. Does NOT save."""
    if not block.restorable:
        raise PadError(f'{block.key}: write layout unconfirmed; not writing')
    old = read_block(link, block)
    new = bytes(new)
    if len(new) != len(old):
        raise PadError(f'{block.key}: {len(new)} bytes for a {len(old)}-byte block')
    for off, val in block.id_at:
        if new[off] != val:
            raise PadError(f'{block.key}: new data would retarget byte {off}')
    if new == old:
        return old
    _set(link, block, new)
    back = read_block(link, block)
    if back != new:
        _set(link, block, old)
        raise PadError(f'{block.key}: read back {back.hex()} after writing '
                       f'{new.hex()}; original restored, nothing saved')
    return old


def save(link):
    body = link.request('save_config_page')
    if not sn.set_succeeded(body):
        raise PadError(f'save rejected (status {body.hex()})')


def restore_plan(current, backup):
    """(writes, skipped): blocks to write to get from `current` to `backup`,
    and differing blocks that cannot be written."""
    if backup.get('format') != BACKUP_FORMAT:
        raise PadError('not a Super Nova backup from this tool')
    writes, skipped = [], []
    for key, (now, want) in diff(current, backup).items():
        block = BLOCKS.get(key)
        if block is None or want is None:
            skipped.append(key)
        elif block.restorable:
            writes.append((block, bytes.fromhex(want)))
        else:
            skipped.append(key)
    return writes, skipped


def restore(link, backup):
    """Write every restorable block that differs from the backup, save, and
    return (written keys, skipped keys, remaining diff)."""
    current = snapshot(link)
    writes, skipped = restore_plan(current, backup)
    for block, data in writes:
        write_block(link, block, data)
    if writes:
        save(link)
    after = snapshot(link)
    return [b.key for b, _ in writes], skipped, diff(after, backup)
