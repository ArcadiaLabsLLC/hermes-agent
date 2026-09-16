"""Bounded, owned filesystem and network operations for console-approved setup."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlparse
import zipfile

import requests

from .config import LocalLlamaError
from .process import OwnedProcess

MAX_EXPANDED = 8 * 1024**3
HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com",
         "objects.githubusercontent.com"}


def fail(reason, message):
    raise LocalLlamaError(reason, message, code=-32000)


def host_path(value, *, directory=False):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        fail("invalid_path", "Enter an absolute path on the Hermes host")
    path = Path(value)
    if not path.is_absolute() or value.startswith(("\\\\", "//")):
        fail("invalid_path", "Use an absolute local host path; network paths are not supported")
    for part in path.parts[1:]:
        if part in (".", "..") or ":" in part or part.endswith((".", " ")):
            fail("invalid_path", "The path contains an unsafe component")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            fail("invalid_path", "The path contains a reserved filename")
    for parent in [path, *path.parents]:
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            fail("unsafe_path", "Links and junctions cannot be used for managed installation")
    if not path.exists() or (directory and not path.is_dir()):
        fail("missing_file", "This location does not exist on the Hermes host")
    return path.resolve()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def official_get(url, *, max_bytes=4 * 1024**2, destination=None, expected_size=None,
                 tick=lambda *_: None, cancelled=lambda: False):
    """No ambient credentials, arbitrary destinations, redirects or unbounded bodies."""
    deadline = time.monotonic() + 1800
    with requests.Session() as session:
        # Normal trusted proxies/CA configuration remains usable. No bearer/netrc auth.
        session.auth = lambda request: request
        for _ in range(6):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
                fail("unsafe_download", "Release download left the official GitHub hosts")
            response = session.get(url, stream=True, timeout=(10, 30), allow_redirects=False,
                                   headers={"Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com" else "application/octet-stream"})
            if response.is_redirect:
                url = response.headers.get("Location", "")
                response.close()
                continue
            try:
                if response.status_code in (403, 429):
                    fail("rate_limited", "GitHub limited release requests; try again later")
                if response.status_code != 200:
                    fail("release_unavailable", "The official release asset is unavailable")
                data = bytearray()
                stream = Path(destination).open("xb") if destination is not None else None
                try:
                    count = 0
                    for chunk in response.iter_content(1024 * 256):
                        if cancelled():
                            fail("cancelled", "Installation cancelled")
                        if time.monotonic() > deadline:
                            fail("timeout", "Release download timed out")
                        count += len(chunk)
                        if count > max_bytes:
                            fail("download_too_large", "Release exceeds its approved size limit")
                        if stream:
                            stream.write(chunk)
                        else:
                            data.extend(chunk)
                        tick(count, expected_size)
                    if expected_size is not None and count != expected_size:
                        fail("size_mismatch", "Downloaded bytes do not match the approved asset")
                    if stream:
                        stream.flush()
                        os.fsync(stream.fileno())
                    return bytes(data)
                finally:
                    if stream:
                        stream.close()
            finally:
                response.close()
        fail("unsafe_download", "Too many release redirects")


def extract_zip(archive, destination, *, remaining=MAX_EXPANDED, tick=lambda *_: None,
                cancelled=lambda: False):
    destination = host_path(str(destination), directory=True)
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        total = sum(m.file_size for m in members)
        if len(members) > 20000 or total > remaining:
            fail("unsafe_archive", "Archive exceeds its approved extraction limit")
        names = set()
        done = 0
        for member in members:
            if cancelled():
                fail("cancelled", "Installation cancelled")
            name = member.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if not parts or name.startswith("/") or any(p in ("..", ".") or ":" in p or p.endswith((".", " ")) or any(ord(c) < 32 for c in p) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts):
                fail("unsafe_archive", "Archive contains an unsafe filename")
            key = name.rstrip("/").casefold()
            mode = member.external_attr >> 16
            if key in names or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                fail("unsafe_archive", "Archive contains links or duplicate filenames")
            names.add(key)
            if member.file_size > max(1, member.compress_size) * 1000:
                fail("unsafe_archive", "Archive expansion ratio is unsafe")
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            host_path(str(target.parent), directory=True)
            if member.is_dir():
                target.mkdir(exist_ok=True)
                continue
            # Never overwrite a file supplied by another artifact in the bundle.
            with source.open(member) as incoming, target.open("xb") as outgoing:
                written = 0
                while chunk := incoming.read(1024 * 256):
                    if cancelled():
                        fail("cancelled", "Installation cancelled")
                    written += len(chunk)
                    done += len(chunk)
                    if written > member.file_size or done > remaining:
                        fail("unsafe_archive", "Archive exceeded its declared size")
                    outgoing.write(chunk)
                    tick(done, total)
    return done


def probe(executable):
    """Explicit validation uses the same kill-on-close owner as inference children."""
    executable = host_path(str(executable))
    if not executable.is_file():
        fail("missing_file", "Choose the llama-server executable")
    from hermes_cli.local_runtime.binaries import server_binary
    if server_binary(executable.parent).resolve() != executable:
        fail("unsupported_binary", "Choose a llama-server executable")
    outputs = []
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_")}
    for flag in ("--version", "--help"):
        with tempfile.TemporaryFile() as output:
            with OwnedProcess([str(executable), flag], cwd=executable.parent, output=output, env=clean_env) as owned:
                deadline = time.monotonic() + 10
                while owned.poll() is None:
                    if os.fstat(output.fileno()).st_size > 256 * 1024 or time.monotonic() > deadline:
                        fail("probe_timeout", "Binary validation exceeded its time or output limit")
                    time.sleep(.02)
                if owned.poll() != 0:
                    fail("unsupported_binary", "llama-server could not start; check its runtime dependencies")
            output.seek(0)
            outputs.append(output.read(256 * 1024).decode("utf-8", errors="replace"))
    required = ("--models-dir", "--models-preset", "--models-max", "--no-models-autoload")
    if not all(flag in outputs[1] for flag in required):
        fail("unsupported_binary", "This llama.cpp build lacks managed router support")
    return {"executable_path": str(executable), "version": outputs[0].strip()[:512],
            "sha256": digest(executable), "compatibility": "compatible", "capabilities": list(required)}
