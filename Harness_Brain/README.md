# Harness_Brain — README

Harness_Brain is the child brain of the **Hermes Agent fork** in the Arcadia/Eternia brain network. It is a **thin navigation, decision, and handoff layer**. Canonical truth for the runtime lives in this repo's `docs/agent-runtime-harness/` tree (nine domain docs + `planned/` + `archive/`); the fork's working contract lives in `docs/downstream-development.md`; upstream's own development guide is `AGENTS.md`. This brain never restates any of them — it routes to them and records what they cannot: the WHY behind fork rulings, what is mid-flight, and how to hand work to an agent.

## What this brain is for

- Compressed orientation (`00 — Maps/`) — the fork boundary, the fork-only codebase, hard rules, vocabulary
- Per-program pointers + cursors (`10 — Programs/`) — one thin note per program, linking out to the canon
- In-flight initiatives and the domain queue (`20 — Active Initiatives/`) — what's open, what's blocking, where to resume
- Decisions (`30 — Decisions/`) — ADR-style WHY notes for load-bearing fork rulings not recoverable from `docs/` or `git log`
- Cross-brain coordination (`40 — Cross-Brain/`) — pointers + open questions for the launcher, backend and parent brains
- Pre-baked agent handoff primers (`50 — Agent Handoffs/`) — "before you touch X, read this short brief"
- Operational cheatsheets (`60 — Operations/`) — run, test, gates, known pitfalls

## What this brain is NOT for

- Runtime architecture, wire shapes, boot stages, chat-turn phases — `docs/agent-runtime-harness/00-index.md` owns them (rule: a domain doc states implemented, verified truth with a code anchor; this brain cites it).
- Upstream Hermes documentation — `AGENTS.md` and `website/docs/` are upstream's; consume, never duplicate.
- Mission Control's work queue — it lives in the launcher's brain (`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`) and covers BOTH repos. See [[0011 — One brain per repo, one Mission Control queue in the launcher]].
- Personal machine paths. Cite other repos with a repo prefix in backticks (`EterniaLauncher/...`, `eternia-backend/...`), never as a link; a relative path belongs only in a cross-brain pointer's frontmatter.

## Conventions

- Frontmatter `type:` is required (`program`, `initiative`, `queue`, `adr`, `handoff`, `map`, `cross-brain`, `operations`, `meta`, `moc`).
- Wikilinks `[[Note]]` for intra-brain references; relative paths (`../../docs/...`) for links into this repo's `docs/`.
- Keep notes ≤ ~80 lines. Link out for detail.
- Cite code by SYMBOL and FILE, never by line number — the god-file refactor moves lines under every cite.
