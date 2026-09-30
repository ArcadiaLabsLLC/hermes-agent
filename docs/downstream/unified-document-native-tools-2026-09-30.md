# Native document tools

The Launcher unified-document slice uses the existing app-function registry.
Independent native conversations previously had no path to that registry.

The native worker now discovers the same tools before building its agent. Its
request transport forwards through the exact Launcher connection that admitted
the turn. The serve layer supplies the proven caller origin; model arguments
cannot replace it. The Launcher dispatcher still owns all capability policy.

One shared pool bounds native requests. Each request dispatches once; observing,
reopening or retrying the turn never retargets or replays it. Cancelled or settled
turns cannot start new calls. Worker loss keeps the ordinary uncertain outcome.
Native history, server-request lifetime and tool registration retain their
existing owners. There is no new capability registry, endpoint or document store.

The additive gateway seams wrap agent construction and bind/reset its turn's
app-function context. Native-source construction waits until the turn binds its
client; ordinary gateway consumers retain their existing construction path.
Both in-process and subprocess workers, including isolated compute hosts, use
this composition. The generated wire catalog comes from the registered model.

Consumer: `EterniaLauncher/docs/companion/planned/UNIFIED_GENERATIVE_UI_2026-09-30.md`.
Verification: 190 related tests and 25 final native/app-function tests pass.
Real agents execute tools through subprocess, isolated-compute and in-process
workers. Removing the active-turn check or preserving a forged caller origin
reddened its behavioral assertion; both mutations were restored.

Internal app-function waiters are excluded from user question projections in
normal reads, recovery and observation; client answers cannot settle them.
A planted projection leak failed the real-agent test before the fix. All three
worker modes pass that test, including the forged-answer refusal.

## Qualification — 2026-09-30

The validated run completed: 2,173 files, 24,623 passed, 108 failed, 733 skipped
in 1,556.7 seconds on Windows/Python 3.13.15. This is not a green full suite.
A 50-file comparison on unchanged primary `3c885f1232` reproduced 101 of those
108 failed assertions, plus the same four nonzero exits after passing assertions
and ten collection failures. Existing queue owners retain these failures.

The remaining seven assertions are: two worktree fleet-identity expectations;
two startup probes redirected through the primary virtualenv; the known realm
history ordering race (previous primary reproduction is recorded in chat-first
qualification); one strict Windows XPASS; and missing `distlib` in the native
wrapper publication fixture. No wrapper was rerun for comparison: the host-freeze
investigation remains parked. These files and their runtime paths are unchanged
by this slice. No test expectations or ceilings were weakened.

Tooling before the final rebase: 1,328 passed, three existing failures (duplicate
helper names and the two discussion ladder assertions), all reproduced on
primary. The generated contract catalog reconciles existing model/schema drift.
Incoming phone packaging changes were rebased cleanly. The final 19-file
gate run repeats 1,328 passes and those same three baseline failures; native
worker acceptance (four tests) and embedded phone acceptance (six) pass.

Launcher acceptance uses an isolated local model fixture through the real native
worker and app-function dispatcher: create, inspect and refine one mixed document.
No provider keys or operator profile data are needed for this proof.
