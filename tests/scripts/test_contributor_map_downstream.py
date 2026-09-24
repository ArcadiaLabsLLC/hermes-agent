"""Fork-owned tests moved out of ``tests/scripts/test_contributor_map.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

import release  # noqa: E402


def test_case_variant_directory_preserves_both_exact_identities(tmp_path, monkeypatch):
    import audit_pr_attribution

    directory = tmp_path / "contributors" / "emails"
    variants = directory / "case-variants"
    variants.mkdir(parents=True)
    (directory / "agent@agents-Mac-mini.local").write_text("momomojo\n")
    (variants / "agent@Agents-Mac-mini.local").write_text("skip-agent\n")
    assert release._load_contributor_dir(directory) == {
        "agent@agents-Mac-mini.local": "momomojo",
        "agent@Agents-Mac-mini.local": "skip-agent",
    }
    monkeypatch.setattr(audit_pr_attribution, "REPO_ROOT", tmp_path)
    assert audit_pr_attribution.is_mapped("agent@agents-Mac-mini.local")
    assert audit_pr_attribution.is_mapped("agent@Agents-Mac-mini.local")
    assert not audit_pr_attribution.is_mapped("agent@AGENTS-Mac-mini.local")
