# Planned — regex search on a phone runs ripgrep's engine inside Hermes

**Status:** plan written 2026-11-21 by lane w1118a-rgplan for row
`RT-PHONE-FILE-TOOLS-TAKE-THE-SAME-ARGUMENTS-AS-ON-DESKTOP-WITH-RIPGREPS-ENGINE-IN-PROCESS`
(`Harness_Brain/20 — Active Initiatives/runtime-queue.md`, NEEDS PLAN after review w1118a.86). The
build rows of §9 are filed READY and wait for a review batch.

**The owner's ruling, quoted from the row (RULED 2026-11-21):** asked whether to file it with ripgrep's
engine through FFI first and the `regex` package as the fallback, the owner said "yea sounds good". The
order is: ripgrep's engine in process; where that cannot ship on a target, the `regex` package with
its `timeout=`; where neither ships, regex is refused in words; never Python `re` on caller input.

Everything below that chooses between options is this plan's **recommendation**, not a ruling. Nothing
here departs from the ruling, so no build row waits on the owner. §8 names the steps that go back to the
owner if they cannot ship.

Evidence labels: **read** means read in code on hermes `origin/main` at `f0b5f7c997` (after
`RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT` landed at `e001fab6da`) and Eternia `8434df7cb23`.
**ran** means the spike of §2 ran it on the Linux box. **guess** means not proven, and the row it names
checks it first.

---

## 1. What is there now

