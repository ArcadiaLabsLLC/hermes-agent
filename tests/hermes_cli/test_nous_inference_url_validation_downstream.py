"""Fork-owned tests moved out of ``tests/hermes_cli/test_nous_inference_url_validation.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from __future__ import annotations

from tests.hermes_cli import test_nous_inference_url_validation as _upstream


class TestCallSiteWiring:
    # upstream's source reader, imported by name (one reader, not a copy)
    _read_auth_source = _upstream.TestCallSiteWiring._read_auth_source

    def _auth_tree(self):
        import ast
        return ast.parse(self._read_auth_source())

    @staticmethod
    def _callee_name(node):
        import ast
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @classmethod
    def _reads_inference_base_url(cls, node):
        """True when ``node`` is ``_optional_base_url(<x>.get("inference_base_url"))``."""
        import ast
        if cls._callee_name(node) != "_optional_base_url":
            return False
        for arg in node.args:
            if not isinstance(arg, ast.Call) or cls._callee_name(arg) != "get":
                continue
            if arg.args and isinstance(arg.args[0], ast.Constant):
                if arg.args[0].value == "inference_base_url":
                    return True
        return False

    def test_no_unvalidated_inference_base_url_assignments_remain(self):
        """Every network read of ``inference_base_url`` is wrapped by the validator.

        DERIVED, not enumerated. The previous version of this test listed two
        exact byte strings - ``refreshed.get(...)`` and ``mint_payload.get(...)``
        - and asserted neither appeared. It passed for as long as it existed
        while `_nous_device_code_login` persisted the device-code poll response
        through `_optional_base_url` alone, because that site reads
        ``token_data``, which neither needle named. One of the two needles,
        ``mint_payload``, had ZERO occurrences in the whole 8,900-line file, so
        that half could never fail at all.

        The rule is structural: a ``_optional_base_url(x.get("inference_base_url"))``
        call is only safe when it is the DIRECT ARGUMENT of
        ``_validate_nous_inference_url_from_network``. That admits the nested
        form the shared-merge path already uses, and refuses a bare one
        wherever it appears and whatever the payload variable is called.
        """
        import ast
        tree = self._auth_tree()

        wrapped = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and self._callee_name(node) == (
                "_validate_nous_inference_url_from_network"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Call) and self._reads_inference_base_url(arg):
                        wrapped.add((arg.lineno, arg.col_offset))

        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and self._reads_inference_base_url(node)
        ]
        # Anti-vacuity: a walk that resolves nothing must say so rather than
        # report a clean tree. If this floor trips, the shape moved and the
        # gate is blind again - which is the whole failure being retired here.
        assert reads, (
            "found no _optional_base_url(...inference_base_url...) reads at all; "
            "the call shape changed and this gate can no longer see its subject"
        )

        offenders = sorted(
            node.lineno
            for node in reads
            if (node.lineno, node.col_offset) not in wrapped
        )
        assert offenders == [], (
            "unvalidated network read of inference_base_url at auth.py line(s) "
            f"{offenders}. Wrap it in _validate_nous_inference_url_from_network(): "
            "a poisoned value here redirects every subsequent proxy request, "
            "bearing the user's inference JWT, to whatever host the network said."
        )

    def test_validator_wired_at_all_known_call_sites(self):
        """Keep all four protected sources after upstream extracts refresh healing."""
        import ast
        tree = self._auth_tree()
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        direct = [n for n in calls if self._callee_name(n) == "_validate_nous_inference_url_from_network"]
        healed = [n for n in calls if self._callee_name(n) == "_healed_nous_inference_url"]
        helper = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_healed_nous_inference_url")
        assert any(isinstance(n, ast.Call) and self._callee_name(n) == "_validate_nous_inference_url_from_network" for n in ast.walk(helper))
        # One validator call is the shared helper itself, not a network source.
        assert len(direct) - 1 + len(healed) >= 4
        assert len(healed) >= 2

    def test_proxy_adapter_also_validates(self):
        """The Nous proxy adapter applies the validator as defense-in-depth
        even though auth.py already validates at the source, so a future
        bypass at the source layer still gets caught at the forward
        boundary."""
        from pathlib import Path
        import hermes_cli.proxy.adapters.nous_portal as _nous_adapter
        source = Path(_nous_adapter.__file__).read_text(encoding="utf-8")
        assert "_validate_nous_inference_url_from_network" in source
