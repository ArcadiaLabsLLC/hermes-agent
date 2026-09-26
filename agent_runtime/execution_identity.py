"""Identify executing code independently of the shared profile/store identity."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

__layer__ = "stores"


def execution_identity() -> dict[str, str | int]:
    # Two forks may share one store. Versions may change in place; neither fact
    # authorizes dispatch to a different checkout.
    root = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    return {"version": 1, "execution_id": hashlib.sha256(root.encode("utf-8")).hexdigest()}
