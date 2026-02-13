# Follow-up Prompt for Kimi Code: Concurrency Semantics + Run Log

Repo: `C:\CorrisBot`
File to change: `tg_codex_gateway.py`

This is a follow-up “work on mistakes” prompt. Some fixes are already present in the current code:
- `/setagent` is now validated against only `codex` and no longer calls `_agent_cmd()` with wrong args.
- Session `meta.txt` is already “rich” (timestamp/version/workdir/allowed_chat_id/agent/console_mode/resume flag).
- Concurrency guard `_RUN_LOCK = asyncio.Lock()` exists and `_run_agent()` uses `async with _RUN_LOCK:`.

Goal now: make the *busy/queue behavior deterministic* and add a per-session `run.log`.

## 1) Fix remaining concurrency race: deterministic “busy” behavior

Current behavior in `_run_agent()`:
- It does `if _RUN_LOCK.locked(): reply Busy; return`
- Then later does `async with _RUN_LOCK: ...`

Problem:
- This is a time-of-check/time-of-use race. Two requests can pass the `locked()` check before any one acquires the lock.
- Result: the second request might not get “Busy”; instead it will silently wait at `async with _RUN_LOCK:` and run after the first finishes (implicit queue).

Pick ONE explicit policy and implement it cleanly:

### Policy A (recommended): reject while busy (no queue)

Requirements:
- If a run is in progress, the next request must *always* respond immediately with `Busy...` and must not wait/queue.
- Never run two Codex processes concurrently.

Implementation suggestion (works with asyncio):
- Do not rely on `locked()` + `async with`.
- Use an explicit non-blocking acquire pattern:
  - `try: await asyncio.wait_for(_RUN_LOCK.acquire(), timeout=0)` (or a tiny timeout like 0.001 if zero is flaky)
  - On `asyncio.TimeoutError`: reply Busy and return
  - On acquire: `try: ... finally: _RUN_LOCK.release()`

Notes:
- Keep the lock held for the entire run lifecycle: spawn -> pump -> wait/timeout -> cleanup -> Telegram reply.
- Ensure typing and pump tasks are stopped in `finally` even on exceptions/timeouts.

Update `/help` Notes accordingly (it already mentions Busy; keep it accurate).

### Policy B: explicit queue (sequential processing)

If you prefer “always queue”:
- Remove the `Busy` response entirely.
- Keep the lock, but then update `/help` text to say requests are queued and processed one at a time.
- Optional: send an immediate “Queued” message (but that can get spammy).

## 2) Add per-session `run.log` (required)

Currently the gateway prints `[RUN] ...` to console. Add a per-session file to make session debugging easier:
- Create/append `sessions/<session>/run.log`
- Append at least (one START and one END line per run, or a single combined line if you prefer):
  - timestamp
  - event type: `START` / `END` (or equivalent)
  - chat_id and username/full_name (if available from `update.effective_user`)
  - prompt length in chars (not the full prompt text)
  - command array used (stringified)
  - session dir name
  - result: exit code, and whether it was `timeout_killed=true|false`
  - duration_ms (recommended; required if easy)

Constraints:
- Do not log the full prompt text to `run.log` (privacy + size). Keep it metadata-only.
- Continue writing Codex stdout/stderr streams to `stdout.log` / `stderr.log` as currently done.

Where:
- Ideally: on each `_run_agent()` start/end.
- Ensure END record is written even on exceptions/timeouts (use `try/finally`).

Format suggestion (keep ASCII, single-line):
- `2026-02-09 20:51:59 START chat_id=... user=@... prompt_len=1234 session=session_... cmd=[...]`
- `2026-02-09 20:52:22 END chat_id=... exit=0 timeout_killed=false duration_ms=23000`

## Acceptance Criteria

1) Two quick Telegram messages:
- Either the second always gets `Busy...` (Policy A) OR the help text clearly says it is queued (Policy B).
- Never two concurrent Codex processes.

2) No new exceptions in normal operation.

3) Each run appends exactly one START and one END entry to `run.log` (or one combined entry).
