"""The bundle closure's shipping rules: extras ship only when the profile names them, and a base
distribution may be omitted only when every import site of it tolerates its absence.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``classify`` ships every extra (``set(homes) & set(selected)`` -> ``homes``)
  -> ``test_an_extra_ships_only_when_the_profile_names_it`` red.
* ``_guarded_ids`` returns an empty set (no import is ever guarded)
  -> ``test_omitting_a_distribution_needs_every_import_site_guarded`` red (its positive control).
* ``_catches_import_error`` returns True for any handler
  -> ``test_omitting_a_distribution_needs_every_import_site_guarded`` red (a ``ValueError`` guard passes).
* ``_guarded_ids`` drops its ``TYPE_CHECKING`` arm
  -> ``test_an_import_under_type_checking_is_an_annotation_not_a_load`` red.
* ``_is_type_checking`` answers True for any test
  -> the same test red (its ``if DEBUG:`` positive control).
* the stand-in probe's ``answers`` returns True for any name
  -> ``test_an_omitted_distributions_stand_in_answers_only_the_names_it_binds`` red.
"""

from __future__ import annotations

import textwrap
import types

from scripts.bundle_profile_closure import (
    Graph,
    Walk,
    classify,
    module_index,
    omitted_import_sites,
    refusals,
    requested_extras,
    shipped_distributions,
    stand_in_answered,
)


def test_an_extra_ships_only_when_the_profile_names_it():
    base, extras = {"httpx"}, {"bedrock": {"boto3", "botocore"}, "anthropic": {"anthropic"}}
    direct = {"httpx": ["a"], "botocore": ["b"], "anthropic": ["c"], "pip": ["d"], "pillow-heif": ["e"]}

    rows = classify(direct, base, extras, selected=("anthropic",), omitted={"pillow-heif"})

    assert {d: r["status"] for d, r in rows.items()} == {
        "httpx": "ship", "anthropic": "ship", "botocore": "optional", "pip": "ship-undeclared",
        "pillow-heif": "omitted"}
    assert rows["botocore"]["extras"] == ["bedrock"]
    # Positive control: name the extra and the same distribution ships.
    assert classify(direct, base, extras, selected=("anthropic", "bedrock"), omitted=set())["botocore"]["status"] \
        == "ship"


