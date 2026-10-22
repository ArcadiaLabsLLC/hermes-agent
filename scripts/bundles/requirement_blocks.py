"""The ``uv export`` requirements text as typed blocks: marker evaluation and a pool's selection.

Fork-owned (plan ``docs/agent-runtime-harness/planned/bundled-phone-pool-2026-10-22.md`` S2). One
block is a requirement line (``name==version ; marker \\`` or ``name @ url ; marker``) and its
indented ``--hash`` continuation lines. ``scripts/bundle_profile_package.evaluate_markers`` keeps the
blocks whose marker holds for a target; :func:`select_blocks` keeps the blocks a closure names and
refuses a selected block uv cannot install under ``--require-hashes``.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.bundle_profile_closure import _norm


@dataclass(frozen=True)
class Block:
    name: str  # normalised distribution name
    head: str  # the requirement without its marker (a URL pin keeps its ``@ url``)
    marker: str  # the PEP 508 marker, "" when none
    hashes: tuple[str, ...]  # the continuation lines, verbatim

    def holds(self, env: dict[str, str]) -> bool:
        from packaging.markers import Marker

        return not self.marker or Marker(self.marker).evaluate(env)

    def lines(self, *, marker: bool) -> list[str]:
        head = f"{self.head} ; {self.marker}" if marker and self.marker else self.head
        return [head + (" \\" if self.hashes else ""), *self.hashes]  # a URL pin has no hash lines


def requirement_blocks(requirements: str) -> list[Block]:
    """Split an exported requirements text into its blocks (comments and blank lines dropped)."""
    from packaging.requirements import Requirement

    raw: list[list[str]] = []
    for line in requirements.splitlines():
        if line.startswith((" ", "\t")):
            raw[-1].append(line)
        elif line.strip() and not line.startswith("#"):
            raw.append([line])
    blocks = []
    for first, *rest in raw:
        head, _, marker = first.rstrip(" \\").partition(" ; ")
        head = head.strip()
        blocks.append(Block(_norm(Requirement(head).name), head, marker.strip(), tuple(rest)))
    return blocks


def render(blocks: list[Block], *, marker: bool) -> str:
    return "\n".join(line for block in blocks for line in block.lines(marker=marker)) + "\n"


def select_blocks(blocks: list[Block], names: set[str]) -> tuple[str, list[str]]:
    """-> (the requirements text of the blocks ``names`` selects, markers and hashes intact; the
    refusals): a selected block with no hash lines is ``pool_pin_unhashed: <head>``, named here rather
    than left to uv's ``--require-hashes`` error. An unselected block is never judged."""
    wanted = {_norm(name) for name in names}
    kept = [block for block in blocks if block.name in wanted]
    refusals = [f"pool_pin_unhashed: {block.head}" for block in kept if not block.hashes]
    return render(kept, marker=True), refusals
