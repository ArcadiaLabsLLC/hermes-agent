"""The QA crops an operator and a console card read (``Thumbs``)."""

from __future__ import annotations

import logging

from agent.charsheet import pipeline

from .layout import DEFAULT_THUMB_FRAME, DEFAULT_THUMB_SCALE, THUMBS_DIRNAME, row_item, turnaround_item

__layer__ = "lanes"

logger = logging.getLogger(__name__)


class Thumbs:
    """The QA crops an operator and a console card read — one stage of :class:`CharacterDraft`, by composition."""

    def __init__(self, draft) -> None:
        self.draft = draft

    def row_thumb(
        self,
        row_key: str,
        *,
        attempt: int = -1,
        frame: int = DEFAULT_THUMB_FRAME,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """Write a card-size QA crop of ONE frame of ONE row attempt.

        The §F.2 looking procedure as a verb, and the procedure is *crop, then
        upscale* — in that order, because the crop is the half that removes
        pixels. A row strip shown whole in a chat column is a false negative
        machine: the 2026-08-24 seam was invisible at fit-to-window scale in the
        very strip that carried it, and "I looked at the strip and it's fine" was
        reliably wrong. Enlarging that same strip does not fix it — measured
        live, a whole-strip 2x thumb and the raw attempt are the same picture at
        card width (≤2/255 per channel), while costing 24 MiB decoded against
        the 12 MiB installed sheet the crop exists to avoid decoding.

        So the default is ONE frame cell (:data:`DEFAULT_THUMB_FRAME`), sliced
        from the strip by the row's own frame count, and only then upscaled with
        NEAREST (no filter averages the defect away) onto a flat dark backdrop
        with the chroma field keyed out (a seam over magenta reads as nothing,
        and so does one over transparency). The whole-strip view still exists and
        needs no verb: it is the attempt file itself, which the payload names as
        ``source``.

        Stage-free on purpose: looking is never out of order. A composed draft is
        exactly when an operator goes back to find what went wrong, and refusing
        to render a picture at that point is the wall ``reopen`` was built to
        remove.

        **Two bounds, two booleans, and the payload carries both.** A crop is
        weighed against two different things and they disagree on real drafts,
        so one boolean could never have answered for both — it answered for one
        and was READ as the other:

        * ``withinConsoleBudget`` — the crop is under
          :data:`pipeline.MAX_CONSOLE_CARD_PIXELS`, a FIXED console decode
          ceiling sized once from ``CHAR8``. It does not move with a spec. This
          is the bound that is ENFORCED: a crop taken at
          :data:`DEFAULT_THUMB_SCALE` or below — the crop a caller gets by
          asking for a picture, and the one an agent declares with a ``MEDIA:``
          line — is REFUSED when it exceeds it. A deliberate deeper zoom is a
          different artifact with a different reader: allowed up to the write
          ceiling and labelled ``withinConsoleBudget: false``. A boolean rather
          than a silent clamp, because a caller who asked for 8x wants 8x — they
          just must not be told it is a card.
        * ``withinOwnSheet`` — the crop is no larger than the sheet THIS draft
          composes, from its own ``spec.sheet_size()``
          (:func:`pipeline.fits_own_sheet`). It moves with the draft. Nothing is
          refused on it; it is reported at every scale, because a crop heavier
          than its own sheet is a legal picture that simply mitigated nothing.

        **THE CONSUMER RULE, for the launcher card (B2) and for any agent
        declaring a crop: draw it inline ONLY when BOTH are true. Otherwise
        route it to the fullscreen viewer** — ``withinConsoleBudget: false``
        because the decode would sink the surface, ``withinOwnSheet: false``
        because cropping bought nothing and the card may as well have opened
        the sheet.

        Measured both ways, which is why they are two: a ``--directions 4``,
        ``idle:2`` draft's default crop came back 1774x1774 = 3,147,076 px —
        ``withinConsoleBudget: true``, ``withinOwnSheet: false`` at 13.1x its
        239,616-px sheet; and an ``add-state``-grown sheet (1536x3120 =
        4,792,320 px, 1.50x the fixed budget) can take a crop the other way
        round, over the console ceiling and still lighter than the sheet that
        draft will compose. ``cardSafe``, which this payload carried until
        2026-08-25, was the first of these two wearing the second one's name.

        **``square`` is the hero-card shape, and it is opt-in.** The console
        card is a fixed 1:1 centre-cover square (§13.17, ruled: the card is not
        moving), and a character cell is taller than it is wide — so the default
        crop renders there as a torso zoom, which is real confusion even though
        the card was never the verdict surface. With *square*, the finished crop
        is centred on a square field of the same flat dark backdrop
        (:func:`pipeline.pad_to_square`, side = the longer edge) so the card
        draws the whole frame; the filename gains ``-sq`` and the payload says
        ``square: true``. The DEFAULT stays tall: a compare pair aligns its
        panes, and padding changes the aspect the compare guidance assumes. Use
        ``--square`` for a card, bare crops for a comparison.

        **Both bounds are weighed on the PADDED output**, because padding adds
        pixels and the file a consumer decodes is the padded one. A square crop
        can therefore be refused at the default scale where the bare crop of the
        same cell is fine — the refusal names the padded size, since arguing
        about the unpadded one would be arguing about a file nobody asked for.

        Returns a PATH and never bytes (plan A-4): the launcher runs on this
        machine, and the trace lane that would carry an inline image is capped at
        4 KiB.
        """
        draft = self.draft
        row = draft._authored_row(row_key)
        store = draft.store
        key = row_item(row.key)
        if not store.history(key):
            raise ValueError(
                f"row {row.key!r} has no attempt to crop yet; generate it first "
                f"(`characters rows --only {row.key}`)"
            )
        # The store resolves -1 → the newest index and refuses out-of-range, so
        # the number in the filename is the number the payload reports.
        index = store.attempt_index(key, attempt)
        source = store.attempt_path(key, index)
        if source is None or not source.is_file():
            raise ValueError(
                f"attempt {index} of row {row.key!r} has no image on disk"
                + (f" at {source}" if source is not None else "")
            )
        cell = pipeline.frame_cell(source, frame=frame, frames=row.frames)
        crop = self._finish_thumb(
            cell,
            scale=scale,
            square=square,
            stem=f"{row.key}-attempt-{index + 1}-frame-{frame + 1}",
            subject=f"frame of row {row.key!r}",
            remedies=("a row with more frames to slice",),
        )
        logger.info(
            "charsheet draft %s: row %s attempt %d frame %d cropped at %dx%d → %s",
            draft.id,
            row.key,
            index,
            frame,
            crop["width"],
            crop["height"],
            crop["path"],
        )
        return {
            "row": row.key,
            "attempt": index,
            "attempts": len(store.history(key)),
            "frame": frame,
            "frames": row.frames,
            "source": str(source),
            **crop,
        }

    def direction_thumb(
        self,
        direction: str,
        *,
        attempt: int = -1,
        scale: int = DEFAULT_THUMB_SCALE,
        square: bool = False,
    ) -> dict:
        """Write a card-size QA crop of ONE turnaround DIRECTION reference.

        The same verdict :meth:`row_thumb` publishes for a row, for the other
        kind of QA item — and it exists because the ABSENCE of a verdict, not
        any weight, is what made the launcher's card draw a tile through the
        whole turnaround stage. A reference is generated on a SQUARE canvas by
        :func:`pipeline.generate_direction_view` and is comfortably inside both
        bounds at the default scale; there was simply nothing to publish.

        Everything :meth:`row_thumb`'s docstring says about the two bounds and
        the consumer rule — draw it inline only when BOTH booleans are true,
        otherwise route it to the fullscreen viewer — holds here unchanged, and
        holds because it is the same code: one helper weighs, keys, upscales,
        pads and writes for both kinds.

        **No frame keys, rather than frame keys faked to 0-of-1.** A row strip
        holds several poses side by side and a reference holds one, so there is
        nothing to slice and :func:`pipeline.frame_cell` is never called. A
        payload that answered ``frame: 0, frames: 1`` would be inviting a
        consumer to offer a frame picker for a picture that has no frames.

        Stage-free for the reason the row crop is: a composed draft is exactly
        when an operator goes back to ask what the reference looked like, and
        the references are never deleted.
        """
        draft = self.draft
        draft._require_authored_direction(direction)
        store = draft.store
        key = turnaround_item(direction)
        if not store.history(key):
            raise ValueError(
                f"direction {direction!r} has no attempt to crop yet; generate it "
                f"first (`characters turnaround` or `characters reroll-direction "
                f"--direction {direction}`)"
            )
        index = store.attempt_index(key, attempt)
        source = store.attempt_path(key, index)
        if source is None or not source.is_file():
            raise ValueError(
                f"attempt {index} of direction {direction!r} has no image on disk"
                + (f" at {source}" if source is not None else "")
            )
        crop = self._finish_thumb(
            # The reference IS the cell — `reference_cell` is the "nothing to
            # slice" counterpart of `frame_cell`, and naming it keeps every
            # decode of a QA source in the module that owns pixels.
            pipeline.reference_cell(source),
            scale=scale,
            square=square,
            # `turnaround-` prefixed because a direction is a bare compass
            # sector: `e-attempt-1-x2.png` beside `walk-e-attempt-1-frame-1-x2`
            # reads as a truncated row key, and the store's own item key is
            # `turnaround@e` for the same reason.
            stem=f"turnaround-{direction}-attempt-{index + 1}",
            subject=f"reference for direction {direction!r}",
            remedies=(),
        )
        logger.info(
            "charsheet draft %s: direction %s attempt %d cropped at %dx%d → %s",
            draft.id,
            direction,
            index,
            crop["width"],
            crop["height"],
            crop["path"],
        )
        return {
            "direction": direction,
            "attempt": index,
            "attempts": len(store.history(key)),
            "source": str(source),
            **crop,
        }

    def _finish_thumb(
        self,
        cell,
        *,
        scale: int,
        square: bool,
        stem: str,
        subject: str,
        remedies: tuple[str, ...],
    ) -> dict:
        """Weigh, key, upscale, pad and write ONE crop; the half both kinds share.

        *cell* is the finished source region — a sliced frame for a row, the
        whole reference for a direction. *subject* and *remedies* are the only things the
        two kinds say differently, and they are both refusal prose: WHAT was too
        big, and which other shapes the caller could ask for instead.

        Split out when the direction arm landed. The two bounds, the refusal
        threshold, the two backdrops and the pad order are one implementation on
        purpose — a second copy is how ``cardSafe`` came to mean two different
        things in two places.
        """
        draft = self.draft
        # Both bounds are read off the OUTPUT size before anything is allocated:
        # the write ceiling inside `upscale_on_backdrop`, the card budget here,
        # where the default is known. Refusing after the resize would already
        # have paid for the picture nobody may use. The scale is gated first
        # through the same helper `upscale_on_backdrop` uses — weighing an
        # output means multiplying by it, and `512 * "2"` is a string.
        scale = pipeline.require_scale(scale)
        square = bool(square)
        # This draft's OWN spec, which is the whole point of the second bound:
        # the sheet a crop is weighed against is the one THIS draft composes,
        # never the package's largest.
        spec = draft.spec
        out_w, out_h = cell.width * scale, cell.height * scale
        # The PADDED size when one is coming: `--square` adds margin to the
        # shorter axis, and every number below — both booleans, the refusal, the
        # payload — is about the file a consumer will decode, not about the
        # intermediate crop that is never written.
        if square:
            out_w = out_h = max(out_w, out_h)
        within_console_budget = pipeline.fits_console_budget(out_w, out_h)
        within_own_sheet = pipeline.fits_own_sheet(out_w, out_h, spec)
        if not within_console_budget and scale <= DEFAULT_THUMB_SCALE:
            raise ValueError(
                f"scale {scale} on this {cell.width}x{cell.height} {subject} "
                "would write "
                + ("a square " if square else "")
                + f"{out_w}x{out_h} "
                f"= {out_w * out_h:,} pixels, over the "
                f"{pipeline.MAX_CONSOLE_CARD_PIXELS:,}-pixel console budget — the "
                "fixed ceiling on what a chat card may decode, which is NOT a "
                "comparison against this draft's own sheet (the payload answers "
                "that separately as withinOwnSheet); "
                "ask for --scale 1, "
                + "".join(f"or {remedy}, " for remedy in remedies)
                + "or --scale 3 or more to take it as a viewer artifact carrying "
                "withinConsoleBudget: false"
                + (", or drop --square to take the cell unpadded" if square else "")
            )
        # Two grounds for two consumers (operator ruling 2026-08-29): the
        # `--square` CARD crop keeps the keyed sprite's transparency — the
        # console draws its own ground (checkerboard) behind it — while the
        # bare COMPARE crop keeps the flat dark looking-procedure ground,
        # where a 1-px seam must not vanish into a viewer's flatten color.
        backdrop = (
            pipeline.TRANSPARENT_BACKDROP if square else pipeline.QA_BACKDROP
        )
        image = pipeline.upscale_on_backdrop(cell, scale=scale, backdrop=backdrop)
        if square:
            # ONE pad step, last: the crop is finished before the margin is
            # added, so nothing the looking procedure did is enlarged, keyed or
            # resampled a second time.
            image = pipeline.pad_to_square(image, backdrop=backdrop)
        # The filename is a HUMAN surface — an operator correlating a crop back
        # to the attempt it came from — so it counts the way the store's own
        # filenames count: `walk-n-attempt-3-frame-1-x2.png` sits beside
        # `revisions/row@walk-n/attempt-3.png`. The payload below stays 0-based
        # machine truth. A QA surface relabels; it never renumbers.
        # `-sq` because the two shapes are two artifacts of the same cell: a card
        # crop and a compare crop must be able to sit in the thumbs directory at
        # once, and an operator must be able to tell which is which by name.
        out = draft.directory / THUMBS_DIRNAME / f"{stem}-x{scale}{'-sq' if square else ''}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out, format="PNG")
        return {
            "scale": scale,
            # Unconditional, like the two booleans below and for the same
            # reason: a consumer deciding WHERE to draw a crop cannot infer the
            # shape from a filename, and the default is a shape too.
            "square": square,
            "path": str(out),
            "width": image.width,
            "height": image.height,
            # Both, always, at every scale — see the docstring's consumer rule.
            # A consumer that reads one and infers the other is the defect this
            # split exists to retire.
            "withinConsoleBudget": within_console_budget,
            "withinOwnSheet": within_own_sheet,
        }
