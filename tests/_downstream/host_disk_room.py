"""Give the ids the table marks a disk with room (lane r-gateway, 2026-10-17).

``gateway.readiness._probe_disk`` reports ``degraded`` at 90 % used, and the readiness
status is ``ok`` only when every probe is. Upstream's
``test_collect_runtime_readiness_reports_healthy_local_runtime`` asserts that ``ok`` while
reading the REAL volume under ``tmp_path``: the fork's test-tmp root sits on a drive that
was 93.6 % used (238 GiB free) on 2026-10-17, so the test was red on the box, never in
the code. For a marked test ``shutil.disk_usage`` reports a half-used volume; the probe,
its threshold and the aggregate still run unchanged.
"""

from __future__ import annotations

import shutil

import pytest

from tests._downstream.id_markers.reasons import HOST_DISK_HAS_ROOM_MARK as _MARK

_GIB = 1024 ** 3
_HALF_USED = (100 * _GIB, 50 * _GIB, 50 * _GIB)  # total, used, free


@pytest.fixture(autouse=True)
def _host_disk_has_room(request, monkeypatch):
    if request.node.get_closest_marker(_MARK) is None:
        return
    usage = type(shutil.disk_usage("."))
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: usage(*_HALF_USED))


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_host_disk_room(config):  # pytest hook
    config.addinivalue_line(
        "markers",
        f"{_MARK}: shutil.disk_usage reports a half-used volume, so a probe of the real "
        "test-tmp drive cannot red the test (applied by id from tests/_downstream/id_markers/).",
    )
