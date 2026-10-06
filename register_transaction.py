"""Verified controller Apply with durable recovery data; transport is injected.

This is THE save path for every controller on the family register protocol
(Cyclone 2, G7 Pro 8K, Tarantula Pro 8K). It began as a second, stricter
Save used only for Continuous Trigger batches (#22); two save paths drift,
so it now handles every batch for those models. (The G7 Pro saves through
its own enveloped channel in bridge.applyConfig.)"""
import json
import os
import tempfile
from datetime import datetime, timezone


KEEP_RECOVERY_FILES = 20      # newest kept per folder; older ones are pruned


def prune(directory, keep=KEEP_RECOVERY_FILES):
    """Delete all but the newest `keep` recovery files. Called only after a
    VERIFIED apply -- a failed one keeps everything, since that is when the
    history matters. Only this module's own files are ever touched."""
    try:
        # 'before_apply_' (current) and 'cyclone2_before_apply_' (#22's name)
        files = sorted((os.path.join(directory, f) for f in os.listdir(directory)
                        if 'before_apply_' in f and f.endswith('.json')),
                       key=os.path.getmtime, reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        try:
            os.unlink(old)
        except OSError:
            pass


def apply(changes, read, write, directory, device, unverified=()):
    """Snapshot changed registers before writing; verify and recover on failure.

    read/write must reject a changed device session. The recovery file uses the
    existing labelled GameSir schema, so Backup & Restore can import it.

    `unverified` = (bank, addr) writes that can't be read back because the pad
    re-enumerates after them -- the poll rate on the 8K and Tarantula. They are
    moved to the END of the batch (after everything else is verified) and are
    written without a read-back; a reconnect afterwards is expected, not failure.
    """
    if not changes:
        return True, 'No changes to apply'
    unverified = set(unverified)
    changes = ([c for c in changes if (c[0], c[1]) not in unverified]
               + [c for c in changes if (c[0], c[1]) in unverified])
    original = []
    for bank, addr, data in changes:
        raw = list(read(bank, addr, len(data)))
        if len(raw) != len(data):
            raise OSError('incomplete pre-write register read; nothing written')
        original.append((bank, addr, raw))
    payload = {'schema': 3, 'device': device,
               'exported': datetime.now(timezone.utc).isoformat(),
               'scope': 'changed registers only', 'profiles': {}, 'lighting': {'fields': {}}}
    for bank, addr, raw in original:
        fields = (payload['lighting']['fields'] if bank == 0x20 else
                  payload['profiles'].setdefault(str(bank), {}))
        # Byte entries preserve overlapping edits of different lengths too.
        for offset, byte in enumerate(raw):
            address = addr + offset
            fields[f'0x{address:04x}'] = {'addr': f'0x{address:04x}', 'bytes': [byte]}
    os.makedirs(directory, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix='before_apply_', suffix='.pending', dir=directory)
    path = pending[:-len('.pending')] + '.json'
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(pending, path)
        if os.name == 'posix':
            dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    except BaseException:
        for candidate in (pending, path):
            if os.path.exists(candidate):
                os.unlink(candidate)
        raise

    attempted = []
    try:
        for i, (bank, addr, data) in enumerate(changes):
            attempted.append(original[i])       # include an interrupted write
            if not write(bank, addr, data):
                raise OSError('write refused or device session changed')
            if (bank, addr) in unverified:
                continue                        # pad reconnects; nothing to read
            if list(read(bank, addr, len(data))) != list(data):
                raise OSError(f'read-back mismatch at 0x{addr:04x}')
    except Exception as failure:
        restored = True
        for bank, addr, raw in reversed(attempted):
            try:
                if not write(bank, addr, raw) or list(read(bank, addr, len(raw))) != raw:
                    restored = False
            except Exception:
                restored = False
        result = 'original settings restored and verified' if restored else 'recovery NOT confirmed'
        return False, f'Apply failed ({failure}); {result}; recovery file: {path}'
    prune(directory)
    n = len(changes); checked = n - sum(1 for c in changes if (c[0], c[1]) in unverified)
    note = ' · poll rate set, controller reconnecting' if checked < n else ''
    return True, f'Applied ✓  {checked}/{checked} confirmed{note}'
