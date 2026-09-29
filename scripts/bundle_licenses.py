"""Licences and a CycloneDX SBOM for one bundle output (plan D4).

Fork-owned (bundled desktop). :mod:`scripts.bundle_profile_package` calls
:func:`write_licence_records` for every output it builds — the core bundle and
each engine pack — and its verify step calls :func:`licence_problems`. Each
output directory gets::

    licenses.json   one row per shipped component: distribution, version,
                    licence expression, the licence files copied into this
                    output (output-relative paths), source URL, the SHA-256 of
                    the wheel it was installed from, and ``review`` + reasons
    sbom.cdx.json   CycloneDX 1.5 JSON: the same components, purl + hashes

The core output also lists the interpreter (placed by the installer, pinned in
``agent_runtime/bundle_profiles/interpreters.lock.json``) and first-party
``hermes-agent``.

``review: true`` marks a licence a human must rule on before release: any
GPL-family (GPL / LGPL / AGPL), non-commercial, proprietary or unknown licence,
a known copyleft component compiled into a permissively-labelled wheel
(:data:`EMBEDDED_COMPONENTS`), or a distribution whose licence text is not in
the output. Flagging never removes anything: what ships is the closure's
decision, not this module's.

A wheel that ships no licence text gets a vetted one from
``agent_runtime/bundle_profiles/licence-texts/`` (:func:`licence_overrides`):
``<distribution>/<version>/<file>``, copied to the output's ``licence-texts/``
and cited like any other licence file. An override names the version it was
vetted at; a different shipped version does not get it, and
:func:`licence_problems` fails until someone re-vets the text.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
import uuid
from email.parser import HeaderParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSES_JSON = "licenses.json"
SBOM_JSON = "sbom.cdx.json"
INTERPRETER_LOCK = ROOT / "agent_runtime" / "bundle_profiles" / "interpreters.lock.json"
LICENCE_TEXTS = ROOT / "agent_runtime" / "bundle_profiles" / "licence-texts"
#: Where an output carries the override texts it cites (output-relative).
OUTPUT_LICENCE_TEXTS = "licence-texts"

#: Copyleft code compiled into a wheel whose own metadata names a permissive licence
#: (or none). Keyed by normalized distribution name.
EMBEDDED_COMPONENTS: dict[str, list[dict[str, str]]] = {
    "piper-tts": [{"name": "espeak-ng", "licence": "GPL-3.0-or-later",
                   "note": "compiled into piper's espeakbridge extension (phonemizer)"}],
    "sherpa-onnx": [{"name": "espeak-ng", "licence": "GPL-3.0-or-later",
                     "note": "compiled into the stock wheel's extension whenever TTS is on"}],
    "sherpa-onnx-core": [{"name": "espeak-ng", "licence": "GPL-3.0-or-later",
                          "note": "compiled into the stock wheel's native library whenever TTS is on"}],
}

#: What the python-build-standalone ``install_only`` interpreter carries (Windows layout).
INTERPRETER_COMPONENTS: list[dict[str, str]] = [
    {"name": "openssl", "licence": "Apache-2.0"},
    {"name": "sqlite", "licence": "blessing"},
    {"name": "libffi", "licence": "MIT"},
    {"name": "zlib", "licence": "Zlib"},
    {"name": "bzip2", "licence": "bzip2-1.0.6"},
    {"name": "xz", "licence": "0BSD"},
    {"name": "mpdecimal", "licence": "BSD-2-Clause"},
    {"name": "expat", "licence": "MIT"},
    {"name": "vcruntime140", "licence": "LicenseRef-Microsoft-Visual-C-Runtime-Redistributable",
     "note": "Windows only: Microsoft's redistributable C runtime shipped beside python.exe"},
]

#: Trove classifier -> SPDX, for distributions without ``License-Expression``.
_CLASSIFIER_SPDX = {
    "MIT License": "MIT", "BSD License": "BSD", "Apache Software License": "Apache-2.0",
    "Python Software Foundation License": "PSF-2.0", "ISC License (ISCL)": "ISC",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "The Unlicense (Unlicense)": "Unlicense",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Affero General Public License v3": "AGPL-3.0-only",
}

_REVIEW_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bAGPL|Affero", re.I), "AGPL-family licence"),
    (re.compile(r"\bLGPL|Lesser General Public", re.I), "LGPL-family licence"),
    (re.compile(r"(?<![AL])\bGPL|(?<!Lesser )General Public License", re.I), "GPL-family licence"),
    (re.compile(r"non-?commercial|\bNC\b|-NC-|-NC$", re.I), "non-commercial licence"),
    (re.compile(r"proprietary|LicenseRef-", re.I), "proprietary or non-SPDX licence"),
)
_LICENCE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT|THIRD[-_]?PARTY)", re.I)


def review_reasons(expression: str, components: list[dict[str, str]] = ()) -> list[str]:
    """Every reason ``expression`` (and the embedded components) needs a human ruling."""
    reasons: list[str] = []
    if not expression or expression.upper() in {"UNKNOWN", "NONE"}:
        reasons.append("unknown licence: no License-Expression, License or licence classifier")
    for pattern, reason in _REVIEW_PATTERNS:
        if expression and pattern.search(expression) and reason not in reasons:
            reasons.append(reason)
    for component in components:
        for reason in review_reasons(component["licence"]):
            reasons.append(f"embedded {component['name']}: {reason}")
    return reasons


# -- facts from one installed distribution -----------------------------------------------------


def _metadata(info_dir: Path):
    return HeaderParser().parsestr((info_dir / "METADATA").read_text(encoding="utf-8", errors="replace"))


def licence_expression(meta) -> str:
    """``License-Expression`` (PEP 639), else a short ``License`` field, else the classifiers."""
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    field = (meta.get("License") or "").strip()
    if field and "\n" not in field and len(field) <= 80 and field.upper() != "UNKNOWN":
        return field
    names = []
    for classifier in meta.get_all("Classifier") or []:
        parts = [p.strip() for p in classifier.split("::")]
        if parts[0] == "License" and len(parts) > 1 and parts[-1] != "OSI Approved":
            names.append(_CLASSIFIER_SPDX.get(parts[-1], parts[-1]))
    if names:
        return " OR ".join(dict.fromkeys(names))
    return field.splitlines()[0][:80] if field else "UNKNOWN"


def licence_files(info_dir: Path, meta) -> list[Path]:
    """The distribution's licence texts: ``License-File`` entries in its dist-info, else files
    named like a licence in the dist-info, else such files its RECORD installs one or two levels
    deep (``onnxruntime/LICENSE``, ``win32/license.txt``) — wherever the wheel put them."""
    found: list[Path] = []
    for name in meta.get_all("License-File") or []:
        for candidate in (info_dir / "licenses" / name, info_dir / name):
            if candidate.is_file():
                found.append(candidate)
                break
    if not found:
        found = sorted(p for p in info_dir.rglob("*") if p.is_file() and _LICENCE_NAME.match(p.name))
    record = info_dir / "RECORD"
    if not found and record.is_file():
        site = info_dir.parent
        for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
            rel = line.split(",", 1)[0].replace("\\", "/")
            parts = rel.split("/")
            if len(parts) <= 2 and _LICENCE_NAME.match(parts[-1]) and (site / rel).is_file():
                found.append(site / rel)
    return sorted(found)


def source_url(meta) -> str | None:
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"source", "source code", "repository", "code", "github"}:
            return url.strip()
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in {"homepage", "home"}:
            return url.strip()
    return (meta.get("Home-page") or "").strip() or None


# -- vetted licence texts for wheels that ship none ----------------------------------------------


def licence_overrides(root: Path = LICENCE_TEXTS) -> dict[str, dict]:
    """normalized distribution name -> its vetted override (``index.json``'s ``overrides``)."""
    index = root / "index.json"
    if not index.is_file():
        return {}
    return json.loads(index.read_text(encoding="utf-8"))["overrides"]


def _same_licence(a: str, b: str) -> bool:
    """``Apache 2.0`` and ``Apache-2.0`` name one licence."""
    return re.sub(r"[\s_-]+", "", a).lower() == re.sub(r"[\s_-]+", "", b).lower()


def place_override(out: Path, name: str, override: dict, root: Path = LICENCE_TEXTS) -> list[str]:
    """Copy ``override``'s texts into ``out/licence-texts/<name>/<version>/``; output-relative paths.
    A text whose bytes no longer match the SHA-256 it was vetted with is refused, loudly."""
    placed = []
    for filename, digest in sorted(override["files"].items()):
        source = root / name / override["version"] / filename
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"vetted licence text {source} changed: sha256 {actual}, vetted {digest}")
        rel = f"{OUTPUT_LICENCE_TEXTS}/{name}/{override['version']}/{filename}"
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out / rel)
        placed.append(rel)
    return placed


