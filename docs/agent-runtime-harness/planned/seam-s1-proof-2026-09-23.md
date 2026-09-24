# Seam Stage 1 proof — the harness CLI as a manifest-declared plugin (2026-09-23)

**Lane:** S1P (proving lane, branch `seam/s1-proof`, cut from `origin/main` @ `5732265aaf`).
**Plan:** [`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) § Stage 1, the
"CORRECTED 2026-09-23" block, points 1–5 (design of record). Stage 1 stays ON HOLD unless §3 says PASS.

## 1. Baseline (before any edit, tree @ `5732265aaf`)

Machine: Windows 10, 16 logical processors, Python 3.12.5 (`C:/Users/beast/.venvs/hermes-test`).
Not guaranteed idle — other lanes were live on the box; min is reported beside median for that reason.

**Method.** Every sample is a fresh process with `HERMES_HOME` a fresh `tempfile.mkdtemp()` directory,
`HERMES_BUNDLED_PLUGINS` unset, cwd the worktree root (so `hermes_cli` resolves to this tree — checked:
`hermes_cli.__file__` = `X:\wt\h-s1p\hermes_cli\__init__.py`). One discarded warm-up per series (it pays
the bytecode compile), then 5 samples. (a)/(b) are the whole CLI process's wall time measured by the
parent; (c)/(d) are `time.perf_counter()` spans inside the fresh process. The driver is
`.lane-logs/measure_s1p.py` (lane-local, not committed); its three probes, verbatim:

```text
CLI      : python -c "import sys; sys.argv=['hermes']+sys.argv[1:]; from hermes_cli.main import main; main()" <args>
PARSER   : sys.argv=['hermes',<args>]; import hermes_cli.main as m; t=perf_counter(); m._build_cli_parser(); span
DISCOVER : t=perf_counter(); import hermes_cli.plugins as p; span1; p.discover_plugins(); span2
```

`python` is the one interpreter named above; `S1P_RUNS=5`.

| # | what | median ms | min ms | samples ms | receipt |
|---|---|---|---|---|---|
| (a) | `hermes harness --help`, wall | 2252.8 | 2173.8 | 2173.8 2252.8 2339.4 2558.2 2221.9 | exit 0 |
| (b) | `hermes harness doctor`, wall | 2618.1 | 2460.7 | 2618.1 2662.2 2749.3 2566.4 2460.7 | exit 0, `verdict: ok` |
| (c) | `_build_cli_parser()`, argv `harness doctor` | 768.1 | 755.8 | 755.8 766.5 769.9 768.1 790.1 | `harness_parser_ms` 530–561 of it; `hermes_cli.plugins` NOT imported; `import hermes_cli.main` 363 ms before it |
| (c2) | `_build_cli_parser()`, argv `status` | 740.3 | 736.9 | 756.0 740.3 739.7 750.0 736.9 | same — the harness tree is built for every command today |
| (d1) | `import hermes_cli.plugins`, bare process | 410.9 | 390.1 | 390.1 412.5 410.9 403.1 447.1 | |
| (d2) | `discover_plugins()` after (d1) | 623.4 | 601.2 | 633.1 623.4 602.8 601.2 643.1 | 59 found, 112 `plugins.*`/`hermes_plugins.*` modules in `sys.modules`, `_cli_commands` empty |

**What a pre-discovery scan costs INSIDE the CLI process** (one probe, 3 runs, after `import
hermes_cli.main` + `_build_cli_parser()`): `import hermes_cli.plugins` **+10 ms** (its dependencies are
already loaded by then — the 411 ms of (d1) is a bare-process figure), `collect_directory_manifests()`
**32 ms** for 59 manifests, `gate_manifest` over all of them **4 ms**. So the corrected shape's floor is
~46 ms against the +50 ms parser threshold, before the plugin itself is materialised.

**Ratchet before:** `python scripts/upstream_footprint.py --base d337b736aa` →
`[up-fp] files=459 deleted_lines=2834 heavy=24`. `hermes_cli/main.py` row: +39 / −193, heavy;
**8 hunks** at default context (`git diff d337b736aa -- hermes_cli/main.py | grep -c '^@@'`), 23 at `-U0`.
`hermes_cli/plugins.py` is already on the list (+5 / −2).

## 2. The built tree (`seam/s1-proof`, corrected shape, points 1–5)

Built as: `3f967b8d09` (generic `cli_commands:` pre-scan, `fork: hook-pending`), `327515b992`
(`_harness_entry` in `harness.py`), `9514c16896` (the `eternia-harness` plugin; `harness`/`postinstall`
out of `_BUILTIN_SUBCOMMANDS`; `build_downstream_parsers` + `dispatch_command` deleted), the tail-import
deletion, `d98e0ebf39` tests. `scripts/dump_cli_contract.py --check`: fresh, 202 paths — fixture
byte-identical.

**Why the §1 series are NOT the comparison.** Re-taking §1's method on the built tree gave (a) 1456.8 and
(b) 1988.0 — 600–800 ms "faster" than §1, which no change here can explain: the box's load moved between
the two runs. The verdict therefore rests on an **interleaved A/B**: a detached worktree at the baseline
`5732265aaf` and this branch, alternated sample by sample (same instant, same load), 7 samples each after
one warm-up per tree, fresh `HERMES_HOME` per sample (driver `.lane-logs/measure_ab.py`, lane-local).

| # | what | base median / min | built median / min | Δ median | Δ min | threshold |
|---|---|---|---|---|---|---|
| (a) | `harness --help`, wall | 1358.6 / 1324.9 | 1421.5 / 1395.4 | +62.9 | +70.5 | — |
| (b) | `harness doctor`, wall | 2090.6 / 2036.5 | 2010.3 / 1962.0 | **−80.3** | −74.5 | ≤ +150 → PASS |
| (c) | `_build_cli_parser()` [harness doctor] | 781.6 / 760.4 | 832.7 / 820.7 | **+51.1** | +60.3 | ≤ +50 → **FAIL by 1.1 (median), 10.3 (min)** |
| (c2) | `_build_cli_parser()` [status] | 789.2 / 766.5 | 852.0 / 821.9 | +62.8 | +55.4 | — (every command pays the scan) |
| (e) | `status`, wall | 3472.2 / 3332.2 | 3503.5 / 3423.5 | +31.3 | +91.3 | — |
| (d) | `discover_plugins()` | 623.4 (§1) | 615.2 (60 found; `_cli_commands` = harness, postinstall) | — | — | not on the harness path any more |

`get_plugin_manager()._discovered` is `False` after the built parser under `harness doctor`: discovery
is never run (pinned by `tests/hermes_cli/test_plugin_declared_cli_commands.py`).

**Where the +51 ms goes** (in-process profile of the built parser, 3 runs): `collect_directory_manifests`
32–36 ms (59 manifests; 15 ms of it is 372 `stat` calls, the rest the C YAML loader), second read of the
manifests for `cli_commands` 5–6, the two config reads of the gate 4, `PluginManager._load_plugin` of the
one plugin 9–10 — of which **16 ms** in the unprofiled run is upstream's
`plugin_compat.disable_reason` (a `load_config_readonly` deepcopy + an AST scan, run for a BUNDLED plugin
that by upstream's own rule never uses compat paths). `harness_parser_ms` itself fell 530–561 → 484: the
harness import now finds some shared deps already loaded by `hermes_cli.plugins`.

**Ratchet:** before `[up-fp] files=459 deleted_lines=2834 heavy=24`; after
`[up-fp] files=459 deleted_lines=2832 heavy=24` (−2: the builtin-list line and the dispatch line are
upstream's again). `main.py` hunks **8 → 7**: four fork hunks gone (builtin list, parser seam, dispatch
wrapper, dead `_warn_legacy_console_gateway_task` tail import), two `hook-pending` hunks carried until the
upstream PR merges (→ 5 then). `plugins.py` +83/−2 (was +5/−2).

### Parallel to upstream — recorded

| # | fork code | upstream symbol it shadows | why carried |
|---|---|---|---|
| 1 | `hermes_cli/plugins.py::_declared_cli_rows` re-reads `plugin.yaml` for one key | `plugins_manifest.parse_manifest_file` / `_parse_manifest_v2_fields` (no `cli_commands` field upstream — checked at `a25cf4d77d`) | keeps `plugins_manifest.py` off the ratchet; the upstream PR adds `PluginManifest.cli_commands` instead and this function goes |

## 3. Verdict — **FAIL** (marginal), Stage 1 stays ON HOLD

Doctor passes with room (−80 ms against a +150 budget). The parser misses its +50 ms budget by
**1.1 ms at the median and 10.3 ms at the min** — inside run-to-run noise, but the rule is the number, and
the number is over. Nothing here is landed on `main`.

**Next shape** (each item a measured slice of the +51, none a parallel):
1. `cli_commands` parsed once, as a `PluginManifest` field (the PR shape) — retires the second read,
   −5 ms, and deletes §2's parallel row; costs `plugins_manifest.py` a place on the ratchet until merge.
2. Upstream PR: `plugin_compat.disable_reason` short-circuits `source == "bundled"` — −10 to −16 ms on
   every bundled plugin load, discovery included; a generic fix with its own consumer.
3. One config read for the gate's enabled/disabled pair — −2 ms.
Together ≈ −17 to −23 ms → parser ≈ +28 to +34 ms, inside the threshold with margin. Re-take the A/B above
on that tree before Stage 1 comes off hold; the launcher boot (`python -m hermes_cli.main harness serve`,
same `harness` entry — no different entry needed) is still owed by the operator on the passing build.
