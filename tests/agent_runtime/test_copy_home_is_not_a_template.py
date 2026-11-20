"""An independent copy's own profile home is not offered as a profile template.

Row ``RT-A-COPYS-OWN-PROFILE-IS-LISTED-AS-A-PROFILE-TEMPLATE`` (review w1118a.52
D3): ``available_profile_template_summaries`` lists every named servable
profile, so a copy made by ``create_independent_agent`` (persona
``agent_<digest>`` on profile ``agent-<digest>``) came back as a ``template_only``
row and Eternia's Presets count grew by one. What a template is belongs to the
runtime, judged by the persona store's record that pairs the copy with its home.

Row ``RT-A-DUPLICATE-YOU-MADE-MAY-ALSO-BE-LISTED-AS-A-PROFILE-TEMPLATE`` (review
w1118a.53 D10): a duplicate (a persona recording ``based_on``, on its own named
profile) is a copy the person made too, so its profile is no template either;
one predicate, ``persona_lifecycle.is_agent_copy``, serves the skip and
``agent_copy_delete._is_copy``.

Killing mutations: drop ``or profile_name in copy_homes`` in
``agent_runtime/snapshot/summaries.py::_available_persona_summary`` — the copy and
duplicate tests go red; drop the ``based_on`` arm of ``is_agent_copy`` — the
duplicate test goes red.
"""

from agent_runtime import snapshot as snapshot_mod

_DIGEST = "0123456789abcdef01234567"


class _Template:
    def __init__(self, name):
        self.name = name
        self.description = ""


class _Agent:
    def __init__(self, persona_id, profile, based_on=None):
        self.id = persona_id
        self.hermes_profile = profile
        self.based_on = based_on


def _profiles(monkeypatch, templates, agents):
    monkeypatch.setattr(
        snapshot_mod.summaries,
        "available_profile_templates",
        lambda: [_Template(name) for name in templates],
    )
    return [row["hermes_profile"] for row in snapshot_mod._available_persona_summary(agents)]


def test_a_copys_home_is_not_listed_while_its_sources_profile_still_is(monkeypatch):
    listed = _profiles(
        monkeypatch,
        ["base", f"agent-{_DIGEST}"],
        [_Agent("base_agent", "base"), _Agent(f"agent_{_DIGEST}", f"agent-{_DIGEST}")],
    )

    assert listed == ["base"]


def test_an_agent_named_profile_no_copy_owns_stays_a_template(monkeypatch):
    """The name alone decides nothing: a profile spelled like a copy's home that
    no copy persona owns (or one owned by an ordinary persona) is still listed."""
    listed = _profiles(
        monkeypatch,
        [f"agent-{_DIGEST}", "agent-ffffffffffffffffffffffff"],
        [_Agent("someone", "agent-ffffffffffffffffffffffff")],
    )

    assert listed == [f"agent-{_DIGEST}", "agent-ffffffffffffffffffffffff"]


def test_a_duplicates_profile_is_not_listed_while_its_sources_profile_still_is(monkeypatch):
    listed = _profiles(
        monkeypatch,
        ["base", "base-agent-twin"],
        [
            _Agent("base_agent", "base"),
            _Agent("base_agent_twin", "base-agent-twin", based_on={"id": "base_agent", "name": "Base Agent"}),
        ],
    )

    assert listed == ["base"]
