# Field notes — the restart drain fence, hermes half (2026-09-07)

The hermes half of the launcher plan `restart-drain-fence.md` (rulings RS-3 and
RS-4, its Stage 2). Written AS THE WORK HAPPENED, so the order of the sections
below is the order the facts arrived, not a tidy retelling. The launcher half of
these notes lives beside the plan in the launcher repo.

Branch `fix/serve-drain-lock-order`, worktree `drain-lock-order`, from
`c670168049`.

---

## 1. What the shutdown order ACTUALLY is today (RS-3, before any edit)

Read, not guessed, in `hermes_cli/harness_parts/serve.py`:

- the drain op handler calls `ServeSocketServer.begin_drain()` on the loopback
  lane and the gateway lane, which closes the LISTENER and emits
  `serve_socket_draining` (`agent_runtime/serve_socket.py`);
- the drain monitor then waits for the in-flight requests;
- `_finish_drain` runs `frames.emit(frame)` → `_broadcast_lanes(frame)` →
  `_close_socket_lane(reason="drain")` → `_unregister_instance()` →
  `_note_end("drained")` → `_write_end()`;
- `_close_socket_lane` swaps the four lane handles under `lane_lock` and then,
  outside it, closes gateway → hub → server → **`lock.release()`**.

**So the order RS-3 asks for is already the order the code runs**: listener
closed → in-flight work drained → socket lock released → register row
unregistered → ended note → exit. The release is the LAST act of
`_close_socket_lane`, and `_unregister_instance` is the statement after it.

That is the answer to the question the plan asked for out loud: the red-first
order test was written first and it was **GREEN on the pre-fix tree** for its
ordering assertions, and RED for the two facts the order alone does not carry —
the `draining_at` sidecar and the `serve_instance_unregistered` line. The reds
are quoted verbatim in §3.

The field's real defect (plan §0, 16:25:23.613) is therefore NOT a wrong order.
It is that the correct order still holds the lock for the whole in-flight wait
— 14 s in the field — while the listener is already closed, and a contender
arriving in that window cannot tell "alive and leaving" from "alive and
serving". That is exactly the hole RS-4 fills, and RS-3's contribution is the
two facts that make the telling possible: a sidecar that says it is leaving and
a line that says when the row went.

---

## 2. What was built

**`agent_runtime/serve_socket.py`**

- `SOCKET_OWNER_DRAINING_KEY = "draining_at"`, and two module constants:
  `SOCKET_LOCK_DRAIN_WAIT_SECONDS = 25.0` (named once, with the launcher's 20 s
  `drainDeadline` cited beside it) and `SOCKET_LOCK_DRAIN_POLL_SECONDS = 0.25`.
- `SocketLockResult.waited_for_drain_ms`, on the object and — when a wait
  happened at all — on `payload()`, so it rides both endings.
- `SocketOwnerLock.__init__` takes `clock` and `sleep`, defaulted to
  `time.monotonic` / `time.sleep`, the same injection `HelloRateLimiter`
  already uses. Production passes neither; a test pins that (§4).
- `SocketOwnerLock._owner_is_leaving` — live pid AND (`draining_at` stamped OR
  no `serve_instances/<pid>.json`). Anything the probes cannot answer is NOT
  leaving.
- `SocketOwnerLock._wait_for_drain` — sleep-then-try, so the first lap is not a
  duplicate of the attempt that got us here; returns `(handle, failure,
  waited_ms)`.
- `SocketOwnerLock.mark_draining()` — REWRITES the published sidecar (the port
  and the boot id survive; the drain must not blank a record clients are still
  discovering by) with `draining_at`.
- A takeover is now either proof: the owner was already dead, or it let go while
  we waited. Same `took_over_from` word, because the launcher's question is the
  same one.

**`hermes_cli/harness_parts/serve.py`**

- The drain op calls `socket_lock.mark_draining()` between `frames.emit` and the
  `begin_drain()` loop — before the listener closes, which is the whole point.
