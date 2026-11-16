# Cold Windows pre-push startup — 2026-11-15

`FH-WORK-V1-CLAIM-GATES-WINDOWS-BUDGET`. Windows host MUltiversalLabsInc, 32 logical processors, Git Bash and shared Python 3.14 test venv. Cold refers to a new locked Git worktree with no `scripts/__pycache__`, at ordinary OS cache temperature. The normal `scripts/prepush.sh` queue and text path ran with `HERMES_GATE_CACHE=0`. Each run executed and passed 172 tests in 11 files. Startup spans are process output arrivals observed by a monotonic stopwatch. Gate, runner and doc-cite walls come from their existing output.

## Quiet verification on the current gate

Fresh worktree `80088d91fc752d6b8d72230086ea6e6cc05509b3`, which contains the current work-count contract from `2a1c39e647`. CPU before was 1%, 1%, and 0%; after, 5%. One- and five-minute MSYS load were 1.69/1.69 before and 1.85/1.73 after. This meets the row's original quiet-Windows screen of load below 2.

The gates started 1.714 s into the command, the existing interpreter check printed at 2.621 s, and the bundled runner took over at 2.696 s. The gate start to runner handoff was **0.982 s**. The 11-file gate batch used its 11-file work allowance, passed 172 tests with a 7.3 s runner wall, and took **8.4 s** in the gate's timer at MSYS load 1.69. Doc-cite passed in 0.9 s, with one walker of one allowed. The command returned green with every step completed.

## Earlier readings

Source `a4f1445badcad3741ec6afd389aacea206ce7026`, before the work-count contract. Run 1 used a new worktree.

| Run | CPU before / after | Gate start → bundled runner handoff | Test-runner wall | Gate wall | Doc-cite |
| --- | --- | ---: | ---: | ---: | ---: |
| First run in fresh worktree | 5%, 3%, 2% / 3% | 2.549 s | 4.9 s | 7.9 s | 1.3 s |
| Warm 1 | 4%, 4%, 8% / 2% | 3.270 s | 4.2 s | 8.3 s | 0.6 s |
| Warm 2 | 4%, 8%, 2% / 2% | 2.860 s | 6.7 s | 10.0 s | 1.3 s |

Warm 2 emitted a budget heartbeat and logged MSYS load 6.34 despite low sampled Windows CPU. The first two runs finished within the budget and the old command only logged MSYS load on overruns. The earlier sample set captures startup variability; the fresh run above verifies the original load screen.

The source path starts the selected shared interpreter to import pytest, checks the selected Python minor and runtime extras, then resolves the real store root and verifies the interpreter sits outside it. The fallback memoizes the successful pytest probe and the root probe also answers the interpreter guard (`scripts/_fork_test_env.sh`). The bundled path reaches the small-file bytecode check and skips the whole-tree precompile. The startup span includes Bash, path and environment setup, and the wrapper handoff. The measured quiet run verifies the landed startup cuts with all those guards active. Work-count and hang-guard policy was delivered separately by `FH-PREPUSH-STEPS-REPORT-WORK-NOT-TIME`.
