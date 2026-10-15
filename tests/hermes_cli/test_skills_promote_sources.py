"""``harness skills promote``: the source table, the profile probe order, the refusal exit.

``tests/conftest.py`` points HERMES_HOME at a per-test tempdir, so the
``default`` profile's skills root is ``get_skills_dir()``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.skill_utils import get_skills_dir
from hermes_cli.harness_parts import skills_promotion_commands as promote


@pytest.fixture(autouse=True)
def _no_shared_override(monkeypatch):
    monkeypatch.delenv("HERMES_SHARED_SKILLS", raising=False)


def _package(base: Path, slug: str) -> Path:
    pkg = base.joinpath(*slug.split("/"))
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text(f"---\nname: {slug.split('/')[-1]}\n---\n# Body\n", encoding="utf-8")
    return pkg


def _args(**flags):
    return SimpleNamespace(**{"from_realm": None, "from_profile": None, "from_path": None, "move_source": False, **flags})


def test_an_exact_slug_beats_a_same_named_package_under_a_category():
    root = get_skills_dir()
    direct = _package(root, "tidy")
    _package(root, "misc/tidy")

    source, meta, move = promote._resolve_promotion_source(_args(from_profile="default"), "tidy")

    assert source == direct
    assert meta == {"kind": "profile", "profile": "default"}
    assert move is True


def test_a_bare_slug_under_one_category_resolves_to_it():
    nested = _package(get_skills_dir(), "misc/tidy")

    source, _, _ = promote._resolve_promotion_source(_args(from_profile="default"), "tidy")

    assert source == nested


def test_each_flag_reaches_its_own_source(tmp_path):
    authored = _package(tmp_path / "authored", "tidy")

    source, meta, move = promote._resolve_promotion_source(_args(from_path=str(authored)), "tidy")

    assert (source, meta["kind"], move) == (authored, "path", False)


def test_two_sources_are_refused_naming_the_flags_in_table_order(tmp_path):
    with pytest.raises(promote._PromotionSourceError) as caught:
        promote._resolve_promotion_source(_args(from_path=str(tmp_path), from_realm="r1"), "tidy")

    assert caught.value.code == "invalid_request"
    assert caught.value.safe_details["provided"] == ["--from-realm", "--from-path"]


def test_a_refused_promotion_exits_two(capsys, tmp_path):
    from hermes_cli.harness import build_parser

    parser = argparse.ArgumentParser()
    build_parser(parser.add_subparsers(dest="command"))
    authored = _package(tmp_path / "authored", "tidy")
    args = parser.parse_args(["harness", "skills", "promote", "bad slug!", "--from-path", str(authored), "--json"])

    assert args.func(args) == 2
    assert json.loads(capsys.readouterr().out)["action"] == "refused"
