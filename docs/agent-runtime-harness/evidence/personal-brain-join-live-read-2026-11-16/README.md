# Live read: a second computer's personal-brain press joins the first one's repository (w1115e-pb, 2026-11-16)

Row `RT-PERSONAL-BRAIN-JOIN-ON-A-SECOND-COMPUTER-READ-LIVE` (group workspace-absorbs-projects). Owner ruling 2026-11-16, "yes use my login": the read may use the machine's GitHub login (`STAGEC_QA_MACHINE_GITHUB=1`). Feature under read: `agent_runtime/work_store/default_brain.py::_adopt_personal_remote` (80c265ea0d), served from a hermes worktree at origin/main 17fd50b529 (`hermes_checkout` pinned; the serve's command line named that worktree). No token was read, printed or written.

## The owner's repository, before and after

- Before: `nekwo/eternia-work-personal` private, `main` at `34c7971f14` (the skeleton commit of 2026-11-14), 0 rows in `Work_Brain/TODO.md` and the queue note.
- During: two rows, both titled `QA-PB-TEST-2026-11-16 …`, nothing else changed (`git diff --stat 34c7971 HEAD`: one file, 2 insertions).
- After: one ordinary commit `0e3a09f42f` removed them. Its tree is byte-identical to `34c7971`'s (`e5689252b9…` both). 0 rows. Still private, same name. Nothing was force-pushed, deleted or renamed, and no repository was created.

## 1. Two QA copies on one login (Eternia's press, Linux, Xvfb, fixture model)

Two lane sessions, so two lane namespaces: `pb1` = `stagec-smoke-lane-36f3ce3f2a`, `pb2` = `stagec-smoke-lane-1cc27de84f`. Eternia QA build of `0a28ea443c`, run one at a time, each in the launch's memory-capped scope.

- **First copy** (`1_first_copy_offer.png`): AI › Tasks › Personal offered "creates a private GitHub repository eternia-work-personal under nekwo". The repository already existed, so pressing `mission_control.board.brain.make_remote` JOINED it rather than making one. The serve log shows `git.remote_adopted outcome added_fetched`, then `work.brain_joined {rows: 0, commit: null, url: https://github.com/nekwo/eternia-work-personal.git}`, then `work.brain_promoted declaration personal`. The binding moved to `…/personal/brain-remote` with `joined_from` set. After a refresh (`2_first_copy_joined.png`) the strip reads "Your To-do brain is backed up to https://github.com/nekwo/eternia-work-personal.git."
- **Second copy**: one row was written to its LOCAL personal brain through hermes' own `runtime.work.start` writer (`store.start`), from a Python step in the serve's namespace. Eternia's New task sheet refuses that title as a task, because `QA-PB-…` reads as a row ID, so the row was written as a subtask (`group: qa-pb-test-2026-11-16`). Then the press. The clone ran (`git.remote_adopted outcome added_fetched`), but the press ended as `work.brain_promote_refused reason push_refused`. The QA push fence in the Work writer (`namespace.qa_blocked_push_url`, RT-WORK-QA-NAMESPACE-PUSH-FENCE: a `stagec-*` namespace pushes to a local origin only) refused the fold commit. The binding and both brains went back to how they were, as `_adopt_personal_remote` promises, and the remote stayed at `34c7971`. So a QA copy cannot show the fold of a second computer's rows end to end: filed `RT-QA-COPY-CANNOT-READ-A-PERSONAL-BRAIN-JOIN-THAT-CARRIES-ROWS`. In the same sitting (`3_second_copy_after_fenced_press.png`), the strip read the offer again, not the refusal with Retry. That screenshot was taken about 0.3 s after the refusal receipt, so whether the strip lags is a guess and was not reproduced.

## 2. Two installs on one login, outside any QA namespace (the same function the press calls)

Two fresh `HERMES_HOME`s with no namespace, run from the same hermes worktree, on the machine's GitHub login:

- Home A: `promote_default_brain('personal')` returned `outcome: joined`, `fold_commit: null`. A row, `WORK-Q6NVBX` "QA-PB-TEST-2026-11-16 first computer row", then went straight to the remote (`951e2399d9`).
- Home B: a row, `WORK-NCI5AN` "QA-PB-TEST-2026-11-16 second computer row", was written LOCALLY (the remote stayed at `951e2399d9`). Then `promote_default_brain('personal')` returned `outcome: joined`, `fold_commit: 95f2d786c9` ("work: append WORK-NCI5AN harness").
- `eternia-work-personal` then held both rows, each ID kept, in `Work_Brain/20 — Active Initiatives/work-queue.md`. No `eternia-work-personal-2` or other repository was made. The script did not set up logging, so these two runs' `work.brain_joined` receipts were not captured. The receipt was read live in part 1, and the binding's `fold_commit` and the remote commit stand for it here.

## Cleanup

Both QA copies were stopped through `kill_launcher` (`machine_github_folders_removed: 1` each, no namespace process left). Xvfb `:4` was stopped by pid. The temporary homes and clones were deleted. The two lane namespaces stay for the sweep. `pb1`'s personal binding still names the owner's repository, and the QA push fence keeps it from pushing there.
