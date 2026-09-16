"""Adapt upstream binary selection to pinned official release metadata."""
from __future__ import annotations

import json
import re
import time

from hermes_cli.local_runtime.binaries import resolve_assets, BinaryResolutionError
from .setup_io import official_get, fail

API = "https://api.github.com/repos/ggml-org/llama.cpp/releases"


class ReleaseCatalog:
    def __init__(self, getter=official_get):
        self.getter = getter
        self.cache = None
        self.cached_at = 0

    def release(self, tag):
        if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tag):
            fail("invalid_parameter", "Invalid release tag")
        return json.loads(self.getter(API + "/tags/" + tag))

    def list(self):
        if self.cache is not None and time.monotonic() - self.cached_at < 300:
            return self.cache
        releases = json.loads(self.getter(API + "?per_page=30"))
        if not isinstance(releases, list):
            fail("release_unavailable", "Unexpected official release response")
        result = []
        seen = set()
        for row in releases[:30]:
            if row.get("draft"):
                continue
            pointer = next((a for a in row.get("assets", []) if a.get("name") == "nightly-tag.txt"), None)
            stable_tag = None
            if pointer and not row.get("prerelease"):
                stable_tag = row.get("tag_name")
                raw = self.getter(pointer["browser_download_url"], max_bytes=128)
                tag = raw.decode("ascii").strip()
                row = self.release(tag)
            tag = row.get("tag_name", "")
            if tag in seen or not re.fullmatch(r"b[0-9]{1,10}", tag):
                continue
            seen.add(tag)
            variants = self.variants(row)
            if variants:
                result.append({"release_id": str(row["id"]), "tag": tag,
                               "stable_alias": stable_tag, "prerelease": bool(row.get("prerelease")),
                               "variants": variants})
        self.cache, self.cached_at = result, time.monotonic()
        return result

    @staticmethod
    def variants(row):
        assets = {a["name"]: a for a in row.get("assets", [])}
        variants = []
        for backend in ("cpu", "cuda"):
            try:
                names = resolve_assets(row["tag_name"], backend, os_name="win", arch="x64").assets
            except BinaryResolutionError:
                continue
            if not all(name in assets for name in names):
                continue
            rows = []
            for name in names:
                asset = assets[name]
                checksum = asset.get("digest") or ""
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum) or type(asset.get("size")) is not int or not 0 < asset["size"] < 8 * 1024**3:
                    break
                rows.append({"asset_id": str(asset["id"]), "name": name,
                             "size_bytes": asset["size"], "sha256": checksum[7:],
                             "url": asset["browser_download_url"]})
            else:
                variants.append({"variant_id": "win-x64-" + backend,
                                 "backend": backend, "artifacts": rows,
                                 "download_bytes": sum(a["size_bytes"] for a in rows)})
        return variants

    def pinned(self, tag, release_id, variant_id):
        row = self.release(tag)
        if str(row.get("id")) != release_id:
            fail("plan_changed", "The selected official release changed")
        return next((v for v in self.variants(row) if v["variant_id"] == variant_id), None)
