# Prompt for Kimi Code: Fix Timeout Control Flow + Exit Code Handling

Repo: `C:\CorrisBot`  
File: `tg_codex_gateway.py`

We recently added deterministic concurrency (`_RUN_LOCK.acquire()` with small timeout) and `sessions/<session>/run.log` (START/END entries). There is now a regression/bug in the timeout path of `_run_agent()`.

## Problem

In `_run_agent()` the inner block:
- wraps `await asyncio.wait_for(proc.wait(), timeout=600)`
- on `asyncio.TimeoutError` it sets `timeout_killed = True`, does `proc.kill()`, sends `Timeout (600s). Killed.` to Telegram
- BUT it does **not** exit the normal flow afterward (the previous `return` was removed).

Consequences:
- After timeout, the function continues into normal “use collected output for Telegram response” logic.
- This can cause extra/unwanted Telegram messages (e.g. `stderr:` fallback) after a timeout.
- `proc.returncode` may remain `None` if we don't wait after `kill()`, which makes later checks unreliable.

We want: on timeout, send exactly one timeout message (plus any optional internal logging), guarantee `END` in `run.log`, and then stop further response processing for that run.

## Required Fix

1) On timeout:
- keep `timeout_killed = True`
- kill the process
- ensure pumps/typing are stopped as today
- (recommended) `await proc.wait()` after `proc.kill()` so `returncode` becomes defined
- send `Timeout (600s). Killed.` to Telegram
- then **exit the run's normal processing** (do not send final_msg/stdout/stderr content)

Implementation guidance:
- Introduce a local flag like `timed_out = False`.
- In timeout handler set `timed_out = True`.
- After the subprocess section finishes (after `finally` that stops typing), check `if timed_out: return` so it exits before the normal reply logic.
- Ensure the outer `finally` still logs `END` to `run.log` and releases `_RUN_LOCK` even when returning.

Alternative acceptable approach:
- `raise` a private exception (e.g. `_RunTimedOut`) from the timeout handler and catch it in the outer scope to return, while still executing outer `finally`.

2) Fix `END` logging details:
- Ensure `run.log` END entry records `timeout_killed=true`.
- `exit_code` should be consistent:
  - Either use the real `proc.returncode` after `await proc.wait()`, or explicitly log `exit=-1` or `exit=timeout`.
- Keep the “START always once, END always once” invariant.

3) Do not change the Busy/lock policy unless required.
- Keep Policy A “reject while busy” behavior.

## Acceptance Criteria (manual)

1) Trigger a timeout (e.g., temporarily set a very small timeout like 1s for testing, then restore 600s):
- Telegram receives only the timeout message for that run (no additional stdout/stderr/final_msg messages).
- `sessions/<session>/run.log` has a START and an END entry for that run.
- END entry shows `timeout_killed=true` and has a sensible `exit=` value.

2) Normal non-timeout run still behaves the same:
- clean Telegram final message
- file delivery directives still work
- run.log START/END appended

