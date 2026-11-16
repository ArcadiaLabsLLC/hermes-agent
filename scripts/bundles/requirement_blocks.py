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


def seed_union(plans: dict[str, tuple[set[str], list[str]]]) -> tuple[set[str], list[str]]:
    """One ``distribution_plans`` job's answer -> (every selection's ``needed``, unioned; the refusals)."""
    return set().union(*(needed for needed, _ in plans.values())), [r for _, refused in plans.values() for r in refused]


def pure_wheel_blocks(blocks: list[Block], pure_wheels, lock: dict[str, dict]) -> tuple[list[Block], list[str]]:
    """``packaging.pure_wheels``: each named block keeps only the hash of its ``none-any`` wheel (from
    ``uv.lock``), so ``uv pip install --require-hashes`` can install nothing else — the compiled wheel a
    target also has is never the one that ships. -> (the blocks, refusals): a named distribution with no
    pure wheel in the lock is ``pure_wheel_missing: <name>``."""
    wanted = {_norm(name) for name in pure_wheels}
    out, refusals = [], []
    for block in blocks:
        if block.name not in wanted:
            out.append(block)
            continue
        pure = {wheel.get("hash", "") for wheel in (lock.get(block.name) or {}).get("wheels", [])
                if wheel.get("url", "").endswith("-none-any.whl") and wheel.get("hash")}
        kept = tuple(line for line in block.hashes if line.strip().removeprefix("--hash=").rstrip(" \\") in pure)
        if not kept:
            refusals.append(f"pure_wheel_missing: {block.name}")
            continue
        out.append(Block(block.name, block.head, block.marker, tuple(
            line.rstrip(" \\") + (" \\" if index < len(kept) - 1 else "") for index, line in enumerate(kept))))
    return out, refusals


def closure_requirements(requirements: str, names: set[str], refused: list[str], env: dict[str, str],
                         seed_sites, pure_wheels=(), lock: dict[str, dict] | None = None) -> tuple[str, list[str], str]:
    """``PoolScope.CLOSURE``'s pool: the export's blocks whose marker holds for ``env``, narrowed to
    ``names`` -> (the requirements text, every problem line, the ``pool scope:`` receipt line).
    Markers are evaluated BEFORE selecting, so another platform's hashless pin is never judged.
    ``pure_wheels`` keeps those distributions to their pure wheel (:func:`pure_wheel_blocks`)."""
    blocks = [block for block in requirement_blocks(requirements) if block.holds(env)]
    blocks, impure = pure_wheel_blocks(blocks, pure_wheels, lock or {})
    text, unhashed = select_blocks(blocks, names)
    problems = [*(f"closure refusal: {line}" for line in refused), *unhashed, *impure]
    kept = f"{len(requirement_blocks(text))} of {len(blocks)} export blocks"
    return text, problems, f"pool scope: closure — {kept} (seed: {', '.join(map(str, seed_sites))})"