- **read** `agent_runtime/phone_file_tools.py` `search_files` takes every desktop argument (target,
  file_glob, limit, offset, order, output_mode, context) over `agent_runtime/project_files/reader.py`,
  under one `Deadline` (2000 ms, `rules.SEARCH_DEADLINE_MS`) across every folder searched. A content
  pattern holding any of `.^$*+?()[]{}|\` is refused in words by `_literal` ("regex search is not on
  this phone yet"). This plan replaces that refusal.
- **read** The walk is Python's and stays Python's: `reader._walk_project_folder` skips links,
  `.git`, the skip list and the root `.gitignore` (`project_files/ignore.py`, the rule spec Eternia and
  hermes both follow). `grep_matches` then opens each file, caps it at `MAX_READ_BYTES` (5 MB), drops
  binary (a NUL in the first 8 KB) and non-UTF-8 files, and calls `replies.grep_lines` per file.
- **read** `grep_lines(path, text, pattern, deadline, context)` asks `pattern.matches(line)` per line
  and builds each match with its `before`/`after` context.
- **read** Today a file is opened with a plain `open(local, "rb")` after the walk saw a regular file.
  A file swapped for a link between the walk and the open is followed. The review listed this as an
  edge case, not worked.

## 2. The spike (scratch only, not committed)

A crate of about 120 lines (`regex` 1.13.2, `grep-searcher` 0.1.17, `grep-matcher` 0.1.9, then also
`grep-regex` 0.1.14) behind a C ABI: `compile(pattern, size_limit) -> handle | error text`,
`search(handle, bytes, cancel_flag*, out_lines*, cap) -> count | -1 (cancelled)`, `free(handle)`.
It was built with rustc 1.100.0 and `cargo-ndk` 4.1.2 on NDK 28.2.13676358, using the release
profile with `lto = true`, `codegen-units = 1`, `panic = "abort"` and `strip = true`. It was loaded
on the host (Python 3.12) through `ctypes`.

| What | Number (ran) |
|---|---|
| `cargo ndk -t arm64-v8a --platform 24 build --release`, cold (crates already fetched) | 48.5 s first; 37.6 s with `grep-regex` |
| same, x86_64 Android, cold | 29.6 s |
| host `cargo build --release`, cold | 31.9 s; 43.2 s with `grep-regex` |
| warm rebuild after touching `lib.rs` (LTO relinks) | 20.0 s |
| `libX.so` arm64-v8a, `opt-level=3` | 1,698,656 B; **1,894,296 B with `grep-regex`** (836,414 B deflated, about the wheel size) |
| `libX.so` arm64-v8a, `opt-level="s"`, without `grep-regex` | 1,504,008 B |
| `libX.so` x86_64 Android, `opt-level=3`, without `grep-regex` | 1,897,744 B |
| host `libX.so` with `grep-regex` | 2,074,896 B |
| `aarch64-apple-ios` `staticlib` (compiles on Linux, unlinked) | 8,587,072 B `.a`, 36.4 s |
| `aarch64-apple-ios` `cdylib` on Linux | fails at link: `xcrun --sdk iphoneos` missing (needs a Mac) |
| ELF `LOAD` alignment, both Android ABIs | `0x4000`: **16 KB page-aligned by default** (NDK r28) |
| `NEEDED` | `libdl.so`, `libc.so` only |
| crates in the build graph | 20 (`regex`, `regex-automata`, `regex-syntax`, `aho-corasick`, `memchr`, `bstr`, `encoding_rs`, `encoding_rs_io`, `memmap2`, …) |
| ctypes call on a 4-line buffer | 7.6 µs per call |
| compile `fn\s+(\w+)\(` | 1.9 ms |
| 5 MB buffer (the per-file cap), `fn\s+(\w+)\(`, one hit | 4.4 ms raw adapter; **1.8 ms `grep-regex`** |
| 5 MB, no-match `zzz\d+qqq` | 8.9 ms raw adapter; **0.8 ms `grep-regex`** |
| 5 MB of `a…ab` lines, `(a|aa)+$`, `(a*)*c`, `(\w+\s*)+x$` | 0.4, 0.3, 1.6 ms: linear, no backtracking blow-up |
| `\p{L}{30}c` at a 1 MB compiled-size cap | refused: "compiled regex exceeds size limit of 1048576" (12.6 ms) |
| `(` | refused: "unclosed group" |
| 200 MB in one call, cancel flag set by a Python thread at 50 ms | returned −1 after 106.7 ms; a Python ticker thread ran 100 times during the call (**the GIL is released**) |

Logs: the scratchpad's `rgplan_spike/` (`rgplan_*.log`, `rgplan_semantics.log`,
`rgplan_ctypes_probe.log`). One probe crashed the interpreter when it passed a refused pattern's
NULL handle into `search`. That was the probe's bug, and it is why §5 makes the binding refuse a NULL
handle before any search.

**What the spike changed in the plan:**
- **`grep-regex` joins `regex` + `grep-searcher`.** `grep-regex` is ripgrep's own matcher crate, built
  on the same `regex-automata`/`regex-syntax` that `regex` uses. A hand-written `Matcher` over
  `regex::bytes` works, but it loses three things ripgrep has:
  - With no line terminator declared, `grep-searcher` takes its slow per-line path. The spike
    measured that as 2–11× slower on 5 MB.
  - A pattern holding a literal `\n` silently matches nothing with the hand-written matcher.
    `grep-regex` refuses it with ripgrep's own sentence ("the literal "\n" is not allowed in a
    regex").
  - ripgrep's Unicode, case and line rules come with it, so a pattern means the same on a phone as
    `rg` on a desktop.
  
  `grep-regex` costs 0.2 MB per ABI. `ignore` stays out, as the review ruled: Python walks.
- **The cancel flag is checked per match in the sink and before each file, not per line.** A
  `find_at` runs over a whole buffer, so a single call is only as fine-grained as one file. The
  per-file cap bounds that call: about 9 ms for 5 MB of non-matching text on this box (ran). A phone
  core may be 3–5× slower (guess), which is still far inside 2000 ms.

## 3. Crates and where the crate lives

- **Crates:** `regex` (for its builder limits and as the engine), `grep-regex`, `grep-searcher`, and
  `grep-matcher` (the trait between them). **Not `ignore`.** The native side never walks and never
  opens a file.
- **Where:** `crates/project_files_match/` at the repo root. It holds `Cargo.toml`, `Cargo.lock`,
  `rust-toolchain.toml` (pinning 1.100.0 and the five targets), `src/lib.rs` and
  `include/project_files_match.h`. It is fork-owned and outside every package that
  `[tool.setuptools.packages.find]` includes, so no wheel carries its source (the row asked for
  this; read in `pyproject.toml`). `apps/bootstrap-installer/src-tauri` is the only other crate, and
  it is an app, so `apps/` is the wrong home.
- **CI routing:** `rust-tests.yml`'s header says that `.rs` under `apps/` was once classified as
  frontend and ran no Rust (read). The change classifier must route `crates/**` to the Rust lane.
  Row A does that.

## 4. Binding: a C ABI through `ctypes` (recommended), not pyo3

| | ctypes over a C ABI | pyo3 extension |
|---|---|---|
| GIL | released on every foreign call (ran: a Python thread ran 100 times during one call) | released with `allow_threads` around the search |
| Python versions | **one library per ABI for every CPython**: no headers, no `libpython` link | one per CPython minor (cp314), or `abi3`; Android cross-builds need `PYO3_CROSS_LIB_DIR` pointed at the phone's `libpython3.14.so` |
| Packaging seam on Android | a plain `.so` loaded by path, like `phone_native_libs.py` loads Flet's libraries (read) | a normal extension module, like Pillow's `_imaging` |
| iOS | CPython's iOS layout puts binary modules in `.framework`s. Whether a plain `dlopen`ed library (not an extension) gets that treatment is **guess**, so row C checks it first | the standard extension-module path, which BeeWare's iOS support converts (guess, not read here) |
| Eternia `dart:ffi` later (§7) | **the same library and header** | not loadable from Dart |
| Host tests | `cargo build` + `ctypes.CDLL` on any Python (ran on 3.12) | needs a matching CPython dev install |

**Recommended: ctypes.** It needs one build per ABI and no CPython coupling, the GIL is released
without code, and it is the only option that leaves the shared-FFI door (§7) open. Its one open risk
is iOS packaging, and the ruling already covers that: if the Mac sitting (row C) shows a plain library
cannot ship on iOS, iOS takes the `regex` fallback (§8) and Android keeps the native engine. If the
review prefers pyo3, only §4 and row A's binding change. The crate, the safety rules and the
packaging seams stay.

## 5. The ABI and its safety rules

> **As built (row A, 2026-11-21, lane w1118a-rgA).** The header that holds is the crate's own
> `crates/project_files_match/include/project_files_match.h`; the sketch below is the plan's. What
> moved: `pfm_compile` also returns the error's length (`size_t *err_len`); `pfm_search` takes
> `start` and `first_line` and returns `resume_at` / `resume_line` in place of `total_out`, so a file
> with more matching lines than `lines_cap` is searched again from where it stopped (review .87 (6));
> codes `-4` bad argument, `-5` caught panic, `-6` search refused join `-1`..`-3`, and `-3` covers NULL
> only (review .87 (4)). The matcher is built as `rg` builds it: `multi_line(true)` (so `^`/`$` are
> line anchors), then `crlf(true)` and the `\n` line terminator. `regex` is a dev-dependency (the
> tests' per-line oracle); the engine is `grep-regex`'s. The `regex`-package step is
> `agent_runtime/project_files/fallback_match.py`; the opener every grep reads through is
> `reader.read_regular_file`.
> **CI moved:** `rust-tests.yml` and `scripts/ci/classify_changes.py` are upstream files, and the
> fork's upstream footprint never rises (`tests/scripts/test_upstream_footprint.py` went red on both),
> while upstream's `ci.yaml` that calls `rust-tests.yml` is disabled on the fork. The job is
> `project-files-match` in the fork-owned `.github/workflows/fork-gates.yml`, selected by its own path
> filter; no classifier route is needed.

```c
/* include/project_files_match.h: version 1 */
int32_t  pfm_abi_version(void);
void    *pfm_compile(const uint8_t *pattern, size_t len, uint32_t flags,  /* bit 0: ignore case */
                     size_t size_limit, size_t dfa_limit, uint8_t *err, size_t err_cap);
int64_t  pfm_search(const void *matcher, const uint8_t *bytes, size_t len,
                    const uint8_t *cancel, uint32_t budget_ms,
                    uint64_t *lines_out, size_t lines_cap, uint64_t *total_out);
           /* -> lines written; -1 cancelled; -2 budget spent; -3 bad handle */
void     pfm_free(void *matcher);
```

- **Bytes in, line numbers out.** Python opens, caps, sniffs binary and checks UTF-8 exactly as
  today, then hands the bytes over. The native side never sees a path, so it **cannot follow a
  link**. The regex path opens with `os.open(..., O_RDONLY | O_NOFOLLOW | O_CLOEXEC)` and refuses a
  file that became a link. The literal path shares that opener, which also closes the review's
  "swapped for a link between resolve and open" edge case for both paths.
- **The compiled pattern is bounded.** The rule spec already caps the pattern at 1–256 characters
  (`MAX_PATTERN`). Compilation adds `size_limit` (start at 1 MB) and `dfa_size_limit` (start at
  8 MB) and `nest_limit(64)`. A refused pattern returns the engine's own sentence, which goes back to
  the agent as `bad_argument`. Ran: `\p{L}{30}c` is refused at 1 MB and `\p{L}{8}c` passes. ripgrep's
  defaults are larger, so a few patterns `rg` accepts are refused here. That is a documented edge
  case. Row A picks the final caps by measuring peak RSS.
- **The cancel flag.** One `ctypes.c_uint8` per search, read with an atomic load before each file,
  per match in the sink, and at the end. Python sets it when the turn is interrupted.
- **The 2000 ms deadline.** The existing `Deadline` keeps owning the clock. Each `pfm_search` gets the
  budget left in milliseconds and keeps its own monotonic clock from there, so no clock crosses the
  FFI. `Deadline.check()` runs between files as today. The search refuses `search_timeout` with
  today's words. Rust's `regex` is linear-time, so the deadline bounds tree size, not backtracking.
- **A NULL or freed handle** is refused (`-3`) in Rust, and the binding never passes one (the spike
  crashed on exactly this).
- **The worker thread.** The tool handler already runs off the event loop, and ctypes drops the GIL for
  the call, so no extra thread is needed. Row A tests that another Python thread keeps running
  during a long call, as the spike did.
- **No process is started**, and nothing is written. The gate's `subprocess_call` rule is unchanged.

**Python side.**
- `agent_runtime/project_files/native_match.py` is the binding. It finds the library, checks
  `pfm_abi_version() == 1` and declares `argtypes`. It exposes
  `RegexLines.compile(pattern, ignore_case)` and `RegexLines.lines(data, deadline, cancel)`. Its
  `available()` is false when the library is absent or fails to load, and it logs the reason once.
- `replies.grep_lines` takes the matching line numbers from either matcher: `LinePattern` per line,
  as today, or `RegexLines` per file. The context and paging code is shared, so one reply shape serves
  both matchers.

## 6. Packaging: how the phone packager ships it

**What happens today (read).** The packager builds nothing from source:
- Flet's Android Pillow and its four library wheels are pinned by URL and sha256 in
  `agent_runtime/bundle_profiles/phone_wheels.lock.json`.
- `scripts/bundles/phone_wheels.py` swaps those pins into the pool. `pinned_blocks` also appends every
  pinned name the export lacks.
- The gate (`scripts/bundle_profile_gate.py`, `distribution_findings`) judges a pinned distribution by
  its pinned wheel. A non-`none-any` wheel needs a `packaging.admitted_native` entry, and "not in
  uv.lock" is never asked of a pinned name.
- The closure maps an import to its distribution through the installed site's metadata
  (`packages_distributions`).
- Eternia's build hook ships the phone tree to Android only (`EterniaLauncher/packages/agents/eternia_hermes_embedded/README.md`:
  "Every other target gets nothing").

**Recommended: a pinned library wheel through the same seam. No build step goes into the packager.**
- **The wheel.** `eternia-project-files-match` holds the `.so` and a three-line locator package,
  `eternia_project_files_match/__init__.py`, that exports `LIBRARY`, the library's path. It is tagged
  `py3-none-android_24_arm64_v8a` / `py3-none-android_24_x86_64`, and later the iOS tags.
  - It is not a CPython extension, so it fits every CPython.
  - The binding imports the locator inside an `ImportError` guard. That puts the distribution in the
    closure. The pool installs it from the pin, and the gate judges the pinned wheel.
  - A desktop does not have the wheel. There the guard gives the fallback (§8).
- **The build** is `scripts/native/build_project_files_match.py`. It runs
  `cargo ndk -t <abi> --platform 24 build --release` under the crate's `rust-toolchain.toml` and
  `--locked`, with `--remap-path-prefix` so that no machine path is in the binary. It then writes the
  wheel and prints its sha256.
  - Android builds run on this Linux box (ran: 38–49 s cold per ABI).
  - iOS builds run on the Mac (row C).
  - A rebuild that does not reproduce the pinned sha256 is refused, never re-pinned silently. Row B
    measures whether the build is bit-for-bit reproducible. If it is not, the pin is the artifact's
    hash and the build script records the toolchain and the `Cargo.lock` hash in the wheel's
    metadata.
- **Hosting the wheel: two options.**
  - **(a) Commit the wheels.** They go under `crates/project_files_match/dist/` (about 0.85 MB each),
    and `phone_wheels.py` learns a repo-relative pin, `"path": …` beside `"url"`. No new host and no
    publish step are needed, at the cost of binary blobs in git for each version.
  - **(b) A release asset** on the fork's GitHub repository, pinned by URL like Flet's wheels. The
    repository is **public** (read through `gh repo view`), so creating that release is a publish that
    needs the owner's go each time.
  - **Recommended: (a).** The blobs are small and versions will be rare, and (b) adds an owner go to
    every bump.
- **`bundled-phone.yaml` `packaging.admitted_native`** gains
  `eternia-project-files-match: "ripgrep's matcher for regex search_files (owner RULED 2026-11-21 on
  RT-PHONE-FILE-TOOLS-TAKE-…-IN-PROCESS: ripgrep's engine through FFI first)"`. The yaml's comment
  says "architecture §6 admits Pillow alone", so the same row amends §6 to cite the ruling.
- **Android 16 KB pages.** Ran: both ABIs come out `0x4000`-aligned with NDK r28 and rustc 1.100. A
  gate check reads the `LOAD` alignment of every `.so` in a pinned phone wheel and refuses anything
  below `0x4000`. This puts the lock comment's hand read into a test.
- **iOS framework layout (row C).** CPython's iOS support (PEP 730) requires every binary in the app
  to be in `Frameworks/<name>.framework/<name>`, with a marker left where the module was. The Mac
  sitting builds `aarch64-apple-ios` and `aarch64-apple-ios-sim` dylibs, wraps each as a framework,
  and reads whether a plain library loaded with `ctypes.CDLL` by its framework path works in
  CPython's iOS testbed on the simulator. That read is a guess until the sitting makes it. Eternia
  does not embed Python on iPhone yet (read, above), so row C proves the library in CPython's
  testbed, not inside Eternia.
- **Desktop CI.**
  - `rust-tests.yml` gains a job: `cargo test` in the crate, then a host `cargo build --release`.
    Then `tests/agent_runtime/test_project_files_native_match.py` runs with
    `ETERNIA_PROJECT_FILES_MATCH_LIB` set to the host library (about 43 s cold, ran).
  - In the ordinary Python suite, the native tests skip with a reason when that variable is unset.
    The fallback and refusal tests always run, with the binding forced unavailable.
- **Size.** About 1.9 MB unpacked and 0.84 MB in the wheel per Android ABI (ran). Eternia's
  `MC-PHONE-SIZE-BUDGET-NEVER-MEASURED` takes these numbers.

## 7. Eternia through `dart:ffi` (a later option only)

The owner asked whether the FFI could be shared. The C ABI of §5 is plain C, so Eternia could later
load the same `libproject_files_match` through `dart:ffi`, shipped by a native-assets build hook like
`eternia_hermes_embedded`'s. Its `ProjectFolderReader` would then search with ripgrep's engine too,
instead of its own literal matcher, giving one regex engine on both sides of the rule spec. **This plan
does not do it and files no row for it.** Keeping the ABI plain C and versioned
(`pfm_abi_version`) keeps the option open at no cost now.

## 8. The fallback order: what each step costs on each phone target

| Step | Android arm64 / x86_64 | iOS device / simulator | Goes to the owner when |
|---|---|---|---|
| 1. ripgrep's engine, ctypes (rows A, B, C) | **Built here (ran).** About 1.9 MB per ABI, 16 KB-aligned. It costs one crate, one build script, two pins and one `admitted_native` entry. | Compiles here, **links only on a Mac** (ran: `cdylib` link fails without Xcode). Framework packaging is a **guess** (row C). | Only if hosting (b) is chosen: each release-asset publish needs the owner's go. |
| 2. `regex` package with `timeout=` | **There is no cross-build after all (read).** Flet's index (`pypi.flet.dev/regex/`) has `cp314` wheels for `android_24_arm64_v8a` and `android_24_x86_64`: 2026.5.9 and 2026.11.9, about 0.29 MB each. This corrects the review's "no android or ios wheel", which is true only of pypi.org (0 of 130 files). The cost is pins, a third `admitted_native` entry and a version clash: `uv.lock` pins `regex` 2026.9.29, and `phone_wheels.version_problems` refuses a phone pin whose version differs. Bumping `uv.lock` to 2026.11.9 (a transitive dependency of transformers, misaki, segments and curated-tokenizers) clears it. 16 KB alignment is unread. | The same index has `ios_13_0_arm64_iphoneos` and `ios_13_0_arm64_iphonesimulator` wheels for both versions, about 0.28 MB each. They are standard extension modules. The same version clash applies. | **If the `uv.lock` bump of `regex` is refused** (a desktop dependency moved for a phone fallback): then the owner chooses between a cross-build of 2026.9.29 (the NDK here, the Mac for iOS) and a per-name exemption from the one-version rule. |
| 3. Refusal in words | Today's `_literal` refusal, worded for good. | The same. | Never: the ruling already covers it. |
| Never | Python `re` on caller input. | | |

The `regex` package backtracks. Its `timeout=` (the remaining deadline) is what bounds it, which is why
it is second. A pattern that is valid in one engine and not the other, when one target falls back, is
a documented edge case (review w1118a.86), not worked.

## 9. Build rows (filed READY, each awaits a review batch)

- **A. `RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY`** (L).
  - The crate under `crates/project_files_match/` (§3), the C ABI and header (§5), and the ctypes
    binding `agent_runtime/project_files/native_match.py`.
  - `grep_lines` takes either matcher. The `O_NOFOLLOW` opener serves both paths.
  - `search_files` runs a regex pattern through the native matcher when it is available, else
    `regex` with `timeout=` when it imports, else the refusal in words.
  - The `rust-tests.yml` job and the change classifier's `crates/**` route.
  - Tests are written after the code, each red under a named mutation.
  - It reads live in a phone-configured Linux namespace through `launcher_qa`, with the host library.
- **B. `RT-PHONE-REGEX-SEARCH-SHIPS-ON-ANDROID`** (M).
  - The build script, the library wheel for `android_arm64` and `android_x86_64`, the pins (hosting
    (a)), the `admitted_native` entry and the architecture §6 amendment.
  - The 16 KB alignment check in the gate.
  - A regex `search_files` turn read on the x86_64 emulator.
  - It starts after A.
- **C. `RT-PHONE-REGEX-SEARCH-SHIPS-ON-IPHONE`** (M, `REQUIRES macos`).
  - The Mac links `aarch64-apple-ios` and `aarch64-apple-ios-sim` and wraps each as a framework.
  - It reads the library loading through `ctypes` in CPython's iOS testbed on the simulator, then
    pins `ios_arm64` and `ios_arm64_simulator`.
  - If a plain library cannot ship on iOS, iOS falls back to step 2 of §8, which the ruling already
    covers. Only the `uv.lock` bump goes to the owner, and only if it is refused.
  - It starts after A.

The parent row waits on these three rows and closes when the last of them closes.
