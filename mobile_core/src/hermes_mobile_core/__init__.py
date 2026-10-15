"""Held remnant of the July mobile provider core (embedded-hermes plan D0).

The duplicates this package used to re-export (``core``, ``auth``,
``providers``, ``events``, ``exceptions``, ``_vendor``) were deleted; phones run
the real Hermes wheel under a profile. ``turn_runner`` was re-homed as the
SDK-free client ``agent.transports.httpx_client`` and ``redact`` into
``agent_runtime.redaction`` (plan Stage 2). What is left is the import gate,
which the Stage 2 profile gate replaces.
"""

__version__ = "0.2.0"