def _tree(tmp_path, **modules):
    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    for name, body in modules.items():
        (root / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return module_index(tmp_path)


def _unguarded(tmp_path, **modules):
    index = _tree(tmp_path, **modules)
    walk = Walk(("pkg",), (), index, {"pkg"})
    manifest = types.SimpleNamespace(omitted_distributions=(
        {"distribution": "heavy", "imports": ("heavy",), "degrades": "x"},))
    sites = omitted_import_sites(manifest, walk)
    result = {"omitted_unguarded_import_sites": {d: [s for s in ss if not s["guarded"]] for d, ss in sites.items()},
              "omitted_but_required": [], "unknown_extras": []}
    return sites["heavy"], refusals(result)


def test_omitting_a_distribution_needs_every_import_site_guarded(tmp_path):
    guarded = """
        from contextlib import suppress

        def a():
            try:
                import heavy
            except ImportError:
                return None

        def b():
            with suppress(Exception):
                import heavy.sub
    """
    sites, problems = _unguarded(tmp_path / "ok", guarded=guarded)
    assert len(sites) == 2 and problems == []  # positive control: both sites seen, both guarded

    wrong_guard = """
        def c():
            try:
                import heavy
            except ValueError:
                return None
    """
    sites, problems = _unguarded(tmp_path / "bad", guarded=guarded, wrong=wrong_guard)
    assert len(sites) == 3
    assert len(problems) == 1 and "pkg.wrong" in problems[0]


def test_an_import_under_type_checking_is_an_annotation_not_a_load(tmp_path):
    annotated = """
        import typing
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            import heavy

        if typing.TYPE_CHECKING:
            from heavy import thing
    """
    sites, problems = _unguarded(tmp_path / "ok", annotated=annotated)
    assert sites and all(site["guarded"] for site in sites) and problems == []

    runs = """
        DEBUG = False

        if DEBUG:
            import heavy
    """
    sites, problems = _unguarded(tmp_path / "bad", runs=runs)
    assert len(sites) == 1 and len(problems) == 1  # positive control: any other ``if`` is a load


def test_a_target_excluded_or_guard_only_distribution_is_optional_not_undeclared():
    """``ptyprocess; sys_platform != 'win32'`` on Windows, and ``distlib`` behind try/except ImportError."""
    direct = {"ptyprocess": ["a"], "distlib": ["b"], "mystery": ["c"]}
    rows = classify(direct, set(), {}, selected=(), omitted=set(),
                    not_for_target={"ptyprocess"}, guarded_only={"distlib"})
    assert {d: r["status"] for d, r in rows.items()} == {
        "ptyprocess": "optional", "distlib": "optional", "mystery": "ship-undeclared"}
    # Positive control: without the two facts the same inputs ship undeclared.
    assert {r["status"] for r in classify(direct, set(), {}, selected=(), omitted=set()).values()} \
        == {"ship-undeclared"}


def test_a_requested_extra_of_a_base_declaration_ships_its_requirements():
    """``httpx[socks]``: ``socksio`` is loaded only for a SOCKS proxy, so no static import reaches it."""
    assert requested_extras()["httpx"] == {"socks"}
    lock = {"fakehttpx": {"dependencies": [{"name": "anyio"}],
                          "optional-dependencies": {"socks": [{"name": "fakesocksio"}]}}}
    assert "fakesocksio" in Graph(lock, {"fakehttpx": {"socks"}}).closure({"fakehttpx"})
    # Positive control: the same lock without the requested extra leaves it out.
    assert "fakesocksio" not in Graph(lock).closure({"fakehttpx"})
    # The installed-metadata path (the packager reads the pool's dist-info): the same rule.
    graph = Graph({}, {"httpx": {"socks"}})
    if "httpx" in graph.installed:
        assert "socksio" in graph.requires("httpx")
        assert "socksio" not in Graph({}).requires("httpx")


class _Graph:
    def __init__(self, requires):
        self._requires = requires

    def closure(self, roots):
        found, stack = set(), list(roots)
        while stack:
            name = stack.pop()
            if name not in found:
                found.add(name)
                stack.extend(self._requires.get(name, ()))
        return found


def test_a_dynamically_reached_base_distribution_ships():
    """``tzdata``: stdlib ``zoneinfo`` loads it, so the walk never reaches it."""
    classes = {"httpx": {"status": "ship"}, "botocore": {"status": "optional"}}
    graph = _Graph({"httpx": ["anyio"]})
    assert shipped_distributions(graph, classes, {"tzdata"}, {"httpx", "tzdata"}) == {"httpx", "anyio", "tzdata"}
    # Positive control: undeclared as a dynamic distribution, it does not ship.
    assert "tzdata" not in shipped_distributions(graph, classes, set(), {"httpx", "tzdata"})
    # A name that is not a base dependency never ships through this door, and is refused.
    assert "left-pad" not in shipped_distributions(graph, classes, {"left-pad"}, {"httpx"})
    result = {"omitted_unguarded_import_sites": {}, "omitted_but_required": [], "unknown_extras": [],
              "dynamic_not_base": ["left-pad"]}
    assert refusals(result) == ["packaging.dynamic_distributions names no base dependency: left-pad"]


def test_the_bundled_desktop_profile_ships_tzdata():
    from agent_runtime.bundle_profiles.manifest import load_profile

    assert "tzdata" in load_profile("bundled-desktop", validate=False).dynamic_distributions


def test_a_placeholder_requirement_is_never_followed_or_shipped():
    """A declared placeholder (once ``av`` under ``faster-whisper``) is never followed or shipped."""
    lock = {"fw": {"dependencies": [{"name": "fakeav"}, {"name": "numpy"}]}}
    assert Graph(lock, placeholders={"fakeav"}).closure({"fw"}) == {"fw", "numpy"}
    # Positive control: without the declaration the requirement ships.
    assert "fakeav" in Graph(lock).closure({"fw"})
    result = {"omitted_unguarded_import_sites": {}, "omitted_but_required": [], "unknown_extras": [],
              "placeholder_imported": ["fakeav"], "placeholder_is_base": ["httpx"]}
    assert refusals(result) == ["placeholder distribution fakeav is imported by kept first-party code",
                                "placeholder distribution httpx is a base dependency"]


def test_the_bundled_desktop_profile_stands_no_placeholder_in_since_faster_whisper_left():
    from agent_runtime.bundle_profiles.manifest import load_profile

    """PyAV's placeholder existed for faster-whisper, which the speech pack no longer ships (Whisper
    runs on onnx-asr). Mutation: restore the ``av`` entry -> red."""
    assert load_profile("bundled-desktop", validate=False).placeholder_distributions == {}


def test_the_declared_dynamic_imports_are_the_registries_own_tables():
    """``DYNAMIC_IMPORTS`` is a copy of two tables the AST walk cannot read; it is held to the
    tables themselves, asked at run time, in both directions."""
    from agent.secret_sources import registry as secret_registry
    from hermes_cli import plugins as plugin_context
    from scripts.bundle_profile_closure import DYNAMIC_IMPORTS

    registrars = plugin_context._SCOPED_PROVIDER_REGISTRARS
    assert set(DYNAMIC_IMPORTS["hermes_cli.plugins"]) == (
        {row[2] for row in registrars} | {row[3].partition(":")[0] for row in registrars})
    assert set(DYNAMIC_IMPORTS["agent.secret_sources.registry"]) == {row[0] for row in secret_registry._BUILTIN_SOURCES}
    assert set(DYNAMIC_IMPORTS) == {"hermes_cli.plugins", "agent.secret_sources.registry"}


def test_a_kept_registry_keeps_what_it_imports_by_name(tmp_path, monkeypatch):
    import scripts.bundle_profile_closure as closure

    for rel, text in {"reg.py": "TABLE = ('impl',)\n", "impl.py": "", "off/__init__.py": "", "other.py": ""}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    index = module_index(tmp_path)
    monkeypatch.setattr(closure, "DYNAMIC_IMPORTS", {"reg": ("impl", "off")})
    walk = Walk(("reg",), ("off",), index, {"reg", "impl", "off", "other"})
    assert walk.kept == {"reg", "impl"}
    assert walk.unguarded_into_pruned == [{"module": "reg", "line": 0, "target": "off"}]
    monkeypatch.setattr(closure, "DYNAMIC_IMPORTS", {})  # positive control: undeclared, unreached
    assert Walk(("reg",), ("off",), index, {"reg", "impl", "off", "other"}).kept == {"reg"}


def test_a_nested_web_package_is_indexed_and_the_top_level_frontend_is_not(tmp_path):
    for rel in ("plugins/web/provider.py", "web/build.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    index = module_index(tmp_path)
    assert "plugins.web.provider" in index
    assert "web.build" not in index


def test_an_omitted_distributions_stand_in_answers_only_the_names_it_binds(tmp_path):
    """The phone's ``openai`` shim answers upstream's unguarded ``from openai import OpenAI`` at run
    time (a child interpreter with ``openai`` unfindable); a name it does not bind stays refused, and
    the same site with no ``stand_in`` on the row is refused (positive control for the refusal)."""
    index = _tree(tmp_path, use="""
        from openai import OpenAI
        from openai.types.chat.chat_completion_message_tool_call import Function

        def later():
            from openai import NotBoundByTheShim
    """)
    walk = Walk(("pkg",), (), index, {"pkg"})
    row = {"distribution": "openai", "imports": ("openai",), "degrades": "x"}

    def judged(row):
        manifest = types.SimpleNamespace(omitted_distributions=(row,))
        sites = {d: [s for s in ss if not s["guarded"]] for d, ss in omitted_import_sites(manifest, walk).items()}
        answered = stand_in_answered(manifest, sites)
        left = {d: [s for s in ss if s["dotted"] not in answered.get(d, ())] for d, ss in sites.items()}
        return sorted(s["dotted"] for s in left["openai"])

    assert "openai.OpenAI" in judged(row)  # no stand-in: every unguarded site is refused
    assert judged({**row, "stand_in": "agent_runtime.provider_sdk_shim"}) == ["openai.NotBoundByTheShim"]


def test_a_handler_the_harness_parser_binds_by_name_is_an_import(tmp_path):
    """``hermes harness`` binds its handlers through ``lazy_module("…")`` (w3-perf), so
    the parser no longer imports them; the walk must still reach them, or a bundle
    could omit a distribution only a handler needs."""
    from scripts.bundle_profile_closure import _imports

    path = tmp_path / "wiring.py"
    path.write_text(
        'doctor = lazy_module("pkg.doctor_commands")\n'
        'other = lazy_widget("pkg.not_an_import")\n',  # positive control: another call is not an import
        encoding="utf-8",
    )
    reached = {(dotted, eager) for dotted, eager, _guarded, _line in _imports(path, "pkg.wiring", False)}
    assert reached == {("pkg.doctor_commands", False)}
