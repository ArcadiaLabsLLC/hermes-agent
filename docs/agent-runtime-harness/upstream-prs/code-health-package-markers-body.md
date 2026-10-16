# fix(code-health): measure a temp tree with its package markers

Draft PR body (fork-hygiene row "`scripts/check --only health` reds every pre-existing BLE001 in a
file the change touches", lane r-isolation 2026-10-16). Posted by the owner in a posting sitting;
`scripts/code_health/` is upstream-owned, so the fork does not carry the edit.

## The problem

`Measurer.measure` reads a committed tree's files into a bare temporary directory and runs ruff
there, while the working tree is measured in place. Ruff resolves a relative import only inside a
package, so in the bare tree `from .vocabulary import logger` leaves `logger` a bare name and
BLE001 accepts its `exc_info=True`; in place, the same `logger` resolves to a module attribute
ruff does not treat as a logger and BLE001 fires. The base therefore carries fewer hits than the
working tree for byte-identical code, and every old hit in a touched file reads as new.

Measured: `origin/main` `d264e13d104` plus one docstring word in
`agent_runtime/mcp_admission/registration.py::release_mcp_admission` -> 9 blocking BLE001.
Same bytes, ruff 0.15.10, same flags: 10 hits in the checkout, 1 in a copy outside it.
With this patch: 0 blocking.

## The change

Write each measured `.py` file's ancestor `__init__.py` files (read from the same tree) into the
temp root before running ruff; they are written, never measured. Test: a docstring-only edit in
a package module keeps its old BLE001 hit old. Killing mutation: `_package_markers` returns `{}`
-> the new test reds (recorded: 1 failed; with the patch the three code-health test files are
118 passed).

## Patch

```diff
diff --git a/scripts/code_health/measure.py b/scripts/code_health/measure.py
index 038a66543c2..a2a1e22a6bc 100644
--- a/scripts/code_health/measure.py
+++ b/scripts/code_health/measure.py
@@ -124,7 +124,7 @@ class Measurer:
             return self._measure_in(self.repo, contents)
         with tempfile.TemporaryDirectory(prefix="code-health-") as tmp:
             root = Path(tmp)
-            for path, text in contents.items():
+            for path, text in {**self._package_markers(tree, contents), **contents}.items():
                 dest = root / path
                 dest.parent.mkdir(parents=True, exist_ok=True)
                 # newline="": the blob's own line endings, so ruff's line numbers match the
@@ -132,6 +132,26 @@ class Measurer:
                 dest.write_text(text, encoding="utf-8", newline="")
             return self._measure_in(root, contents)
 
+    def _package_markers(self, tree: str, contents: dict[str, str]) -> dict[str, str]:
+        """Each measured ``.py`` file's ancestor ``__init__.py`` files, as ``tree`` has them.
+
+        Ruff resolves a relative import only inside a package; without the markers an imported
+        ``logger`` reads as a bare name and BLE001 accepts its ``exc_info=True``, so a base
+        measured in a bare temp tree lost hits the working tree (measured in place) still had,
+        and every old hit in a touched file read as new. Written, never measured."""
+        markers: dict[str, str] = {}
+        for path in contents:
+            if not path.endswith(".py"):
+                continue
+            for parent in Path(path).parents:
+                marker = (parent / "__init__.py").as_posix()
+                if parent == Path(".") or marker in markers or marker in contents:
+                    continue
+                text = read_file(self.repo, tree, marker)
+                if text is not None:
+                    markers[marker] = text
+        return markers
+
     def _measure_in(self, root: Path, contents: dict[str, str]) -> dict[str, FileMeasure]:
         result = {path: FileMeasure(path, lines=text.splitlines()) for path, text in contents.items()}
         py = sorted(p for p in contents if in_scope(p) == "py")
diff --git a/tests/scripts/test_code_health_cli.py b/tests/scripts/test_code_health_cli.py
index 3ac15b7cc69..5bc82ce22d2 100644
--- a/tests/scripts/test_code_health_cli.py
+++ b/tests/scripts/test_code_health_cli.py
@@ -452,3 +452,27 @@ def test_tooling_failure_exits_2_without_a_traceback(tmp_path, monkeypatch, caps
     assert cli.main(["--base", base, "--head", "HEAD"]) == 2
     err = capsys.readouterr().err
     assert err.startswith("code health:") and "npm" in err
+
+
+# --- a docstring-only edit inside a package keeps its old BLE001 hits old ---------------------
+
+
+def test_a_docstring_edit_in_a_package_does_not_renew_its_old_blind_excepts(tmp_path, capsys):
+    """The base is measured in a temp tree; without the package's ``__init__.py`` there, ruff
+    cannot resolve ``from .log import logger`` and accepts its ``exc_info=True``, so the
+    working tree (measured in place) reported every old hit as new.
+
+    Killing mutation: make ``Measurer._package_markers`` return ``{}`` -> this test reds.
+    """
+    repo, _ = _ratchet_repo(tmp_path)
+    module = ('"""Module."""\nfrom .log import logger\n\n\ndef boundary():\n    """{}"""\n'
+              "    try:\n        return 1\n    except Exception:\n"
+              '        logger.warning("failed", exc_info=True)\n        return 0\n')
+    base = _commit(repo, {"pkg/__init__.py": "",
+                          "pkg/log.py": "import logging\n\nlogger = logging.getLogger(__name__)\n",
+                          "pkg/b.py": module.format("Old words.")})
+    _write(repo, {"pkg/b.py": module.format("New words.")})
+    code = cli.run(repo, base, None)
+    out = capsys.readouterr().out
+    assert code == 0, out
+    assert "BLE001" not in out, out
```
