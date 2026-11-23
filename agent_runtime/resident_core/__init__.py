"""The serve's resident core: built once, then moved by the frames it fans out.

Owner 2026-11-22: "what builds the frame doesn't have to be rebuilt … that way
everything can be rpcs" (row RT-FU-THE-AGENT-LIST-FRAME-IS-REBUILT-WHOLE-FOR-
CHANGES-IT-COULD-APPLY-IN-PLACE). Module map:

* :mod:`.fold` — one frame's rows applied to a copy of a core (Eternia's fold, ported);
* :mod:`.holder` — the held core per profile root, its offset, the switch, ``observe``.
"""

from __future__ import annotations

from .holder import ResidentCore, drop, held, observe, resident_core_enabled, wait_through

__layer__ = "lanes"

__all__ = ["ResidentCore", "drop", "held", "observe", "resident_core_enabled", "wait_through"]
