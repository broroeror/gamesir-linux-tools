"""G7 SE GIP v1 session exchange. No controller configuration writes.

Protocol references: supplied SE raw USBPcap and xone/auth/{auth,crypto}.c.
This implementation uses fresh OS randomness, OpenSSL RSA encryption, SHA256
transcript hashing and HMAC verification. It does not verify a Microsoft trust
chain and is not a general device authentication service. USB identity/session
pinning is provided by the bounded startup caller. Secrets stay in memory.
"""
import hashlib
import hmac
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from vendors.gamesir.models.g7se import gip


def prf(secret, label, seed, length):
    seed = label + seed
    digest = lambda data: hmac.digest(secret, data, 'sha256')
    a, output = digest(seed), bytearray()
    while len(output) < length:
        output.extend(digest(a + seed))
        a = digest(a)
    return bytes(output[:length])


def varint(value):
    if not 0 <= value <= 4096:
        raise ValueError('GIP integer out of diagnostic bounds')
    result = bytearray()
    while True:
        byte, value = value & 127, value >> 7
        result.append(byte | (128 if value else 0))
        if not value:
            return bytes(result)


def frame(sequence, options, payload, offset=None):
    length = varint(len(payload))
    suffix = b'' if offset is None else varint(offset)
    if (3 + len(length) + len(suffix)) % 2:
        length = length[:-1] + bytes((length[-1] | 128, 0))
    return bytes((6, options, sequence)) + length + suffix + payload


def request(command, length):
    return bytes((0, 0x42, 0, command)) + (length+4).to_bytes(2, 'big') + bytes(8)


def message(command, payload):
    data = bytes((command, 1)) + len(payload).to_bytes(2, 'big') + payload
    return bytes((0, 0x41, 0, command)) + len(data).to_bytes(2, 'big') + data + bytes(8)


def client_data(body, command):
    if (len(body) < 10 or body[:4] != bytes((0, 0xc2, 0, command))
            or body[6:8] != bytes((command, 1))
            or int.from_bytes(body[4:6], 'big') != len(body)-6
            or int.from_bytes(body[8:10], 'big') != len(body)-10):
        raise ValueError('Malformed, unsupported or unexpected authentication response')
    return body[10:]


