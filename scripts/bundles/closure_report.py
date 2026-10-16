"""The closure report's Markdown tables (``bundle_profile_closure.py --markdown``).

Split out of ``scripts/bundle_profile_closure.py`` (W0-G1 size ceiling).
"""

from __future__ import annotations


def _mib(n) -> str:
    return f"{(n or 0) / 2**20:.2f}"


def _version(row) -> str:
    lock, inst = row.get("lock_version"), row.get("installed_version")
    if lock and inst and lock != inst:
        return f"{lock} (venv {inst})"
    return lock or (f"— (venv {inst})" if inst else "—")


def render_markdown(result: dict) -> str:
    rows = result["needed"]
    measured = [r for r in rows if r["installed"]]
    estimated = [r for r in rows if not r["installed"]]
    boot = [r for r in measured if r["loaded_at_boot"]]
    optional_bytes = sum((r.get("size_bytes") if r["installed"] else r.get("wheel_bytes_estimate")) or 0
                         for r in result["optional_not_shipped"])
    out = ["| | distributions | size |", "|---|---:|---:|",
           f"| Shipped, installed (measured) | {len(measured)} | **{_mib(result['needed_measured_bytes'])} MiB** |",
           f"| — of which loaded at boot | {len(boot)} | {_mib(sum(r['size_bytes'] for r in boot))} MiB |",
           f"| Shipped, not installed locally (uv.lock wheel bytes, **estimate**) | {len(estimated)} | "
           f"~{_mib(result['needed_estimated_bytes'])} MiB |",
           f"| **All shipped, as uv.lock wheels (compressed — the installer-ceiling view)** | {len(rows)} | "
           f"**~{_mib(result['needed_wheel_bytes'])} MiB** |",
           f"| Optional extras reached but not shipped | {len(result['optional_not_shipped'])} | "
           f"{_mib(optional_bytes)} MiB (direct only) |",
           f"| Omitted base distributions | {len(result['omitted'])} | "
           f"{_mib(sum(r.get('size_bytes', 0) for r in result['omitted']))} MiB |",
           f"| Excludable (reached only by switched-off features) | {len(result['excludable'])} | "
           f"{_mib(result['excludable_total_bytes'])} MiB |", ""]
    out += ["### Shipped, installed (measured)", "",
            "| distribution | version | declared | pure/native | MiB | loaded at boot |", "|---|---|---|---|---:|---|"]
    for r in measured:
        out.append(f"| {r['name']} | {_version(r)} | {r['declared']} | {'native' if r['native'] else 'pure'} | "
                   f"{_mib(r['size_bytes'])} | {'yes' if r['loaded_at_boot'] else 'no'} |")
    out += ["", "### Shipped, not installed locally (estimate: uv.lock wheel bytes)", "",
            "| distribution | version | MiB (wheel) |", "|---|---|---:|"]
    for r in sorted(estimated, key=lambda r: -(r.get("wheel_bytes_estimate") or 0)):
        out.append(f"| {r['name']} | {_version(r)} | {_mib(r.get('wheel_bytes_estimate'))} |")
    out += ["", "### Optional extras reached but not shipped", "",
            "| distribution | extras | MiB (installed, else wheel) | first reached via |", "|---|---|---:|---|"]
    for r in result["optional_not_shipped"]:
        size = r.get("size_bytes") if r["installed"] else r.get("wheel_bytes_estimate")
        homes = ", ".join(r["extras"][:4]) + (", …" if len(r["extras"]) > 4 else "")
        out.append(f"| {r['name']} | {homes} | {_mib(size)} | `{' → '.join(r['via'])}` |")
    out += ["", "### Omitted base distributions", "", "| distribution | MiB | what degrades |", "|---|---:|---|"]
    for r in result["omitted"]:
        out.append(f"| {r['name']} | {_mib(r.get('size_bytes'))} | {r['degrades']} |")
    out += ["", "### Excludable", "", "| distribution | version | MiB |", "|---|---|---:|"]
    for r in result["excludable"]:
        out.append(f"| {r['name']} | {_version(r)} | {_mib(r.get('size_bytes'))} |")
    return "\n".join(out) + "\n"
