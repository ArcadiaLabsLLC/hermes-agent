"""Held remnant of the July mobile provider core (embedded-hermes plan D0).

The duplicates this package used to re-export (``core``, ``auth``,
``providers``, ``events``, ``exceptions``, ``_vendor``) were deleted; phones run
the real Hermes wheel under a profile. What is left is held for re-homing:
``turn_runner`` (the SDK-free client, Stage 2) and ``redact`` (its rules are
folded into ``agent_runtime.redaction``).
"""

__version__ = "0.2.0"
