"""``hermes harness roots``: list, set, unset and migrate the machine roots.

Separate because the machine-root registry (``agent_runtime.machine_roots``) is
its own store; these verbs are its operator door and hold no rule of their own.
"""

from __future__ import annotations

from pathlib import Path

from hermes_cli.flag_binding import list_flag_or_empty
from agent_runtime.errors import NotFound
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    _require_yes,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_roots_list",
    "_cmd_roots_migrate",
    "_cmd_roots_set",
    "_cmd_roots_unset",
    "_machine_root_config_paths",
]


def _machine_root_config_paths(explicit: list[str] | None) -> list[Path]:
    """Config files the migration targets: explicit args, else every profile."""

    if explicit:
        return [Path(item) for item in explicit]
    from hermes_constants import get_default_hermes_root

    root = get_default_hermes_root()
    paths: list[Path] = []
    default_config = root / "config.yaml"
    if default_config.is_file():
        paths.append(default_config)
    profiles_dir = root / "profiles"
    if profiles_dir.is_dir():
        for child in sorted(profiles_dir.iterdir()):
            candidate = child / "config.yaml"
            if candidate.is_file():
                paths.append(candidate)
    return paths


def _cmd_roots_list(args) -> int:
    from agent_runtime.machine_roots import load_machine_roots, machine_roots_registry_paths

    roots = load_machine_roots(refresh=True)
    payload = roots.row()
    payload["registry_paths"] = [str(path) for path in machine_roots_registry_paths()]
    _print_stage42(_object_envelope("machine_roots", payload), args=args, default_output="json")
    return 0


def _cmd_roots_set(args) -> int:
    from agent_runtime.machine_roots import load_machine_roots, write_machine_roots

    path = Path(str(args.path)).expanduser()
    if not path.is_absolute():
        return emit_harness_error(
            ValueError(f"'{args.path}' is not absolute"),
            args=args,
            code="invalid_payload",
            message="A machine root must be an ABSOLUTE local path — relative bindings are exactly the portability bug this replaces.",
        )
    if not path.exists() and not getattr(args, "allow_missing", False):
        return emit_harness_error(
            FileNotFoundError(str(path)),
            args=args,
            code="not_found",
            message=f"{path} does not exist on this machine. Re-run with --allow-missing to bind it anyway.",
        )
    roots = dict(load_machine_roots(refresh=True).roots)
    roots[str(args.name)] = str(path)
    result = write_machine_roots(roots, dry_run=bool(getattr(args, "dry_run", False)))
    _print_stage42(_object_envelope("machine_roots", result), args=args, default_output="json")
    return 0


def _cmd_roots_unset(args) -> int:
    from agent_runtime.machine_roots import load_machine_roots, write_machine_roots

    roots = dict(load_machine_roots(refresh=True).roots)
    if str(args.name) not in roots:
        return emit_harness_error(
            NotFound(str(args.name)), args=args, message=f"Machine root '{args.name}' is not bound."
        )
    roots.pop(str(args.name))
    result = write_machine_roots(roots, dry_run=bool(getattr(args, "dry_run", False)))
    _print_stage42(_object_envelope("machine_roots", result), args=args, default_output="json")
    return 0


def _cmd_roots_migrate(args) -> int:
    from agent_runtime.machine_roots import MachineRoots, load_machine_roots
    from agent_runtime.machine_roots_migration import (
        apply_config_migration,
        plan_config_migration,
        suggest_roots_from_configs,
        unmapped_absolute_paths,
    )

    if not _require_yes(args):
        return 8
    config_paths = _machine_root_config_paths(list_flag_or_empty(args, "configs"))
    if not config_paths:
        return emit_harness_error(
            NotFound("config.yaml"), args=args, message="No profile config.yaml files found to migrate."
        )

    explicit: dict[str, str] = {}
    for item in list_flag_or_empty(args, "root"):
        if "=" not in str(item):
            return emit_harness_error(
                ValueError(str(item)), args=args, code="invalid_payload", message=f"--root expects NAME=PATH, got '{item}'"
            )
        name, _sep, value = str(item).partition("=")
        explicit[name.strip()] = str(Path(value.strip()).expanduser())

    bindings = dict(load_machine_roots(refresh=True).roots)
    bindings.update(suggest_roots_from_configs(config_paths))
    bindings.update(explicit)
    roots = MachineRoots(roots=bindings)

    plan = plan_config_migration(
        config_paths,
        roots,
        add_platform_gates=not bool(getattr(args, "no_platform_gates", False)),
    )
    outcome = apply_config_migration(plan, dry_run=bool(getattr(args, "dry_run", False)))
    payload = plan.row()
    payload["applied"] = outcome
    payload["unmapped_absolute_paths"] = unmapped_absolute_paths(config_paths, roots)
    _print_stage42(_object_envelope("machine_roots_migration", payload), args=args, default_output="json")
    return 0 if plan.safe else 1
