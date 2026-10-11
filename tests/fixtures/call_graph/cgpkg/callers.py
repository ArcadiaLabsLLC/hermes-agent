"""Every shape the call graph must resolve (or record as unresolved)."""

from cgpkg import helper, twin
from cgpkg.reexport import emit as re_emit
from cgpkg.root import emit

from .helper import via


def direct():
    emit(1)


def two_hop():
    via(1)


def two_hop_through_module_attribute():
    helper.via(1)


def through_a_reexport():
    re_emit(1)


def local_import():
    from cgpkg.root import emit as inner

    inner(1)


def same_name_other_module():
    twin.emit(1)


def cycle_a():
    cycle_b()


def cycle_b():
    cycle_a()


def unresolved(handler):
    handler.emit(1)
    mystery(1)  # noqa: F821
