"""The batch dispatcher — ready todo rows planned into thick lanes, run, landed once (dispatcher plan §3).

Plan ``docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md`` §3, stage B2. The
package holds no state of its own: a batch IS its manifest note in the workspace's default brain plus
the rows' claim marks; every object here is rebuilt from those on each call.

planner (policy): ``plan`` — ready rows → thick lanes by ``Domain``, budgeted by row effort, one landing;
machine (policy): the batch and lane state tables, the budget rule, the land rule;
manifest (stores): the manifest note — render, parse, fold — and its store over the W2 writer;
board_source (stores): ``BoardSource``, the production ``WorkSource`` over the boards and the writer;
lane_git (stores): where a lane works in git — worktrees beside the clone, ``--no-ff`` merges, the ff push (B5);
lane_executor (lanes): ``BatchLaneExecutor`` — a lane as one persona turn in its own worktree (B5);
lander (lanes): ``GitLander`` — ``approve``'s fast-forward push of the landing (B5);
dispatcher (lanes): ``BatchDispatcher`` — plan / start / status / stop / land / approve, settles, the tick;
rpc (lanes): ``runtime.batch.plan|start|status|stop|land|approve``, console tier.
"""

__layer__ = "models"
__all__: list[str] = []