- `_unregister_instance(reason=…)` emits one `serve_instance_unregistered` line
  on the service log when the row actually goes, and the pre-existing
  `serve_instance_unregister_failed` line grew the same `reason`. The three call
  sites say `drain`, `drain_abandoned`, `shutdown`.

**Canon**: the `serve_socket.py` module docstring's "does not fail and does not
retry" sentence now says when it DOES retry; the `SocketOwnerLock` class
docstring grew a third owner shape ("A LEAVING owner is worth waiting for");
`docs/agent-runtime-harness/03-transport-and-wire.md`'s socket-ownership
paragraph gained the draining sidecar, the new line, and the bounded wait.

---

## 3. The reds, quoted

### 3.1 RS-3, the order — GREEN before the fix, and that is the finding

`tests/hermes_cli/test_harness_serve_drain_order.py::test_drain_releases_the_lock_before_it_drops_the_row`
passed on the first run against the pre-fix tree. The recorder's list, printed
by pytest in the sibling failures' fixture repr, is the receipt:

```
drain_recorder = {..., 'steps': ['listener_closed', 'lock_released', 'row_unregistered', 'ended_note']}
```

Two of the three tests in that file were red, and both are RS-3's *other* half
— the facts a contender reads from outside the process:

```
>       assert isinstance(sidecar.get("draining_at"), str)
E       AssertionError: assert False
E        +  where False = isinstance(None, str)
E        +    where None = <built-in method get of dict object at 0x…>('draining_at')
E        +      where <…>.get = {'boot_id': '2cce4c9…', 'host': '127.0.0.1', 'pid': 25420, 'port': 49695, ...}.get
```

```
>       assert len(rows) == 1, [r.get("event") for r in run["sink"].service_log()]
E       AssertionError: ['serve_socket_accept_loop_exit', 'serve_socket_draining']
E       assert 0 == 1
E        +  where 0 = len([])
```

The second red's message is the whole point in one line: the ONLY structured
events a whole drain put on the service log were the accept loop's exit and the
drain announcement. Nothing marked the moment the register row went.

### 3.2 RS-4, the bounded wait

`tests/agent_runtime/test_serve_socket_drain_wait.py` did not even import:

```
tests\agent_runtime\test_serve_socket_drain_wait.py:37: in <module>
    from agent_runtime.serve_socket import (
E   ImportError: cannot import name 'SOCKET_LOCK_DRAIN_POLL_SECONDS' from 'agent_runtime.serve_socket' (X:\…\agent_runtime\serve_socket.py)
```

An import error is a weak red — it says the constant is missing, not that the
behaviour is. So the two constants, the result field and the injected
clock/sleep landed first, WITHOUT the wait, and the red was taken again:

```
>       assert result.acquired is True
E       AssertionError: assert False is True
E        +  where False = SocketLockResult(outcome='lock_held_by', pid=34888, path='…\serve_socket.lock',
E                          owner_started_at='2026-09-07T16:25:09.771Z', took_over_from=None,
E                          waited_for_drain_ms=None, owner_state='pid_running').acquired
```

```
>       assert result.waited_for_drain_ms == int(SOCKET_LOCK_DRAIN_WAIT_SECONDS * 1000)
E       AssertionError: assert None == 25000
```

`owner_state='pid_running'` with `waited_for_drain_ms=None` beside a sidecar
that says `draining_at` is the field's 16:25:23 line reproduced at the unit
seam: the contender knew the owner was alive, had the word "leaving" on disk in
front of it, and refused without waiting a single lap.

3 failed, 3 passed — the three that passed are the arm that must not change
(a healthy owner refused at once), the constants' pin, and the production
defaults' pin.

---

## 4. The mutation table

Each row: one production behaviour removed or inverted, both new test files run,
the verdict quoted. Taken after green, restored from a scratch copy each time —
the tree ends byte-identical (`git diff --stat` re-checked).

