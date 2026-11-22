"""Android 16 KB pages: the ``LOAD`` alignment of every shared library a phone ships.

Fork-owned (row ``RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID``, plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`` §6). Android 15+
devices may run 16 KB pages; a library whose ``PT_LOAD`` segments are aligned below ``0x4000`` does not
load there. The Pillow pins were read aligned by hand (2026-11-17, ``phone_wheels.lock.json``'s comment);
this module is that read as code, and it runs where the bytes are:

* ``scripts/native/build_project_files_match.py`` refuses its own wheel when misaligned;
* :func:`scripts.bundles.phone_wheels.alignment_problems` reads every pinned wheel committed in the
  repository (the gate's ``page_alignment`` finding);
* the phone packager reads every ``.so`` in an Android pool after it installs (``pool_problems``), which
  covers the wheels pinned by URL (Flet's Pillow and its four libraries) and everything else installed.

Only ELF ``PT_LOAD`` program headers are read; a file that is not ELF is named, never skipped.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

#: Android's page-size floor for 16 KB devices.
MIN_ALIGN = 0x4000
_PT_LOAD = 1


def is_shared_library(name: str) -> bool:
    """``libfoo.so`` and ``libfoo.so.1``, the names a loader opens."""

    base = name.rsplit("/", 1)[-1]
    return base.endswith(".so") or ".so." in base


def load_alignments(data: bytes) -> list[int]:
    """The ``p_align`` of each ``PT_LOAD`` program header of the ELF file ``data``.

    Raises ``ValueError`` when ``data`` is not an ELF file or its program headers are cut short."""

    if len(data) < 16 or data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    wide = {1: False, 2: True}.get(data[4])
    order = {1: "<", 2: ">"}.get(data[5])
    if wide is None or order is None:
        raise ValueError("unknown ELF class or byte order")
    if wide:
        phoff, = struct.unpack_from(order + "Q", data, 0x20)
        phentsize, phnum = struct.unpack_from(order + "HH", data, 0x36)
        layout, type_at, align_at = order + "Q", 0, 0x30
    else:
        phoff, = struct.unpack_from(order + "I", data, 0x1C)
        phentsize, phnum = struct.unpack_from(order + "HH", data, 0x2A)
        layout, type_at, align_at = order + "I", 0, 0x1C
    if phoff + phentsize * phnum > len(data):
        raise ValueError("program headers run past the end of the file")
    out = []
    for i in range(phnum):
        base = phoff + i * phentsize
        p_type, = struct.unpack_from(order + "I", data, base + type_at)
        if p_type == _PT_LOAD:
            out.append(struct.unpack_from(layout, data, base + align_at)[0])
    return out


def problem(label: str, data: bytes) -> str | None:
    """A sentence naming ``label`` when its ``LOAD`` segments are aligned below ``MIN_ALIGN``; else None."""

    try:
        aligns = load_alignments(data)
    except ValueError as error:
        return f"page_alignment: {label} cannot be read as ELF ({error})"
    # MUTATION: compare with ``max`` instead of ``min`` and a library with one 4 KB segment among 16 KB ones
    # passes (test_elf_alignment: test_one_low_segment_refuses_the_library).
    low = min(aligns, default=0)
    if low < MIN_ALIGN:
        return f"page_alignment: {label} has a LOAD segment aligned to {low:#x}, below Android's {MIN_ALIGN:#x}"
    return None


def wheel_problems(wheel: Path) -> list[str]:
    """Every shared library in the wheel at ``wheel`` that is aligned below ``MIN_ALIGN``."""

    with zipfile.ZipFile(wheel) as archive:
        return [p for name in sorted(archive.namelist()) if is_shared_library(name)
                if (p := problem(f"{wheel.name}:{name}", archive.read(name)))]


def tree_problems(root: Path) -> list[str]:
    """Every shared library under ``root`` (an installed pool) aligned below ``MIN_ALIGN``."""

    return [p for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()
            and is_shared_library(path.name)
            if (p := problem(path.relative_to(root).as_posix(), path.read_bytes()))]
