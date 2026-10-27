"""The ``prometheus`` poll source: one instant query against the HTTP API.

``GET <base_url>/api/v1/query?query=<q>`` (plan §3: the API directly), or through
``kubectl proxy`` (``via: kube_proxy``, L4): the base is
``feed.kube_proxy_base_url`` on loopback port 8001, built from validated Kubernetes
names, so its loopback read needs no ``allow_private_network`` — no part of the
host is the manifest's. A ``scalar`` result is its value; a ``vector`` must hold
exactly one sample — zero is ``no_series`` and more than one is
``ambiguous_series``, because picking one of several series would be a guess.
Prometheus writes sample values as strings, ``NaN`` and ``+Inf`` included; a
non-finite value is ``not_a_number``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from ..feed import kube_proxy_base_url
from ..shapes import prometheus_skeleton
from .transport import ReadReason, ReadResult, fetch_json, unavailable

__layer__ = "lanes"


def _sample_value(pair: Any) -> float | None:
    if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[1], str):
        return None
    try:
        number = float(pair[1])
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _value_of(data: Any) -> ReadResult:
    kind = data.get("resultType") if isinstance(data, dict) else None
    result = data.get("result") if isinstance(data, dict) else None
    if kind == "scalar":
        pair = result
    elif kind == "vector" and isinstance(result, list):
        if not result:
            return unavailable(ReadReason.NO_SERIES, 200)
        if len(result) > 1:
            return unavailable(ReadReason.AMBIGUOUS_SERIES, 200)
        pair = result[0].get("value") if isinstance(result[0], dict) else None
    else:
        return unavailable(ReadReason.QUERY_FAILED, 200)
    number = _sample_value(pair)
    if number is None:
        return unavailable(ReadReason.NOT_A_NUMBER, 200)
    return ReadResult(value=number, reason=ReadReason.OK, http_status=200)


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None) -> ReadResult:
    source = feed["source"]
    proxied = "via" in source
    base = kube_proxy_base_url(source) if proxied else source["base_url"]
    url = base.rstrip("/") + "/api/v1/query"
    document, failed = fetch_json(url, headers=headers, params={"query": source["query"]},
                                  allow_private=proxied or feed.get("allow_private_network", False),
                                  client=client, resolver=resolver)
    if failed is not None:
        return failed
    if not isinstance(document, dict) or document.get("status") != "success":
        result = unavailable(ReadReason.QUERY_FAILED, 200)
    else:
        result = _value_of(document.get("data"))
    return replace(result, shape=prometheus_skeleton(document))
