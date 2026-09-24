"""Fork-owned tests moved out of ``tests/hermes_cli/test_codex_models.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""



def test_catalog_falls_back_to_the_ungated_sentinel_when_newest_client_is_rejected():
    """If the backend goes back to rejecting out-of-sequence versions (empty list or non-200), the
    ``0.0.0`` sentinel is tried next; a sentinel that is itself empty yields no entries."""
    from agent.model_metadata import CODEX_UNGATED_CLIENT_VERSION, fetch_codex_catalog_entries

    class _Resp:
        def __init__(self, status, models):
            self.status_code, self._models = status, models

        def json(self):
            return {"models": self._models}

    def rejecting(url):
        return _Resp(200, [{"slug": "gpt-5.5"}]) if url.endswith(CODEX_UNGATED_CLIENT_VERSION) else _Resp(400, [])

    entries, status = fetch_codex_catalog_entries(rejecting)
    assert [e["slug"] for e in entries] == ["gpt-5.5"] and status == 200
    assert fetch_codex_catalog_entries(lambda url: _Resp(200, [])) == ([], 200)
