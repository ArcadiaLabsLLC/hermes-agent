"""Fork-owned pytest fixtures and hooks, moved out of upstream conftests (seam Stage 5)."""

#: ``tests/conftest.py`` as pytest registered it, handed over by the fork root ``conftest.py``
#: before it imports ``conftest_plugin`` (so the plugin never scans ``sys.modules`` for it).
root_conftest = None
