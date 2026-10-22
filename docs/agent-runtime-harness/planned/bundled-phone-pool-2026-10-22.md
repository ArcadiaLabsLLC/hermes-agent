# Planned — the phone-scoped pool: the packager installs the closure, not the export — 2026-10-22

**Owner domain:** the bundled editions (`docs/downstream/bundled-phone-gate-2026-09-28.md`,
`docs/downstream/phone-gate-to-zero-plan-2026-09-30.md`); packaging `scripts/bundle_profile_package.py`;
the preceding plan [bundled-phone-profile-2026-10-21.md](bundled-phone-profile-2026-10-21.md) (S1–S2 landed,
S3's receipt stopped at phase pool — commit `83bf715c9d`).
**Status:** IMPLEMENTATION-READY (design lane w1022a-plan). One lane, five stages, one CHANGE commit per
stage or one for S1–S4 together; S5 is the measured receipt.
**Measured / read:** 2026-10-22 against hermes `origin/main` 5371792420, uv 0.12.3, CPython 3.14.7
(`~/.venvs/hermes-test`), the packager and the closure script run from the tree (§1.2).

Row: `RT-BUNDLED-PHONE-POOL` (runtime-queue § Fork-owned); unblocks `RT-BUNDLED-PHONE-PROFILE` S3 and the
launcher's `DIST-MOBILE-CORE-WHEEL-LOCK` slice 2.

## 1. What is true today (file::symbol), and what was measured

### 1.1 The pool is the whole export

- `scripts/bundle_profile_package.py::_build` phase `pool`: `install_pool(export_requirements((*manifest.packaging_extras,
  *pack_extras)), …)`. `export_requirements` is `uv export --frozen … --no-emit-project --no-dev` for core plus the
  profile's extras: EVERY base dependency of `pyproject.toml`, markers evaluated afterwards by `evaluate_markers`
  for `marker_env(target)`. Nothing in phase `pool` reads the profile's `omitted_distributions`, and nothing reads
  the closure: the closure (`distribution_plans`, phase `plan`) runs AFTER the pool, over the pool's own metadata
  (`scripts/bundle_profile_closure.py::plan_jobs` puts the job's `sites` at the head of `sys.path` and
  `Graph` reads `importlib.metadata` there, uv.lock second).
- The desktop lives with this because every base dependency has a desktop wheel. A phone target does not:
  `uv pip install --require-hashes --only-binary :all:` refuses the first block it cannot satisfy, so phase
  `pool` is where `--profile bundled-phone` dies on both targets.
- The one place that knows what a phone needs, `closure_script.GraphFacts.plan` (`needed`), is the one place the
  pool phase never asks.

### 1.2 Measured

| measurement | android_arm64 | ios_arm64 |
|---|---|---|
| `uv export` for `bundled-phone` (`extras: []`), blocks before markers | 79 | 79 |
| after `evaluate_markers` for the target | 65 | 65 |
| the phone closure (`closure("bundled-phone", target=…, parents=True)`, 2007 kept modules, 0 refusals) | **28 dists** | **28 dists** (same set) |
| closure dists, as uv.lock wheels (compressed) | 11.3 MiB | 11.3 MiB |
| closure dists with no wheel in uv.lock (`needed_without_wheel`) | none | none |
| `uv pip install --dry-run` of the 28, `--require-hashes --only-binary :all:` | **27 resolve; pillow 12.3.0 has no Android wheel** | **28 resolve** |
| the packager as it stands (`--profile bundled-phone --python-version 3.14 --no-serve-probe`) | phase pool: `psutil @ git+…` has no hash | phase pool: cryptography 50.0.1 has no iOS wheel |

The 28: anyio, certifi, charset-normalizer, croniter, h11, httpcore, httpx, idna, markdown-it-py, mdurl,
packaging, pillow, prompt-toolkit, pygments, pyjwt, python-dateutil, python-dotenv, pytz, requests, rich,
ruamel-yaml, six, snowballstemmer, socksio, truststore, urllib3, wcwidth, websockets. Two are compiled in the
dev venv: charset-normalizer (ships `py3-none-any` too; resolves on both targets) and pillow (`admitted_native`).

The 37 export blocks the closure does NOT need: annotated-doc, annotated-types, browser-harness, cdp-use, cffi,
click, cryptography, distro, fastapi, fetch-use, fire, firecrawl-anydoc, httptools, jinja2, jiter, markdown,
markupsafe, openai, pathspec, pillow-heif, psutil, ptyprocess, pycparser, pydantic, pydantic-core,
python-multipart, resvg-py, sniffio, starlette, tenacity, termcolor, tomli-w, tqdm, typing-extensions,
typing-inspection, uvicorn, watchfiles.

**The closure-first vs omitted-filtered decision falls out of the table.** Dropping the profile's eight
`omitted_distributions` from the export leaves 57 blocks, of which six (firecrawl-anydoc, httptools, jiter,
markupsafe, watchfiles, resvg-py) still have no phone wheel — exactly what `83bf715c9d` measured — so an
omitted-filtered export never reaches phase 4 on either target. Every one of those six is OUTSIDE the closure.
Installing the closure reaches phase 4 on iOS today and on Android as soon as pillow has an Android wheel (§5).

### 1.3 Per-distribution verdicts (the row's list)

| distribution | phone closure? | verdict |
|---|---|---|
| cryptography | no (omitted; `pyjwt[crypto]` dropped) | **not in the phone closure** — never exported into a closure pool |
| firecrawl-anydoc | no (`plugins.web.firecrawl.provider` imports `firecrawl` guarded; unresolved import name) | not in the phone closure |
| httptools | no (uvicorn's; the dashboard is not packaged) | not in the phone closure |
| jiter | no (openai's; openai omitted, `provider_sdk_shim` stands in) | not in the phone closure |
| markupsafe | no (jinja2's; nothing kept imports jinja2) | not in the phone closure |
| watchfiles | no (uvicorn's) | not in the phone closure |
| resvg-py | no (tools.vision SVG raster; its import is guarded, unresolved on the phone) | not in the phone closure |
| psutil (git pin, no hash) | no (omitted; `pid_exists_stdlib` fallback) | not in the phone closure — the unhashable block is never selected; S2 still refuses a hashless block that IS selected |
| pillow | **yes** (base; `admitted_native`; reached from `agent.image_routing`, `tools.vision_tools*`, `tui_gateway.server`, `agent.pet.*`, `agent.charsheet.*`) | iOS: ships (`cp314-ios_13_0_arm64_iphoneos` wheel in uv.lock). **Android: blocks the build** — no Pillow release has ever published an Android wheel (PyPI probed unpinned: "all versions of pillow have no usable wheels"). Owner ruling, §5. |

A pure-python fallback is needed by none of the nine: the eight absent ones are absent by construction, and
pillow has no pure alternative (that is why architecture §6 admits it).

## 2. Decisions

- `Decided (plan):` **the pool scope is declared by the profile, as an Enum, defaulting to today's
  behaviour.** `packaging.pool: closure` in `bundled-phone.yaml`; `ProfileManifest.packaging_pool: PoolScope`
  with `PoolScope.EXPORT` (default — the desktop is untouched) and `PoolScope.CLOSURE`. Not keyed on the target:
  the choice is a property of the profile's omission model (a phone profile omits base dependencies, a desktop
  profile does not), and a `str` mode would be the ladder the fork's bar forbids.
- `Decided (plan):` **closure-first, seeded from installed metadata the packager already has; the pool plan
  stays the authority.** The closure needs a site to map import names to distributions (`Graph.mapping` is
  `importlib.metadata.packages_distributions()`; uv.lock carries no module names, and `markdown_it` →
  `markdown-it-py`, `dateutil` → `python-dateutil`, `ruamel` → `ruamel-yaml` are not derivable). So phase `pool`
  under `CLOSURE` first runs ONE planning child over a SEED site (default: the packager interpreter's own
  `purelib`, uv-synced from the same lock; `--seed-site` overrides, e.g. an existing desktop pool), takes the
  union of every selection's `needed`, and exports only those blocks. The existing phase `plan` then re-plans
  over the installed phone pool and already fails loud on any difference (`the closure needs X; the pool does not
  hold it`), so a seed that mis-maps a name is a red, never a silent gap. Measured above: the seed plan and
  the phone closure agree (the §1.2 run IS a seed-site plan).
- `Decided (plan):` **a selected block without a hash is a refusal, not a uv error.** `--require-hashes`
  stays; the packager says which pin (`pool_pin_unhashed: psutil @ git+…`) instead of forwarding uv's text.
- `Decided (plan):` **no new target plumbing.** `TARGETS`, `marker_env`, `evaluate_markers`, `install_pool_into`
  (`scripts/bundles/pool_install.py`) are unchanged; the selection is applied to the export text BEFORE
  `install_pool` sees it, so the retry/scratch-folder path is untouched.

## 3. Stages

Each stage names its test and the killing mutation; the mutation is planted, the red recorded in the commit
body, then reverted.

**S1 — `PoolScope` on the manifest** (`agent_runtime/bundle_profiles/manifest.py`). `class PoolScope(Enum):
EXPORT = "export"; CLOSURE = "closure"`; `ProfileManifest.packaging_pool: PoolScope = PoolScope.EXPORT`;
`parse_manifest` reads `packaging.pool` (absent → EXPORT); `validate_manifest` refuses a value outside the Enum
with `ProfileManifestError("packaging.pool must be one of export, closure: got …")`.
`agent_runtime/bundle_profiles/bundled-phone.yaml` gains `pool: closure` under `packaging:` with a two-line
comment pointing at this plan. Test (`tests/agent_runtime/test_bundle_profiles.py`): the phone profile loads with
`packaging_pool is PoolScope.CLOSURE`, the desktop with `EXPORT`, and a manifest with `pool: everything` is
refused naming the value. Killing mutation: read `packaging.pool` as a bare string → the `is PoolScope.CLOSURE`
assertion reds.

**S2 — requirement blocks are typed; a selection keeps only named blocks**
(`scripts/bundle_profile_package.py`). `@dataclass(frozen=True) class Block: name: str; head: str;
marker: str; hashes: tuple[str, ...]` and `requirement_blocks(requirements: str) -> list[Block]` (the name via
`packaging.requirements.Requirement(head).name`, normalised with `_norm`; a URL pin's head keeps its `@ url`).
`evaluate_markers` is rewritten over `requirement_blocks` with its output byte-identical (the three existing
marker tests pin it, `test_a_requirement_with_no_hash_lines_keeps_no_continuation` included).
`select_blocks(blocks: list[Block], names: set[str]) -> tuple[str, list[str]]`: the requirements text of the
blocks whose name is in `names` (markers and hashes intact, so `evaluate_markers` still applies after), and the
refusals `pool_pin_unhashed: <head>` for a selected block with no hash lines. Tests
(`tests/scripts/test_bundle_profile_package.py`): a three-block export selected to two yields exactly those two
with their hashes; a selected `psutil @ git+…` block is refused by name; an unselected hashless block is not.
Killing mutation: drop the hash check in `select_blocks` → the refusal test reds.

**S3 — phase `pool` under `CLOSURE` installs the seed plan's union** (`scripts/bundle_profile_package.py`).
`pool_selection(manifest, seed_sites: list[Path], target, python_version) -> set[str]`: one
`distribution_plans(manifest.profile, [(seed_sites, pack_selections(manifest))], …)` child; the union of every
selection's `needed`; its refusals are printed `closure refusal: …` and the build returns 1 before any install
(they are the same refusals phase `plan` would raise later). `main` gains `--seed-site` (repeatable, `Path`;
default `[Path(sysconfig.get_paths()["purelib"])]` of `sys.executable`). `_build`'s phase `pool` becomes: export
→ `requirement_blocks` → (`CLOSURE` only) `pool_selection` + `select_blocks`, a refusal returns 1 → `install_pool`.
Receipt line: `pool scope: closure — <kept> of <blocks> export blocks (seed: <sites>)`; under `EXPORT` the
phase prints nothing new. Tests (`test_bundle_profile_package.py`, over the `_build_stubs` fixture): with
`packaging_pool=CLOSURE` and `distribution_plans` stubbed to answer `{"a-dist"}` for the core and
`{"a-dist", "b-dist"}` for a pack, `install_pool` receives a requirements text naming `a-dist` and `b-dist` and
not `c-dist`, and the phase order gains `phase seed plan` before `phase pool`; with `EXPORT` the text is the
whole export and no seed child starts (`calls` unchanged). Killing mutation: ignore `manifest.packaging_pool`
and always select → the `EXPORT` test reds (the seed child ran).

**S4 — the pool plan proves the seed** (no new code path; one test and one receipt). `_build` already compares
the pool plan with the pool (`plan.missing`). Add the receipt `pool: seed plan <n> dists, pool plan <m> dists`
after phase `plan`, and the test that a seed answering `{"a-dist"}` while the pool plan answers
`{"a-dist", "d-dist"}` ends the build with `the closure needs d-dist; the pool does not hold it` and exit 1 —
the positive guarantee that a wrong seed is a red. Killing mutation: have `_build` skip the `plan.missing` check
when `packaging_pool is CLOSURE` → red.

**S5 — the measured receipt** (the `RT-BUNDLED-PHONE-PROFILE` S3 receipt, finished). On a workstation with uv:
`python scripts/bundle_profile_package.py --profile bundled-phone --target ios_arm64 --python-version 3.14
--no-serve-probe --out <tmp>/ios` must reach `verify: 0 problem(s)`; the commit body records the pool line
(expected `28 of 65 export blocks`), the `packaged … distributions` line, and the bundle's size on disk
(`du -sh`); the §1.2 wheel total predicts ~11 MiB of third-party. The same for `android_arm64` is BLOCKED on
ruling §5.1 and the body says so with the one failing block (`pillow==12.3.0`): until the ruling lands,
android's receipt is the `--dry-run` of §1.2 (27 of 28 resolve). The landing commit files the "hermes side
landed" note on the launcher's `DIST-MOBILE-CORE-WHEEL-LOCK` as the preceding plan §2 says.

## 4. Out of scope

- The desktop pool stays `EXPORT` (its engine packs rely on the pool holding every extra; moving it to `CLOSURE`
  is a separate row with its own measurement).
- The unresolved import names the phone walk reports (`firecrawl`, `pillow_avif`, `cairosvg`, `svglib`,
  `reportlab`, `mutagen`, `tiktoken`, `keyring`) — each guarded, 0 refusals; `keyring` reaching the embedded
  entry through `agent_runtime.host_store.desktop_binding` is the phone gate plan's, not this pool's.
- Pillow's Android wheel itself (§5.1 decides WHERE it comes from; building it is the launcher's or a
  follow-on hermes lane's, never this one's).
- The closure's speed (the seed plan is a second 2007-module walk; 510 s measured on a loaded box) — the
  planner's stall/cap handling already covers it; a cached walk is a separate row.

## 5. Open rulings

1. **Pillow on Android** — no Pillow release ships an Android wheel; the phone closure needs pillow on both
   targets (10 kept modules, the turn-path sites guarded, `agent.charsheet.*` / `agent.pet.*` / one
   `tui_gateway.server` site unguarded); the manifest has no per-target omission. Options: (a) a fork-built
   Android wheel (BeeWare's mobile-forge carries a Pillow recipe), published under the fork's releases and
   pinned in `pyproject.toml` as `pillow @ <url> ; sys_platform == 'android'` WITH its hash in uv.lock — the
   shape psutil's Android pin already has, hashed; (b) omit pillow on Android only — needs a marker on
   `omitted_distributions` rows plus guarding or switching off the unguarded sites, and degrades image prep on
   one phone and not the other. · Recommend: (a); iOS lands S5 now, Android's S5 lands with the wheel; file
   the wheel build as a launcher row (the launcher owns the mobile toolchain) naming this plan.
2. **Pillow's version on the phones** — uv.lock pins 12.3.0 (iOS wheel present); PyPI's newest iOS wheel is
   13.0.0. Keep the lock's pin or bump for the phones? · Recommend: keep 12.3.0 (one lock, one version, the
   desktop's); the bump is the weekly release merge's.
