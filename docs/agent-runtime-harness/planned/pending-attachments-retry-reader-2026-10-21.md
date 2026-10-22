# Planned — the write-ahead's attachment lists get their reader: a retry re-attaches the same bytes — 2026-10-21

**Owner domain:** the chat turn ([04](../04-chat-turn.md) § The write-ahead record, § Retry — D2.04);
plan [p10-turn-2026-10-19.md](p10-turn-2026-10-19.md) §3.5 (`RT-MISSION-CHAT-MESSAGE-TAKES`).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035.

Row: `RT-PENDING-ATTACHMENTS-NO-READER` (runtime-queue § Fork-owned).

## 1. What is true today (file::symbol)

- `chat_turn_commit/run.py::_write_ahead` persists on the `TURN_STATE_PENDING` record
  `pending_user_message`, and — when present — `pending_user_images` (`self.user_image_paths`, the
  stored files of pasted images) and `pending_user_files` (`self.user_files`, the reviewed
  `operator_files` paths). The comment beside them promises: "a retry or replay of this record names
  the same bytes".
- `mission_chat_turns/records.py::_JOURNAL_PATH_LISTS = {"pending_user_images": 16,
  "pending_user_files": 16}` bounds them on the record; `safe_assignment_text(limit=1024)` per path.
- **Nothing reads them.** `grep` over `agent_runtime` and `hermes_cli` finds the two writers only. Even
  `pending_user_message` has no reader: `admit.py::_replay_walk` writes it AGAIN on the replay path, and
  the retry (`admit.py::_admit_retry`, D2.04) reads the retried record only for its `state`
  (`TERMINAL_TURN_MARKERS`) and then runs the NEW request's message and attachments — the Launcher
  resends everything. So today the three `pending_*` keys are evidence on the journal, and the promise
  in the comment is unkept.

## 2. The decision: a reader, not a deletion

`Decided (plan):` **the retry is the reader.** A `retry_of` request that carries NO attachments of its
own re-attaches the retried record's `pending_user_images` / `pending_user_files` — exactly the bytes
the failed turn had, as the comment promised. A retry that carries its own attachments keeps them (the
operator changed the send). Deleting the keys instead would leave D2.04's retry dependent on the client
re-uploading files it already stored, and would delete the one durable record of what a turn carried
(the FILE: / MEDIA: lines in the mirrored row name the files but are text, not paths).

`Decided (plan):` **a stored path that no longer exists is refused, not skipped.** The retry answers
`ChatErrorKind` `attachment_missing` (a new member beside the existing attachment refusals in
`mission_chat_outcome.py`) with `safe_details: {missing: [<basename>…]}` — the operator sees which file
to re-send. Fail closed: silently dropping an image changes what the persona is asked.

`pending_user_message` keeps its one reader-shaped use (the replay walk re-stamps it) and gains none
here; it is not this row.

## 3. Stages

**A1 — the reader** (`chat_turn_commit/admit.py::_admit_retry`). After the target record passes the
terminal-state check, when `not getattr(self, "user_image_paths", ()) and not getattr(self,
"user_files", ())`: read `target.get("pending_user_images") or []` and `target.get("pending_user_files")
or []`; files re-resolve through `operator_files.resolve_refs(refs)` (the record stores the stored
paths; the ref is the stored name under `files_dir()`, which `resolve_refs` contains and sidecar-checks —
never a bare `Path(text)`), images through the image store's own resolver with the same containment
check; each must exist; set `self.user_image_paths` and `self.user_files` (`ResolvedFile`, what
`with_file_lines` consumes) from them. Missing → `attachment_missing` (beside `ChatErrorKind.FILE_INVALID`). The
write-ahead of the retry then records the same lists again (the existing `_write_ahead` code path, no
change), so the chain of retries stays self-describing.
Tests (`tests/hermes_cli/test_mission_chat_turn_files.py`, the p10-turn file, two new tests): (1) a
first send with `--file` stored through `operator_files` fails terminally (the fixture's provider
refusal), a retry naming it with no `--file` → the request text the runtime is handed carries the same
`FILE:` line and the retry's write-ahead record lists the same `pending_user_files`; (2) the stored file
is deleted between the two sends → the retry answers `attachment_missing` naming the basename, no
write-ahead record is written. Killing mutations: (1) skip the re-attach → the request text has no
`FILE:` line → red; (2) skip the existence check → the refusal test reds (a turn runs).
The same two tests for images over `user_image_paths` and `with_media_lines` (`MEDIA:` line).

**A2 — the docs line.** `04-chat-turn.md` § Retry gains one sentence: a retry without attachments
re-attaches the retried record's stored files; `attachment_missing` when they are gone. The comment
in `run.py` that made the promise is left as is — it is now true.

## 4. Out of scope

The replay walk (`_replay_walk`) — it answers from SessionDB and never re-runs a turn, so it needs no
attachments. The boot-time pending sweep. Any widening of `_JOURNAL_PATH_LISTS` caps.

## 5. Open rulings

None.