def encrypt_secret(certificate, secret):
    # Captured certificate contains an RSA-2048 PKCS#1 public key. OpenSSL
    # parses and encrypts it; only the public key goes into a temporary file.
    marker = bytes.fromhex('3082010a')
    offsets = [i for i in range(len(certificate)) if certificate.startswith(marker, i)]
    if len(offsets) != 1 or offsets[0]+270 > len(certificate):
        raise ValueError('Expected exactly one complete captured-format RSA public key')
    public = certificate[offsets[0]:offsets[0]+270]
    with tempfile.TemporaryDirectory(prefix='g7se-public-key-') as directory:
        path = Path(directory)/'public.der'
        path.write_bytes(public)
        completed = subprocess.run(['openssl', 'pkeyutl', '-encrypt', '-pubin',
            '-inkey', str(path), '-keyform', 'DER', '-pkeyopt', 'rsa_padding_mode:pkcs1'],
            input=secret, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    if completed.returncode or len(completed.stdout) != 256:
        raise ValueError('OpenSSL could not encrypt the fresh session secret')
    return completed.stdout


class Exchange:
    def __init__(self, session, handle, log):
        self.session, self.handle, self.log = session, handle, log
        self.transcript = hashlib.sha256()

    def raw(self, wire, stage):
        self.session.check()
        self.log.append({'request': wire.hex(), 'interface': 0, 'stage': stage})
        if self.handle.write(wire) != len(wire):
            raise OSError('Short authentication transfer')

    def next_sequence(self):
        self.session.sequence = self.session.sequence % 255 + 1
        return self.session.sequence

    def chunk_ack(self, sequence, received, total):
        # SE firmware 0630 acknowledges host chunks with flags 0x30 and an
        # eleven-byte remainder bias, as captured for both HostSecret ACKs.
        expected = bytes((1, 32, sequence, 9, 0, 6, 48))
        expected += received.to_bytes(2, 'little') + bytes(2) + (total-received+11).to_bytes(2, 'little')
        result = self.session.receive(self.handle, self.log,
            lambda reply: reply if reply == expected else None, seconds=3)
        if result is None:
            raise OSError('Authentication chunk acknowledgment timed out')

    def send(self, body):
        if not 2 <= len(body) <= 1024:
            raise ValueError('Authentication request size out of bounds')
        sequence = self.next_sequence()
        if len(body) <= 58:
            self.raw(frame(sequence, 0x30, body), 'fresh-authentication-message')
        else:
            self.raw(frame(sequence, 0xf0, body[:58], len(body)), 'fresh-authentication-chunk-start')
            self.chunk_ack(sequence, 58, len(body))
            for offset in range(58, len(body), 58):
                part = body[offset:offset+58]
                last = offset + len(part) == len(body)
                self.raw(frame(sequence, 0xb0 if last else 0xa0, part, offset), 'fresh-authentication-chunk')
                if last:
                    self.chunk_ack(sequence, len(body), len(body))
            self.raw(frame(sequence, 0xa0, b'', len(body)), 'fresh-authentication-chunk-complete')
        return sequence

    def receive(self, sequence):
        transfer = gip.IdentificationTransfer(command=6, minimum=2, expected_sequence=sequence)
        def match(reply):
            # Normal input, GIP ACKs and unrelated replies are not auth data.
            if not reply or reply[0] != 6:
                return None
            decoded = gip.decode(reply)
            if (decoded['sequence'] == sequence and decoded['options'] == 0x30
                    and len(decoded['payload']) == 1):
                raise ValueError('Controller rejected authentication with status 0x' + decoded['payload'].hex())
            value, ack = transfer.accept(reply)
            if ack is not None:
                self.raw(ack, 'validated-authentication-chunk-ack')
            return value
        value = self.session.receive(self.handle, self.log, match, seconds=4)
        if value is None:
            raise OSError('Authentication message timed out')
        return value

    def host(self, command, payload):
        wire_body = message(command, payload)
        self.transcript.update(wire_body[6:-8])
        answer = self.receive(self.send(wire_body))
        if answer != bytes.fromhex('00c100010000'):
            raise ValueError('Controller rejected authentication host message')

    def query(self, command, length):
        body = self.receive(self.send(request(command, length)))
        payload = client_data(body, command)
        if len(payload) > length:
            raise ValueError('Oversized authentication response')
        return body, payload

    def run(self):
        if shutil.which('openssl') is None:
            raise OSError('G7 SE initialization requires the system OpenSSL command')
        host_random = secrets.token_bytes(32)
        self.host(1, host_random + bytes(8))
        body, hello = self.query(2, 80)
        if len(hello) != 80:
            raise ValueError('Unsupported client hello version/length')
        self.transcript.update(body[6:])
        body, certificate = self.query(3, 1024)
        self.transcript.update(body[6:])
        secret = secrets.token_bytes(48)
        master = prf(secret, b'Master Secret', host_random + hello[:32], 48)
        self.host(5, encrypt_secret(certificate, secret))
        host_finished = prf(master, b'Host Finished', self.transcript.digest(), 32)
        self.host(7, host_finished)
        _, finish = self.query(8, 64)
        expected = prf(master, b'Device Finished', self.transcript.digest(), 32)
        if len(finish) != 64 or not hmac.compare_digest(finish[:32], expected):
            raise ValueError('Fresh controller authentication transcript failed verification')
        self.raw(frame(self.next_sequence(), 0x20, bytes((1, 0))), 'verified-authentication-completion')
        return {'version': 1, 'fresh_transcript_verified': True,
                'certificate_sha256': hashlib.sha256(certificate).hexdigest()}
