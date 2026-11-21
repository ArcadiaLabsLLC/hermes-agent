# Golden cases

Each `*.json` file here is `{"fixtures": {name: fixture}, "cases": [case]}`. Both
readers run every case: Eternia's
(`test/core/io/project_folder_conformance_test.dart`) and hermes'
(`tests/agent_runtime/test_project_files_spec_cases.py`, over the
vendored mirror).

A **fixture** is built in a fresh temporary folder `T`; the root is `T/root`:

| key | what it makes |
|---|---|
| `files` | `{path: text}` under the root, UTF-8 |
| `bytes` | `{path: hex}` under the root, raw bytes |
| `dirs` | empty folders under the root |
| `series` | `[{dir, prefix, count, width, suffix, text}]`: `count` files named `prefix` + the index zero-padded to `width` + `suffix` |
| `links` | `{path: target}` symlinks under the root, the target written verbatim (relative to the link's folder) |
| `outside` | `{path: text}` under `T/outside`, beside the root |

Any string in a fixture, request or expectation may be written
`{"$repeat": s, "count": n}` (`s` repeated `n` times) or
`{"$join": [part, ...]}` (strings and `$repeat` objects, joined).

A **case** is `{name, about, fixture, request, expect}`. `request` is
`{verb, path?, depth?, offset?, pattern?}`. `expect` is one of
`{"refusal": code}`, `{"reply": exact}` or `{"reply_keys": subset}`.

A runner that cannot create a symlink on its platform skips a case whose
fixture has `links` and names it as skipped; it never passes it.
