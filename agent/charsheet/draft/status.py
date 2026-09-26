"""The status payload: every QA item's history, the stage and its order (``StatusReport``)."""

from __future__ import annotations

from agent.charsheet import pipeline
from agent.charsheet.revisions import ImageRevisionStore

from .installed import _row_json
from .layout import SCHEMA, STAGES, path_or_none, read_palette, row_item, spec_to_dict, turnaround_item

__layer__ = "lanes"


class StatusReport:
    """The status payload: every QA item's history, the stage, the scope — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def status_payload(self) -> dict:
        """Everything a QA UI needs: stage, spec summary, per-item history.

        JSON-safe by construction. ``current`` is the approved image when there is
        one and the latest attempt otherwise, so a pending item is still
        displayable.

        **Every path in this payload is a ``str`` or JSON ``null``** — including
        ``baseImage``, which is the one ``path_or_none`` did NOT reach when the
        rule was first written. It answered ``""`` for a draft with no base image
        beside ``authoredBy: null`` and ``history[].path: null`` in the same
        response, which is exactly the two-spellings defect the helper exists to
        retire, one field later. ``list`` carries the same field
        (``_characters_draft_summary``) and answers the same way.
        """
        draft = self.draft
        spec = draft.spec
        store = draft.store
        width, height = spec.sheet_size()
        base = draft.base_image

        turnaround = {
            direction: self._item_status(store, turnaround_item(direction))
            for direction in pipeline.turnaround_order(spec.scheme.authored)
        }
        rows = {
            row.key: self._item_status(store, row_item(row.key))
            for row in spec.authored_rows()
        }
        # ABSENT, not empty, when this draft has not composed. The key is spelled
        # as a conditional entry in a fixed position rather than appended, so a
        # consumer reading key order sees one shape; and an uncomposed draft is
        # not the same fact as a sheet with no colours (`read_palette`).
        palette = read_palette(draft.directory)
        return {
            "schema": SCHEMA,
            "id": draft.id,
            "slug": draft.slug,
            "displayName": draft.display_name,
            "concept": draft.concept,
            "style": draft.style,
            "authoredBy": draft.authored_by,
            # The two provenance fields travel together, and both spell absence
            # `null`. `hermesHome` is a PATH field, so it is also bound by the
            # rule this docstring states: a `str` or JSON `null`, never `""`.
            "hermesHome": draft.hermes_home,
            "stage": draft.stage,
            "stages": list(STAGES),
            "created": str(draft._data.get("created", "")),
            "updated": str(draft._data.get("updated", "")),
            "baseImage": path_or_none(base),
            **({"palette": palette} if palette is not None else {}),
            "spec": {
                **spec_to_dict(spec),
                "rows": [_row_json(row) for row in spec.rows()],
                "sheetWidth": width,
                "sheetHeight": height,
            },
            "turnaround": turnaround,
            "rows": rows,
            "pending": {
                "turnaround": [
                    direction for direction, item in turnaround.items() if item["approved"] is None
                ],
                "rows": [key for key, item in rows.items() if item["approved"] is None],
            },
            "missing": {
                "turnaround": [
                    direction for direction, item in turnaround.items() if not item["attempts"]
                ],
                "rows": [key for key, item in rows.items() if not item["attempts"]],
            },
        }

    @staticmethod
    def _item_status(store: ImageRevisionStore, key: str) -> dict:
        """One QA item: its counts, its current image, and every attempt's file.

        ``history[].path`` is the store's own answer for that index, not a
        filename re-derived from the attempt number — a QA surface that wants to
        show attempt 2 beside attempt 3 has to address them individually, and
        re-spelling the store's layout here is how the two would drift apart.

        **Every path here is a ``str`` or JSON ``null``, never ``""``.** Same
        reasoning as ``authored_by`` above, and the same payload: absence is a
        fact a consumer must be able to READ. An empty string is not a path, and
        a consumer that receives one cannot tell "no image was recorded for this
        attempt" from any other empty value — while an agent following the
        ``MEDIA:<path>`` protocol interpolates it and emits a bare ``MEDIA:``
        line. ``attempt_path``/``current``/``latest`` all return a typed
        ``Path | None``; flattening that at the payload boundary destroyed the
        only distinction the store took care to make.
        """
        history = store.history(key)
        approved = store.approved_index(key)
        approved_path = store.current(key)
        # A pending item's newest attempt is what QA has to look at.
        current = approved_path if approved_path is not None else store.latest(key)
        return {
            "key": key,
            "attempts": len(history),
            "approved": approved,
            "approvedPath": path_or_none(approved_path),
            "current": path_or_none(current),
            "rejected": [i for i, record in enumerate(history) if record.get("rejected")],
            "history": [
                {
                    "attempt": index,
                    "path": path_or_none(store.attempt_path(key, index)),
                    "note": str(record.get("note", "")),
                    "created": str(record.get("created", "")),
                    "rejected": bool(record.get("rejected")),
                }
                for index, record in enumerate(history)
            ],
        }