# -- the wheel each distribution was installed from ----------------------------------------------


def lock_wheels(lock: Path = ROOT / "uv.lock") -> dict[tuple[str, str], list[dict]]:
    """(normalized name, version) -> the lock's wheel entries (url, hash, size)."""
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], list[dict]] = {}
    for package in data.get("package", []):
        name = re.sub(r"[-_.]+", "-", package["name"]).lower()
        out.setdefault((name, str(package.get("version", ""))), []).extend(package.get("wheels", []))
    return out


def installed_wheel(info_dir: Path, name: str, version: str, wheels: dict) -> dict | None:
    """The lock wheel whose tag set equals the dist-info ``WHEEL`` tags (``uv pip install`` picked it)."""
    from packaging.tags import parse_tag
    from packaging.utils import parse_wheel_filename

    wheel_file = info_dir / "WHEEL"
    if not wheel_file.is_file():
        return None
    tags = set()
    for tag in HeaderParser().parsestr(wheel_file.read_text(encoding="utf-8")).get_all("Tag") or []:
        tags |= set(parse_tag(tag.strip()))
    for entry in wheels.get((name, version), []):
        filename = entry["url"].rsplit("/", 1)[-1]
        if set(parse_wheel_filename(filename)[3]) == tags:
            return entry
    return None


