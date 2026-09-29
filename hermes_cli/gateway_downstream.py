"""Fork-owned half of ``hermes_cli/gateway.py`` (class G11): the managed-interpreter
resolver the Windows launcher persists, the POSIX-only uid guard, the boot's
home-resolution receipt, and the profile matcher the pid scan uses.

Moved out of the upstream module by lane FOOTPRINT-DROP (2026-09-27); ``gateway.py``
re-exports these names in one import line so callers and patches keep spelling them
``gateway.<name>``, and every upstream name is read through the module at call time.
``_detect_venv_dir`` is the RECORDED PARALLEL of upstream ``_pm_runtime_venv_dir``
(upstream-footprint-ledger row ``hermes_cli/gateway.py``). Retires with the G11 PR.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _gw():
    from hermes_cli import gateway

    return gateway


def _detect_venv_dir() -> Path | None:
    """Active virtualenv dir: ``sys.prefix``, then ``VIRTUAL_ENV`` (uv sets it without changing
    sys.prefix), then .venv/venv under PROJECT_ROOT; None if none found.

    RECORDED PARALLEL (upstream merge 2026-09-25, design note §5 Q4): upstream deleted this in
    favour of :func:`_pm_runtime_venv_dir` (``pm.environments.selected_venv``). The launcher's
    install is a venv OUTSIDE the checkout (``.hermes/venvs/hermes-agent``), which pm's
    committed-environment contract does not find, and ``hermes update`` was not exercised on the
    merged tree. Retire condition: the launcher's install moves onto pm bundles.
    """
    candidates: list[Path] = []
    if sys.prefix != sys.base_prefix:
        candidates.append(Path(sys.prefix))
    if os.environ.get("VIRTUAL_ENV"):
        candidates.append(Path(os.environ["VIRTUAL_ENV"]))
    root = _gw().PROJECT_ROOT
    candidates += [root / ".venv", root / "venv"]
    return next((venv for venv in candidates if venv.is_dir()), None)


def _venv_interpreter(venv: Path) -> Path:
    """The interpreter path inside ``venv`` for this platform."""
    from hermes_constants import venv_python_path

    return venv_python_path(venv, windows=_gw().is_windows())


class ManagedPythonUnavailable(RuntimeError):
    """No interpreter could be resolved as the one Hermes is installed into."""


def resolve_managed_python() -> str:
    """Return the interpreter Hermes is INSTALLED INTO — the one updates sync.

    Same layout knowledge as :func:`_detect_venv_dir` (this process's venv via
    ``sys.prefix``, then ``$VIRTUAL_ENV``, then the ``.venv``/``venv``
    checkout layouts that ``_venv_core_imports_healthy`` and
    ``managed_uv._default_live_venv`` already treat as the install). It
    deliberately does NOT introduce a second notion of "the managed
    environment" — there was no accessor for it at all, which is why the
    launcher renderer had nothing better to ask.

    The difference from :func:`get_python_path` is the fallback, and it is the
    whole point: ``get_python_path`` ends in ``sys.executable``, which is
    right for ephemeral work in a dev checkout and wrong for anything
    persisted. Stamped into a launcher artifact, that fallback silently pins
    whichever interpreter happened to run the install — the gateway then boots
    for months against a package set nobody maintains, and the failure only
    surfaces as a missing-module traceback at some later boot.

    Raises :class:`ManagedPythonUnavailable` with a single-line reason naming
    what was looked for. Callers persisting an artifact must let it propagate
    rather than degrade to a guess.
    """
    gw = _gw()
    venv = gw._detect_venv_dir()
    if venv is None:
        raise ManagedPythonUnavailable(
            "no Hermes virtualenv found (looked at sys.prefix, $VIRTUAL_ENV, "
            f"{gw.PROJECT_ROOT / '.venv'}, {gw.PROJECT_ROOT / 'venv'})"
        )
    interpreter = gw._venv_interpreter(venv)
    if not interpreter.exists():
        raise ManagedPythonUnavailable(
            f"virtualenv {venv} has no interpreter at {interpreter}"
        )
    return str(interpreter)


def _posix_uid_or_zero() -> int:
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if callable(getuid) else 0


def _emit_gateway_home_receipt(emit_diag) -> dict:
    """Build and emit this boot's home-resolution receipt. Returns the receipt.

    Split out of :func:`run_gateway` so it is testable without booting a
    gateway — ``run_gateway`` guards a live process and cannot be called in a
    unit test.
    """
    from hermes_constants import get_default_hermes_root, get_hermes_home

    from hermes_cli.gateway_home_receipt import (
        RESOLUTION_DEFAULT,
        RESOLUTION_ENV_VAR,
        build_gateway_home_receipt,
        env_key_names,
        suspicious_home_row,
        wrapper_profiles,
    )

    home = Path(get_hermes_home())
    receipt = build_gateway_home_receipt(
        hermes_home=home,
        resolution=os.environ.get(RESOLUTION_ENV_VAR) or RESOLUTION_DEFAULT,
        env_keys=env_key_names(home / ".env"),
    )
    emit_diag("gateway.home_resolution", **receipt)
    _gw().logger.info("Gateway home resolution: %s", receipt["summary"])

    suspicious = suspicious_home_row(
        receipt,
        installed_wrapper_profiles=wrapper_profiles(
            Path(get_default_hermes_root()) / "profiles"
        ),
    )
    if suspicious is not None:
        emit_diag("gateway.home_suspicious", **suspicious)
        _gw().logger.warning(
            "%s — %s", suspicious["summary"], suspicious["fix_hint"]
        )
    return receipt


