# Planned — the bundled phone profile: it exists; what the launcher's slice 2 still needs — 2026-10-21

**Owner domain:** the bundled editions (`docs/downstream/bundled-phone-gate-2026-09-28.md`,
`docs/downstream/phone-gate-to-zero-plan-2026-09-30.md`); packaging `scripts/bundle_profile_package.py`.
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). Half-page plan: the fix is small and its
shape is obvious once the row's premise is corrected.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035; launcher plan
`EterniaLauncher/docs/embedded_hermes/planned/MOBILE_WHEEL_LOCK_2026-10-19.md` read in place.

Row: `RT-BUNDLED-PHONE-PROFILE` (runtime-queue § Fork-owned).

## 1. The row is wrong about why — planned from the code

The row says "the Stage 2 phone package profile … does not exist". It does:
`agent_runtime/bundle_profiles/bundled-phone.yaml` (`profile: bundled-phone`, `packaging.targets:
[android_arm64, ios_arm64]`, `forced_sibling_tree: true`, `skill_platforms: [android, ios]`), in the tree
since the s2 phone lanes (last touched d2c3e25aa9, 2026-10-19), gated by `scripts/bundle_profile_gate.py`
(`--profile` defaults to `bundled-phone`) and exercised by `tests/agent_runtime/test_embedded_phone_session.py`
and `tests/scripts/test_bundle_profile_gate.py`.

What the launcher's slice 2 actually lacks is on the PACKAGER, not the profile:

- `scripts/bundle_profile_package.py::TARGETS` knows `win32-x64`, `win32-arm64`, `darwin-arm64`,
  `darwin-x64`, `linux-x64` — the names of `pm/lock.json` — and NO phone target. `marker_env` indexes
  `TARGETS[target]`, so `--profile bundled-phone --target android_arm64` is a `KeyError` today; the
  profile's own `packaging.targets` list is read by the gate, never by the packager.
- `agent_runtime/bundle_profiles/interpreters.lock.json` pins a desktop CPython per desktop target;
  the phone interpreter is the host app's (BeeWare/Chaquopy-style embedding is the launcher's
  `ARCHITECTURE_2026-09-28.md` §4), so the packager must not demand a pin for a phone target.
- The launcher's `installer/hermes/bundled-hermes.lock.json` carries `"profile": "bundled-desktop"`;
  slice 2 adds `"phone_profile": "bundled-phone"` (its Decision 1) — the launcher's own commit.

## 2. Stages

**S1 — phone targets in the packager** (`scripts/bundle_profile_package.py`). Add `android_arm64` and
`ios_arm64` rows to `TARGETS` with their PEP 508 marker environments (`sys_platform` `android` / `ios`,
`platform_system` `Android` / `iOS`, `os_name` `posix`, `platform_machine` `aarch64` / `arm64`) and the
`uv`/pip platform tag the pool install passes (`--python-platform` `aarch64-linux-android` /
`arm64-apple-ios`; `install_pool` already takes the tag from the `TARGETS` tuple and passes it as uv's
`--python-platform`). Decision rule: if the pinned uv rejects a phone platform tag, the lane keeps the
`TARGETS` row, routes the pool phase for that target through `pip download --platform <tag> --only-binary
:all:` (same hashes, same `--no-deps`), and says so in the commit body. A target the manifest's
`packaging.targets` lists but `TARGETS` lacks is refused by `load_profile(validate=True)` with a
`ProfileManifestError` naming it (one additive check in `bundle_profiles/manifest.py::validate`).
Test (`tests/scripts/test_bundle_profile_package.py`): `marker_env("android_arm64", "3.14")` returns
`sys_platform == "android"`; the validator refuses a profile naming `watchos_arm64`. Killing mutation: drop
the `android_arm64` row → the marker test reds with `KeyError`.

**S2 — no interpreter pin for a phone target.** `locked_python_version()` / `--bake-with` stay desktop;
`main` refuses `--bake-with` for a phone target (`bake_refused_phone_target`) and reads the CPython version
from `--python-version` only. `tests/agent_runtime/test_bundle_interpreters_lock.py` gains the assertion
that the lock lists exactly the desktop `TARGETS` (a phone target must NOT appear). Killing mutation: add
`ios_arm64` to the lock fixture → red.

**S3 — one dry packaging run per phone target is the proof the launcher needs.** `python
scripts/bundle_profile_package.py --profile bundled-phone --target android_arm64 --python-version 3.14
--out <tmp>` must reach phase 4 (`verify_bundle`) on a workstation with `uv`; the commit body records
the bundle size and the distribution count per target. No test — it is the measured receipt (the
`--verify` run is what `tests/scripts/test_bundle_payload.py` already does for desktop with a fake pool;
extend its parametrization with the two phone targets over the fake pool).

Then the launcher's slice 2 (`DIST-MOBILE-CORE-WHEEL-LOCK`) is unblocked: the lock gains
`"phone_profile": "bundled-phone"` and the build hook runs the packager with it. File that as the
launcher row's "hermes side landed" note in the landing commit.

## 3. Out of scope

The phone profile's content (toolsets, omitted distributions, forced tree) — owned by the phone gate plan.
Any wheel of hermes's own (`hermes_mobile_core`) — retired by the launcher's Decision 1.

## 4. Open rulings

None. (The target names `android_arm64` / `ios_arm64` are the manifest's own and already in the tree.)