# -- one output ---------------------------------------------------------------------------------


def _component(name: str, version: str, expression: str, files: list[str], url: str | None,
         wheel: dict | None, homepage: str | None, components: list[dict[str, str]] = (),
         more_reasons: list[str] = (), **extra) -> dict:
    reasons = review_reasons(expression, list(components)) + list(more_reasons)
    if not files and not extra.get("licence_files_placed_by"):
        reasons.append("no licence text in the output")
    sha = (wheel or {}).get("hash", "")
    row = {"distribution": name, "version": version, "licence": expression, "licence_files": files,
           "source_url": (wheel or {}).get("url") or url, "homepage": homepage,
           "wheel_sha256": sha.split(":", 1)[1] if sha.startswith("sha256:") else None,
           "review": bool(reasons), "review_reasons": reasons}
    if components:
        row["embedded"] = list(components)
    row.update(extra)
    return row


def distribution_rows(out: Path, names, wheels: dict | None = None, overrides: dict | None = None,
                      override_root: Path = LICENCE_TEXTS) -> list[dict]:
    """A row for each of ``names`` installed in ``out/site-packages``; a wheel with no licence text
    gets its vetted override when the override names the shipped version."""
    site = out / "site-packages"
    wheels = lock_wheels() if wheels is None else wheels
    overrides = licence_overrides(override_root) if overrides is None else overrides
    by_name = {}
    for info in site.glob("*.dist-info"):
        meta = _metadata(info)
        by_name[re.sub(r"[-_.]+", "-", meta["Name"]).lower()] = (info, meta)
    rows = []
    for name in sorted(names):
        info, meta = by_name[name]
        files = [p.relative_to(out).as_posix() for p in licence_files(info, meta)]
        expression, more, extra = licence_expression(meta), [], {}
        override = overrides.get(name)
        if not files and override and override["version"] == meta["Version"]:
            files = place_override(out, name, override, override_root)
            extra["licence_text_override"] = {k: override[k] for k in ("source_url", "tag", "commit")}
            if expression.upper() in {"UNKNOWN", "NONE", ""}:
                expression = override["licence"]
            elif not _same_licence(expression, override["licence"]):
                more.append(f"vetted licence text is {override['licence']}; the wheel metadata says "
                            f"{expression}")
        rows.append(_component(name, meta["Version"], expression, files,
                         source_url(meta), installed_wheel(info, name, meta["Version"], wheels),
                         source_url(meta), EMBEDDED_COMPONENTS.get(name, []), more, **extra))
    return rows


def interpreter_row(target: str, lock: Path = INTERPRETER_LOCK) -> dict:
    data = json.loads(lock.read_text(encoding="utf-8"))
    artifact = data["artifacts"][target]
    components = [c for c in INTERPRETER_COMPONENTS
                  if target.startswith("win32") or c["name"] != "vcruntime140"]
    return _component("cpython", data["version"], "PSF-2.0", ["LICENSE.txt"], artifact["url"],
                {"url": artifact["url"], "hash": f"sha256:{artifact['sha256']}"},
                "https://github.com/astral-sh/python-build-standalone", components,
                licence_files_placed_by="installer (interpreter root)", kind="interpreter")


def first_party_row(out: Path, commit: str) -> dict:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    files = sorted(p.relative_to(out).as_posix() for p in (out / "app").glob("*.dist-info/licenses/*")
                   if p.is_file())
    return _component(project["name"], f"{project['version']}+g{commit[:12]}", project.get("license", "UNKNOWN"),
                files, None, None, None, kind="first-party",
                commit=commit)