| mutation | which tests red |
|---|---|
| `_wait_for_drain()` call removed from `acquire` | `test_serve_socket_drain_wait.py::test_a_draining_owner_is_waited_out_and_the_lane_is_taken`, `::test_an_owner_that_dropped_its_register_row_counts_as_leaving`, `::test_a_wait_that_expires_degrades_as_today_and_says_how_long_it_gave` — **3 failed, 6 passed** |
| `socket_lock.mark_draining()` not called at drain start | `test_harness_serve_drain_order.py::test_the_sidecar_says_it_is_leaving_from_the_first_drain_event_on` — **1 failed, 8 passed** |
| `_finish_drain` drops the row BEFORE it releases the lock | `test_harness_serve_drain_order.py::test_drain_releases_the_lock_before_it_drops_the_row` — **1 failed, 2 passed**, `At index 1 diff: 'row_unregistered' != 'lock_released'` |
| the register-row arm of `_owner_is_leaving` returns False | `test_serve_socket_drain_wait.py::test_an_owner_that_dropped_its_register_row_counts_as_leaving` — **1 failed, 5 passed**, and only that one, so the two arms are independently pinned |
| `serve_instance_unregistered` renamed | `test_harness_serve_drain_order.py::test_the_moment_the_register_row_goes_is_one_line_on_the_service_log` — **1 failed, 2 passed** |

Nothing here is a kill-proof for the constants themselves; those are pinned by
value in `test_serve_socket_drain_wait.py::test_the_bound_is_one_named_constant_above_the_launchers_drain_deadline`,
and the production defaults by `::test_the_default_wait_uses_real_time_and_is_not_left_to_the_caller`.

---

## 5. Deviations

**1. Three existing tests grew a register row, and it was a REAL red, not a
cosmetic one.** `test_serve_socket_lane.py::test_a_live_owner_is_refused_exactly_as_before_and_nothing_is_taken_over`
took **25.09 s** after the wait landed (pytest `--durations`) — it passed, but
through the drain wait, describing the wrong scenario. Its incumbent was a bare
sidecar naming a live pid with no registry row, which under RS-4 reads as an
owner that has already unregistered. Two more had the same shape:
`::test_the_second_serve_for_a_root_degrades_to_stdio_and_names_the_owner`
(fabricated pid 4242, whose liveness is the box's business — a latent
machine-dependent 25 s) and
`test_serve_gateway_lane.py::test_a_socket_lock_lost_to_a_live_owner_names_the_holder_on_the_gateway_block`.
All three now write `serve_instances/<pid>.json` through a `_serving_row`
helper, which is them saying out loud the thing they always meant: *alive **and
serving***. Timing back to baseline afterwards (three files: 23.8 s on this
branch vs 22.8 s at `c670168049`).

**2. A second module constant.** The plan says "one named constant, module
level" for the 25 s bound; the poll cadence is a second one,
`SOCKET_LOCK_DRAIN_POLL_SECONDS`. The ruling's "once" is about the BOUND — the
number that has to stay in step with the launcher — and a bare `0.25` in a loop
would have been a magic number the tests could not name. The launcher-facing
constant is still spelled exactly once.

**3. The order test was green before the fix.** Stated in §1 and §3.1 rather
than engineered around. The plan explicitly allowed either answer; the honest
one is that the shutdown order was already right and the field defect was the
lock's *duration*, not its *position*.

**4. Line-number cites in three canon docs were repointed.** Inserting into
`hermes_cli/harness_parts/serve.py` shifted six `serve.py:<n>` cites in
`03-transport-and-wire.md`, `04-boot-and-lifecycle.md` and `07-observability.md`
by +21/+33 lines; `tests/scripts/test_doc_cite_adjacency.py` caught all six
(`UNWAIVED FAILURES: 6`) and passes after the repoint. Nothing in those
sentences changed — only the numbers.

**5. Not done, and not in scope.** The plan's Stage 3 (RS-6, `code_tree` on the
register row) is a separate stage and is untouched here. The `serve_instance_unregistered`
line is on the service log only — it is deliberately not a new frame kind, for
the same reason `serve_socket_owner_takeover` is not.

**6. The order test arms the end-reason recorder.** `record_end_reason=True` is
what writes the ended note, and arming it installs a process-wide console
control handler on Windows; the test monkeypatches
`_install_console_ctrl_reason_handler` to a no-op so a unit test does not leave
one on the pytest process.
