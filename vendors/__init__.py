"""Per-vendor controller support.

Each subpackage speaks ONE manufacturer's protocol. The app core (bridge, reader,
controller_profile) stays vendor-neutral and reaches hardware only through these.
Adding a manufacturer means adding a sibling package here — not touching the core.
"""
