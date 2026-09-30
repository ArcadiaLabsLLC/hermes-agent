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

The tooling pass reports 1,287 passes and one pre-existing duplicate-helper-name
failure, reproduced on main and filed in the fork-hygiene queue. The generated
contract catalog also reconciles existing schema drift against its Python models.
The validated suite and native Launcher acceptance remain in progress.
