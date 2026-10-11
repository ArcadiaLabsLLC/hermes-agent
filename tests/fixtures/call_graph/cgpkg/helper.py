"""A one-hop helper over the root."""

from cgpkg.root import emit


def via(value):
    return emit(value)
