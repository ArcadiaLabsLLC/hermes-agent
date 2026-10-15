---
type: meta
tags: [meta, templates]
---

# Templates

Starting-point templates for new brain notes. Copy, rename, fill the placeholders. **Do not link to these from elsewhere in the brain** — they are cloned, not referenced.

## Available

- `new-program.md` — for `10 — Programs/`.
- `new-initiative.md` — for `20 — Active Initiatives/`.
- `new-adr.md` — for `30 — Decisions/`.
- `new-handoff.md` — for `50 — Agent Handoffs/`.

## Conventions

- Frontmatter `type:` is required: `program`, `initiative`, `queue`, `adr`, `handoff`, `map`, `cross-brain`, `open-questions`, `operations`, `meta`, `moc`.
- Tags carry the `program/<slug>` namespace.
- `cursor::` inline field on programs (single line, dated). `status::`, `blocking::` on initiatives.
- Wikilinks `[[Note]]` inside the brain; relative paths (`../../docs/<path>`) into this repo's `docs/`; a repo prefix in backticks (`EterniaLauncher/…`) for any other repo, never a link.
- Cite code by symbol and file, never by line number.
- Notes stay under ~80 lines; detail lives in `docs/`.

## After creating

1. Add the note to its index ([[Brain Index]] programs line, [[Initiatives Index]], [[Decisions Index]], [[Handoffs Index]]).
2. Touch the owning program's `cursor::` if something shipped.
3. File any finding the note surfaces into [[fork-hygiene-queue]] or the launcher's Mission Control queue — on arrival.
