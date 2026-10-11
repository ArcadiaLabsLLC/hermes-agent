"""The ``[up-fp]`` ratchet: the fork's footprint in upstream files only goes down.

Plan: ``docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md``
§1 rule 2. The fixture is the ceiling AND the floor of record: a number above it
is a new or wider edit to an upstream file; a number below it is progress the
fixture has not been lowered to yet. A core change the operator wants raises the
fixture in the SAME commit with a ``reasons`` row — never silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.upstream_footprint import MANIFEST, count_footprint, ledger_rows, manifest_paths, measure, merge_ledger, read_manifest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "upstream_footprint.json"
NUMBERS = ("files", "deleted_lines", "heavy")


def test_the_upstream_footprint_never_rises_and_the_fixture_follows_it_down():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    manifest_base, _ = read_manifest(MANIFEST)
    assert fixture["base"] == manifest_base, (
        f"{MANIFEST.name} was refreshed to base {manifest_base} but {FIXTURE.name} is still "
        f"baselined at {fixture['base']}: re-measure and re-baseline both in one commit"
    )
    assert isinstance(fixture["reasons"], list)

    _, tree = measure(fixture["base"])
    risen = {n: (fixture[n], getattr(tree, n)) for n in NUMBERS if getattr(tree, n) > fixture[n]}
    assert not risen, (
        f"{tree.line()} — the fork's footprint in upstream files ROSE {risen} (fixture, tree). "
        "Make the edit additive / move it behind the plugin surface, or raise the fixture in "
        "this commit with a `reasons` row saying why the core change is wanted."
    )
    fell = {n: (fixture[n], getattr(tree, n)) for n in NUMBERS if getattr(tree, n) < fixture[n]}
    assert not fell, (
        f"{tree.line()} — the footprint FELL {fell} (fixture, tree); lower "
        f"{FIXTURE.name} to the tree's numbers in this commit (the list only shrinks)."
    )


NUMSTAT_Z = (
    "3\t0\thermes_cli/main.py\0"  # upstream, light, additive
    "150\t60\ttools/registry.py\0"  # upstream, heavy (210 > 200)
    "100\t100\tagent/prompt_builder.py\0"  # upstream, exactly 200: not heavy
    "-\t-\tassets/logo.png\0"  # upstream binary: touched, 0/0
    "0\t0\trun_agent.py\0"  # upstream mode-only change: touched
    "900\t400\tagent_runtime/serve.py\0"  # fork-only: not counted at all
)
MANIFEST_PATHS = [
    "hermes_cli/main.py",
    "tools/registry.py",
    "agent/prompt_builder.py",
    "assets/logo.png",
    "run_agent.py",
    "cli.py",  # upstream, untouched by the fork
]


def test_the_pure_counter_over_fake_numstat():
    fp = count_footprint(NUMSTAT_Z, MANIFEST_PATHS)
    assert fp.line() == "[up-fp] files=5 deleted_lines=160 heavy=1"
    by_path = {row.path: row for row in fp.rows}
    assert "agent_runtime/serve.py" not in by_path and "cli.py" not in by_path
    assert by_path["tools/registry.py"].heavy and not by_path["agent/prompt_builder.py"].heavy
    assert (by_path["assets/logo.png"].added, by_path["assets/logo.png"].deleted) == (0, 0)

    # Positive control: the same bytes with the fork-only file in the manifest DO count it.
    widened = count_footprint(NUMSTAT_Z, [*MANIFEST_PATHS, "agent_runtime/serve.py"])
    assert widened.line() == "[up-fp] files=6 deleted_lines=560 heavy=2"

    # The plain (non -z) numstat form counts identically.
    assert count_footprint(NUMSTAT_Z.replace("\0", "\n"), MANIFEST_PATHS) == fp


def test_the_manifest_is_the_merge_base_tree_union_upstream_tip():
    base = "agent/gone_upstream.py\0cli.py\0"
    tip = "cli.py\0tools/new_upstream.py\0"
    paths = manifest_paths(base, tip)
    # A file upstream deleted after the base stays upstream's: a fork edit to it is a
    # modify/delete conflict, and dropping it would under-count the footprint.
    assert "agent/gone_upstream.py" in paths
    assert "tools/new_upstream.py" in paths
    assert paths == sorted(set(paths)) and len(paths) == 3
    # Positive control: the counter DOES see a fork edit to the base-only file.
    assert count_footprint("3\t2\tagent/gone_upstream.py\0", paths).line() == "[up-fp] files=1 deleted_lines=2 heavy=0"


def test_the_ledger_merge_keeps_hand_edits_on_path():
    fp = count_footprint(NUMSTAT_Z, MANIFEST_PATHS)
    first = merge_ledger(None, fp)
    edited = first.replace(
        "| `tools/registry.py` | 150 | 60 | carry | unreviewed | - |",
        r"| `tools/registry.py` | 150 | 60 | upstream | P3 check_fn TTL cache \| perf | S3 |",
    )
    assert edited != first
    later = count_footprint(NUMSTAT_Z.replace("150\t60\ttools", "20\t5\ttools"), MANIFEST_PATHS[1:])
    merged = merge_ledger(edited, later)
    assert r"| `tools/registry.py` | 20 | 5 | upstream | P3 check_fn TTL cache \| perf | S3 |" in merged
    assert "hermes_cli/main.py" not in merged  # no longer in the footprint → row gone
    assert "| `run_agent.py` | 0 | 0 | carry | unreviewed | - |" in merged
    assert merged.startswith(first.split("| path")[0])  # preamble kept verbatim


def test_every_ledger_disposition_is_one_the_plan_names():
    """``carry-permanent`` is accepted (a ruled carry, still counted in ``files=``);
    anything else is a typo the detach read would silently miscount."""
    from scripts.upstream_footprint import DEFAULT_LEDGER, DISPOSITIONS, ledger_rows, unknown_dispositions

    text = DEFAULT_LEDGER.read_text(encoding="utf-8")
    rows = ledger_rows(text)
    assert len(rows) > 50, "the ledger parse found almost no rows — the walk is wrong"
    assert unknown_dispositions(text) == {}
    assert "carry-permanent" in DISPOSITIONS

    # Positive control: the same ledger with one row's disposition misspelt IS caught.
    path = next(iter(rows))
    old = f"| `{path}` | {rows[path]['added']} | {rows[path]['deleted']} | {rows[path]['disposition']} |"
    assert old in text
    bad = text.replace(old, f"| `{path}` | {rows[path]['added']} | {rows[path]['deleted']} | carry-permanant |", 1)
    assert unknown_dispositions(bad) == {path: "carry-permanant"}


def test_a_ruled_permanent_row_still_counts_in_files():
    fp = count_footprint(NUMSTAT_Z, MANIFEST_PATHS)
    ruled = merge_ledger(None, fp).replace(
        "| `hermes_cli/main.py` | 3 | 0 | carry |", "| `hermes_cli/main.py` | 3 | 0 | carry-permanent |"
    )
    remerged = merge_ledger(ruled, fp)
    assert "| `hermes_cli/main.py` | 3 | 0 | carry-permanent |" in remerged
    assert fp.files == 5  # the ruling settles the row, it does not remove it from the count


def test_no_row_under_a_code_tree_is_ruled_permanent():
    """Plan §1 rule 7: agent/, tools/, gateway/, hermes_cli/ never carry-permanent."""
    from scripts.upstream_footprint import DEFAULT_LEDGER, forbidden_permanent, ledger_rows

    text = DEFAULT_LEDGER.read_text(encoding="utf-8")
    assert forbidden_permanent(text) == []

    # Positive control: the same ledger with one hermes_cli/ row ruled permanent IS caught.
    path = next(p for p in ledger_rows(text) if p.startswith("hermes_cli/"))
    row = ledger_rows(text)[path]
    old = f"| `{path}` | {row['added']} | {row['deleted']} | {row['disposition']} |"
    bad = text.replace(old, f"| `{path}` | {row['added']} | {row['deleted']} | carry-permanent |", 1)
    assert bad != text
    assert forbidden_permanent(bad) == [path]


def test_no_ledger_row_is_unreviewed_or_unledgered():
    """D3.03: an upstream edit lands with its ledger reason. ``merge_ledger`` admits a new
    row as ``carry`` / ``unreviewed`` / ``-``; this is what reds on it, so a sync or merge
    job cannot land an upstream edit with no reason and no manifest entry."""
    from scripts.upstream_footprint import DEFAULT_LEDGER, unreviewed_rows

    text = DEFAULT_LEDGER.read_text(encoding="utf-8")
    assert unreviewed_rows(text) == [], (
        "these upstream edits carry no reviewed reason: write the ledger row (and the "
        "carried_prs.json entry when a PR carries the hunk) in the commit that lands them"
    )

    # Positive controls: a freshly merged row and the sync sweep's marker ARE caught.
    fresh = merge_ledger(None, count_footprint(NUMSTAT_Z, MANIFEST_PATHS))
    assert unreviewed_rows(fresh) == sorted(MANIFEST_PATHS[:5])
    path = next(iter(ledger_rows(text)))
    row = ledger_rows(text)[path]
    old = f"| `{path}` | {row['added']} | {row['deleted']} | {row['disposition']} | "
    assert old in text
    marked = text.replace(old, old + "additive (landed unledgered by `abc`): ", 1)
    assert unreviewed_rows(marked) == [path]


def test_every_reader_moved_to_load_config_readonly_says_so_in_the_ledger():
    """D3.06: the read-through derives its reader set from rows carrying ``READER_MOVED``, so a
    fork edit that ADDS a ``hermes_cli.config.load_config_readonly`` import to an upstream file
    must carry that spelling. Over-approximates a move (any added import), the safe direction."""
    import subprocess

    from scripts.upstream_footprint import DEFAULT_LEDGER, ROOT
    from tests._downstream.fork_readonly_readers import READER_MOVED, readonly_reader_moves

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = ledger_rows(DEFAULT_LEDGER.read_text(encoding="utf-8"))
    paths = sorted(path for path in rows if path.endswith(".py"))
    # The whole tree, narrowed by -G (no path argv: one naming hermes_cli/main.py trips the
    # live-system guard), then to the ledger's upstream files.
    diff = subprocess.run(
        ["git", "diff", "-U0", "--no-renames", "-Gload_config_readonly", fixture["base"]],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True, timeout=120,
    ).stdout
    moves = readonly_reader_moves(diff) & set(paths)
    assert len(moves) >= 5, f"the diff walk found {sorted(moves)} — too few; the walk is wrong"
    unflagged = sorted(path for path in moves if READER_MOVED not in rows[path]["reason"])
    assert unflagged == [], (
        f"these upstream files gained a load_config_readonly import but their ledger row does not "
        f"say {READER_MOVED!r}, so the read-through will not route upstream's load_config patches "
        f"to them: {unflagged}"
    )

    # Positive control: an added import in a fake diff IS found; context and removals are not.
    fake = ("+++ b/tools/x.py\n+    from hermes_cli.config import cfg_get, load_config_readonly\n"
            "+++ b/tools/y.py\n-    from hermes_cli.config import load_config_readonly\n")
    assert readonly_reader_moves(fake) == {"tools/x.py"}
