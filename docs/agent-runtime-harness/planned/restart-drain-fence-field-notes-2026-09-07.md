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

<!-- filled in §4 -->

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

<!-- filled after green -->

---

## 5. Deviations

<!-- filled at the end -->
