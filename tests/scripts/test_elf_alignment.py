"""Android 16 KB pages: every shared library a phone ships has its LOAD segments aligned to 0x4000.

Row ``RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID`` (plan
``docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md`` §6, review w1118a.87
correction 2: the check runs where the bytes are). ``scripts/bundles/elf_alignment.py`` reads ELF program
headers; these build ELF files by hand, so no compiler or download is needed.
"""

from __future__ import annotations

import struct
import zipfile

from scripts.bundles import elf_alignment
from scripts.bundles.phone_wheels import alignment_problems


def _elf64(*aligns: int, loads: bool = True) -> bytes:
    """A little-endian ELF64 header and one program header per ``align`` (PT_LOAD, or PT_NOTE)."""
    phoff, phentsize = 64, 56
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", header, 0x20, phoff)
    struct.pack_into("<HH", header, 0x36, phentsize, len(aligns))
    phdrs = b"".join(struct.pack("<IIQQQQQQ", 1 if loads else 4, 5, 0, 0, 0, 0, 0, align) for align in aligns)
    return bytes(header) + phdrs


def _elf32(*aligns: int) -> bytes:
    phoff, phentsize = 52, 32
    header = bytearray(52)
    header[:6] = b"\x7fELF\x01\x01"
    struct.pack_into("<I", header, 0x1C, phoff)
    struct.pack_into("<HH", header, 0x2A, phentsize, len(aligns))
    return bytes(header) + b"".join(struct.pack("<IIIIIIII", 1, 0, 0, 0, 0, 0, 5, a) for a in aligns)


def test_load_alignments_are_read_from_both_elf_classes():
    assert elf_alignment.load_alignments(_elf64(0x4000, 0x10000)) == [0x4000, 0x10000]
    assert elf_alignment.load_alignments(_elf32(0x1000)) == [0x1000]
    assert elf_alignment.load_alignments(_elf64(0x10, loads=False)) == []


def test_one_low_segment_refuses_the_library():
    """Mutation: ``max`` for ``min`` in ``problem`` -> red (the 0x1000 segment passes)."""
    assert elf_alignment.problem("ok.so", _elf64(0x4000, 0x4000)) is None
    assert elf_alignment.problem("low.so", _elf64(0x4000, 0x1000)) == (
        "page_alignment: low.so has a LOAD segment aligned to 0x1000, below Android's 0x4000")


def test_a_file_that_is_not_elf_is_named_not_skipped():
    assert "cannot be read as ELF (not an ELF file)" in elf_alignment.problem("x.so", b"MZ not elf")
    assert "run past the end" in elf_alignment.problem("cut.so", _elf64(0x4000)[:80])


def test_a_wheel_and_a_pool_are_read_for_every_shared_library(tmp_path):
    wheel = tmp_path / "w-1-py3-none-android_24_x86_64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pkg/libok.so", _elf64(0x4000))
        archive.writestr("pkg/liblow.so.1", _elf64(0x1000))
        archive.writestr("pkg/__init__.py", "")
    assert elf_alignment.wheel_problems(wheel) == [
        f"page_alignment: {wheel.name}:pkg/liblow.so.1 has a LOAD segment aligned to 0x1000, below Android's 0x4000"]
    (tmp_path / "pool" / "opt").mkdir(parents=True)
    (tmp_path / "pool" / "opt" / "libz.so").write_bytes(_elf64(0x1000))
    (tmp_path / "pool" / "a.py").write_text("")
    assert elf_alignment.tree_problems(tmp_path / "pool") == [
        "page_alignment: opt/libz.so has a LOAD segment aligned to 0x1000, below Android's 0x4000"]


def test_the_committed_matcher_wheels_are_their_pins_and_16kb_aligned():
    """The wheels pinned by repo path (ripgrep's matcher) are in git, match their sha256 and load on a
    16 KB-page device. Mutation: change one hex digit of a pin's sha256 -> red (pinned_wheel_hash)."""
    assert alignment_problems() == []