def copy_first_party_licence(app: Path) -> None:
    """``pyproject``'s ``license-files`` into the app's dist-info (PEP 639 layout)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for info in app.glob("*.dist-info"):
        for rel in project.get("license-files", []):
            source = ROOT / rel
            if source.is_file():
                (info / "licenses").mkdir(exist_ok=True)
                (info / "licenses" / source.name).write_bytes(source.read_bytes())


def cyclonedx(output: str, commit: str, rows: list[dict]) -> dict:
    """A CycloneDX 1.5 JSON BOM for ``rows``; the serial number is derived, so rebuilds are stable."""
    components = []
    for row in rows:
        kind = row.get("kind")
        purl = (f"pkg:generic/python-build-standalone/cpython@{row['version']}" if kind == "interpreter"
                else f"pkg:pypi/{row['distribution']}@{row['version']}")
        licence = row["licence"]
        spdx_like = re.fullmatch(r"[A-Za-z0-9.+\-() ]+", licence) and licence.upper() != "UNKNOWN"
        component = {
            "type": "application" if kind == "first-party" else "library",
            "bom-ref": purl, "name": row["distribution"], "version": row["version"], "purl": purl,
            "licenses": [{"expression": licence}] if spdx_like else [{"license": {"name": licence}}],
        }
        if row.get("wheel_sha256"):
            component["hashes"] = [{"alg": "SHA-256", "content": row["wheel_sha256"]}]
        refs = [{"type": "distribution", "url": row["source_url"]}] if row.get("source_url") else []
        if row.get("homepage"):
            refs.append({"type": "website", "url": row["homepage"]})
        if refs:
            component["externalReferences"] = refs
        if row.get("embedded"):
            component["components"] = [
                {"type": "library", "bom-ref": f"{purl}#{c['name']}", "name": c["name"],
                 "licenses": [{"expression": c["licence"]}] if not c["licence"].startswith("LicenseRef-")
                 else [{"license": {"name": c["licence"]}}]}
                for c in row["embedded"]]
        components.append(component)
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'hermes-bundle:{output}:{commit}')}",
        "version": 1,
        "metadata": {"component": {"type": "application", "bom-ref": f"hermes-bundle:{output}",
                                   "name": f"hermes-bundle-{output}", "version": commit}},
        "components": components,
    }


def write_licence_records(out: Path, output: str, names, target: str, commit: str,
                          *, core: bool, wheels: dict | None = None, overrides: dict | None = None,
                          override_root: Path = LICENCE_TEXTS) -> dict:
    """``licenses.json`` + ``sbom.cdx.json`` in ``out`` for ``names`` (and, for the core, the
    interpreter and first-party app). Returns the licences record."""
    rows = distribution_rows(out, names, wheels, overrides, override_root)
    if core:
        rows = [interpreter_row(target), first_party_row(out, commit), *rows]
    record = {"schema": 1, "output": output, "target": target, "commit": commit,
              "review_required": [r["distribution"] for r in rows if r["review"]], "components": rows}
    (out / LICENSES_JSON).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out / SBOM_JSON).write_text(json.dumps(cyclonedx(output, commit, rows), indent=2) + "\n",
                                 encoding="utf-8")
    return record


def licence_problems(out: Path, names, overrides: dict | None = None) -> list[str]:
    """``licenses.json`` names exactly ``names`` (plus the core's two), every licence file it
    cites is in the output, no vetted licence-text override names a version other than the one
    shipped, and the SBOM lists the same components."""
    overrides = licence_overrides() if overrides is None else overrides
    path = out / LICENSES_JSON
    if not path.is_file():
        return [f"no {LICENSES_JSON} in {out.name}"]
    record = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in record["components"] if r.get("kind") not in {"interpreter", "first-party"}]
    listed = {r["distribution"] for r in rows}
    problems = [f"{LICENSES_JSON} lists a distribution the output does not ship: {n}"
                for n in sorted(listed - set(names))]
    problems += [f"{LICENSES_JSON} does not list a shipped distribution: {n}" for n in sorted(set(names) - listed)]
    for row in rows:
        override = overrides.get(row["distribution"])
        if override and override["version"] != row["version"]:
            problems.append(f"licence-text override of {row['distribution']} is vetted at "
                            f"{override['version']}, the output ships {row['version']}: re-vet it "
                            f"(agent_runtime/bundle_profiles/licence-texts)")
    for row in record["components"]:
        if row.get("licence_files_placed_by"):
            continue
        problems += [f"{LICENSES_JSON}: licence file of {row['distribution']} is not in the output: {rel}"
                     for rel in row["licence_files"] if not (out / rel).is_file()]
    sbom = out / SBOM_JSON
    if not sbom.is_file():
        problems.append(f"no {SBOM_JSON} in {out.name}")
    else:
        bom = {c["name"] for c in json.loads(sbom.read_text(encoding="utf-8"))["components"]}
        if bom != {r["distribution"] for r in record["components"]}:
            problems.append(f"{SBOM_JSON} and {LICENSES_JSON} list different components")
    return problems

