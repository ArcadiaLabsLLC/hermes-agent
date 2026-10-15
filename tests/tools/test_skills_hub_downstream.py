"""Fork-owned half of ``tests/tools/test_skills_hub.py`` (lane FOOTPRINT-DROP 2026-09-27).

The fork's ``tools/skills_hub_official.py`` keys an optional-skill bundle by POSIX-relative
paths on every host (open upstream PR #121643, ``up/win-remote-posix-paths``). Upstream's
``test_fetch_preserves_binary_assets`` looks the keys up with ``os.path.join``, which is the
same string only off Windows; there it is a strict xfail by id
(``tests/_downstream/id_markers/upstream_reds.py``) and this test pins the POSIX keys.
"""

from tools.skills_hub_official import OptionalSkillSource


def test_fetch_keys_binary_assets_by_posix_path(tmp_path):
    optional_root = tmp_path / "optional-skills"
    skill_dir = optional_root / "mlops" / "models" / "neutts"
    (skill_dir / "assets" / "neutts-cli" / "samples").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: neutts\ndescription: test\n---\n\nBody\n",
        encoding="utf-8",
    )
    wav_bytes = b"RIFF\x00\x01fakewav"
    (skill_dir / "assets" / "neutts-cli" / "samples" / "jo.wav").write_bytes(
        wav_bytes
    )
    (skill_dir / "assets" / "neutts-cli" / "samples" / "jo.txt").write_bytes(
        b"hello\n"
    )
    pycache_dir = skill_dir / "assets" / "neutts-cli" / "src" / "neutts_cli" / "__pycache__"
    pycache_dir.mkdir(parents=True)
    (pycache_dir / "cli.cpython-312.pyc").write_bytes(b"junk")

    src = OptionalSkillSource()
    src._optional_dir = optional_root

    bundle = src.fetch("official/mlops/models/neutts")

    assert bundle is not None
    assert bundle.files["assets/neutts-cli/samples/jo.wav"] == wav_bytes
    assert bundle.files["assets/neutts-cli/samples/jo.txt"] == b"hello\n"
    assert "assets/neutts-cli/src/neutts_cli/__pycache__/cli.cpython-312.pyc" not in bundle.files
