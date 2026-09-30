"""``agent_runtime.yaml_io`` reads with upstream's reader and writes what that reader reads back.

The private pyyaml-compatible resolver ``load`` carried until 2026-09-30 retired once a sweep of
every store, realm checkout and the tree found no artifact the two readers disagree on (lane
h14-yaml). These pin the two halves that retirement rests on: there is ONE reader, and every byte
the fork writes reloads identically under it — so nothing the fork publishes can bring the carry
back.
"""

from __future__ import annotations

import hermes_yaml

from agent_runtime import yaml_io


def test_load_is_upstreams_reader():
    assert yaml_io.load is hermes_yaml.safe_load


def test_every_scalar_the_reader_would_retype_round_trips_through_dump():
    # The scalars YAML 1.1 retypes when bare: flow-graph ``y`` keys, ``n``, exponent floats,
    # and the yes/no/on/off family, as keys and as values.
    doc = {
        "nodes": [{"id": "n_owner", "x": 10, "y": 20}],
        "viewport": {"x": -12.5, "y": 3.0, "zoom": 0.75},
        "n": "y",
        "values": ["y", "n", "Y", "N", "1e3", "on", "off", "yes", "no", "~", "null"],
    }

    assert yaml_io.load(yaml_io.dump(doc)) == doc
