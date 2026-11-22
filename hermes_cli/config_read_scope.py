"""Context-local read projection; explicit config writes keep the persisted view."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

_projection = ContextVar("hermes_readonly_config_projection", default=None)
#: ``(section, fold)`` pairs, outermost first: each folds one top-level section of the read view.
_section_folds: ContextVar[tuple] = ContextVar("hermes_readonly_config_section_folds", default=())


@contextmanager
def readonly_config_scope(project):
    token = _projection.set(project)
    try:
        yield
    finally:
        _projection.reset(token)


@contextmanager
def readonly_section_scope(section: str, fold):
    """Fold ONE top-level section of every read in this context: ``fold(section_dict) -> dict``.

    Shallow by design (a new top-level dict and a new section dict per read, never a deepcopy of the
    whole config), and nested scopes compose, outermost first. Sole caller:
    ``agent_runtime.approval_surface_policy.scoped_approval_policy`` (a dispatched helper's approval
    wait and its lead's deny globs, row RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS).
    """
    token = _section_folds.set(_section_folds.get() + ((section, fold),))
    try:
        yield
    finally:
        _section_folds.reset(token)


def project_readonly_config(config):
    """The read view: the context's projection, then its section folds, then a bundled install's
    shipped switches (``config_switches.with_install_switches``), last so no projection can turn one
    back on."""
    from hermes_cli.config_switches import with_install_switches

    project = _projection.get()
    view = config if project is None else project(deepcopy(config))
    folds = _section_folds.get()
    if folds and isinstance(view, dict):
        view = dict(view)
        for section, fold in folds:
            current = view.get(section)
            view[section] = fold(dict(current) if isinstance(current, dict) else {})
    return with_install_switches(view)
