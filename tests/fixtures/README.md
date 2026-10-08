# G7 SE descriptor 0630 protocol fixtures

These small JSON fixtures contain confirmed USB requests/responses from Linux
probes and owner-supplied Windows Nexus Legacy 1.5.3.0 captures. Source filenames
and hashes provide provenance; raw captures are not required to run the tests.

- `g7se-0630-nexus.json`: short reads, target writes, rear records and readbacks.
- `g7se-0630-linux-roundtrip.json`: complete record remap, Default and restoration.
- `g7se-0630-auth.json`: authentication framing, public certificate, reconstructed
  handshake messages and controller chunk acknowledgements. Production generates
  fresh session material; no premaster or master secret is included or replayed.
- `g7se-0630-gip-identification.json`: bounded identification and chunk ACKs.
- `g7se-0630-input.json`: standard Xbox input reports and expected readouts.
- `g7se-0630-firmware.json`, `g7se-0630-info-0b.json`: information replies.
- `g7se-0630-nexus-startup.json`: earlier transient startup candidates, distinct
  from the verified fresh authentication path.

Historical fixtures include the readable fourth bank. Nexus exposes three
editable profiles, so tests explicitly require production writes to bank 4 to
be refused. Device backups, full local diagnostics and Windows vendor bundles
are excluded from the upstream change.
