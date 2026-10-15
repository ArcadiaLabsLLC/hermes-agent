"""Every LLM-response ``.message.content`` read in ``tools/browser_tool.py`` is None-guarded.

Reasoning-only models (DeepSeek-R1, QwQ) return ``content=None``. Fork-owned:
split out of upstream's ``test_browser_content_none_guard.py`` when upstream
purged that file (2026-09 "purge low-value tests"); the static AST check was
the fork's addition to it.
"""


class TestBrowserSourceLinesAreGuarded:
    """EVERY ``…message.content`` read in browser_tool.py is None-guarded.

    This is a module-wide property — a NEW unguarded call site must fail it —
    which is why it is checked statically instead of only behaviourally. The
    two behavioural classes above pin the two sites that exist today; this pins
    that no third one appears unguarded.

    It is PARSED, not grepped. The two assertions it replaces were hand-copied
    line spellings — ``"return response.choices[0].message.content\\n"`` and
    ``"analysis = response.choices[0].message.content\\n"`` — and the first
    named a shape the module has never had, because that site ASSIGNS rather
    than returns. Deleting the production guard left it GREEN: a vacuous test
    standing exactly where a regression gate was supposed to be. A substring
    scan also breaks on any reformatting, which is the same defect in slower
    motion. Resolved AST nodes have neither failure mode.
    """

    @staticmethod
    def _unguarded_content_reads() -> list[int]:
        """Return the line numbers of un-None-guarded ``.message.content`` reads.

        A read counts as guarded when it is the LEFT operand of an ``or`` —
        i.e. the ``(… or "")`` form — which is the shape the fallback relies on.
        """
        import ast
        import pathlib

        from tools import browser_tool

        tree = ast.parse(
            pathlib.Path(browser_tool.__file__).read_text(encoding="utf-8")
        )
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        unguarded: list[int] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "content"):
                continue
            # Only LLM-response reads: `<...>.message.content`.
            if not (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "message"
            ):
                continue
            parent = parents.get(node)
            guarded = (
                isinstance(parent, ast.BoolOp)
                and isinstance(parent.op, ast.Or)
                and parent.values[0] is node
            )
            if not guarded:
                unguarded.append(node.lineno)
        return unguarded

    def test_every_message_content_read_is_none_guarded(self):
        unguarded = self._unguarded_content_reads()
        assert not unguarded, (
            "browser_tool.py reads an LLM response `.message.content` without "
            'the None guard at line(s) '
            f'{unguarded} — reasoning-only models (DeepSeek-R1, QwQ) return '
            'content=None there. Apply the `(… or "").strip()` form.'
        )
