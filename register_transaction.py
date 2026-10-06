"""Verified controller Apply with durable recovery data; transport is injected."""
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
        files = sorted((os.path.join(directory, f) for f in os.listdir(directory)
                        if f.startswith('cyclone2_before_apply_') and f.endswith('.json')),
                       key=os.path.getmtime, reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        try:
            os.unlink(old)
        except OSError:
            pass


def apply(changes, read, write, directory, device):
    """Snapshot changed registers before writing; verify and recover on failure.

    read/write must reject a changed device session. The recovery file uses the
    existing labelled GameSir schema, so Backup & Restore can import it.
    """
    if not changes:
        return True, 'No changes to apply'
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
    fd, pending = tempfile.mkstemp(prefix='cyclone2_before_apply_', suffix='.pending', dir=directory)
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
    return True, f'Applied and verified {len(changes)} changes; recovery file: {path}'
