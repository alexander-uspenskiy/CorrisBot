# Prompt for Kimi Code: Fixes After Session 2 Review (C:\CorrisBot)

You are working in repo `C:\CorrisBot`. The gateway is `tg_codex_gateway.py` (Telegram polling via `python-telegram-bot`) and runs Codex CLI as a local agent.

Goal: implement small but important correctness fixes discovered while reviewing “session 2” artifacts in `sessions/session_20260209_185448/`, plus add minimal concurrency protection and better session metadata.

Do NOT change behavior unrelated to these items.

## Context (what was observed)

Artifacts for session 2 are stored here:
- `sessions/session_20260209_185448/meta.txt`
- `sessions/session_20260209_185448/stdout.log`
- `sessions/session_20260209_185448/stderr.log`

The logging design is intentional:
- `stdout.log` holds only the assistant final message (via `--output-last-message`) so Telegram stays clean.
- `stderr.log` contains the full Codex CLI stream output (including headers / thinking / tokens used). This is expected and should stay, unless you have a strong reason to change it.

## Issues to fix (must-do)

### 1) `/setagent` handler is buggy even though “agent switching” is not really implemented yet

Problem: `cmd_setagent()` tries to validate the agent name by calling `_agent_cmd(name, "ping", None)` but `_agent_cmd()` signature is `_agent_cmd(agent: str, output_path: Optional[str]) -> List[str]`. This would crash or always fail validation.

Required fix:
- Make `/setagent` behave consistently with the actual supported agents.
- If only `codex` is supported, `/setagent codex` must succeed, and any other name must produce a clear “unknown agent” response.
- Do not add new agents in this change; just correct the validation / bug and keep the command accurate.

Acceptance criteria:
- `/setagent codex` works.
- `/setagent somethingelse` returns “Unknown agent … Supported: codex”.
- No exceptions thrown in the handler.

### 2) Prevent parallel Codex runs (concurrency protection)

Problem: Two Telegram messages can arrive close together and start two `_run_agent()` executions concurrently, creating multiple Codex processes in parallel. This is a correctness and resource-risk issue.

Required fix:
Implement one of these policies (pick one, but do it cleanly and document it in code comments and `/help` text):

Policy A (simplest, recommended):
- Add a global `asyncio.Lock` (or per-chat lock) guarding the Codex execution section.
- If a run is already in progress, reply immediately with a short message like `Busy. Try again in a moment.` and do NOT queue the request.

Policy B (sequential queue):
- Add an `asyncio.Queue` and a single background worker that processes prompts sequentially.
- Incoming prompts are queued; user gets `Queued (#N)` or a short acknowledgment.
- Consider how `/reset` interacts with queued items (at minimum: keep it simple and predictable).

Do NOT implement “cancel previous run” in this pass unless you can do it reliably without leaving orphan processes.

Acceptance criteria:
- It is impossible for two Codex processes to run at the same time from this gateway instance.
- Behavior under burst messages is deterministic (either reject while busy, or queue sequentially).

### 3) Expand session metadata (`meta.txt`)

Problem: `meta.txt` currently only contains the session start timestamp; it is not sufficient for debugging.

Required fix:
On session creation (`_create_new_session_dir()`), write more metadata, minimally:
- timestamp (existing)
- gateway script version marker (could be git commit if available, otherwise `unknown`)
- working directory
- allowed chat id
- current agent name
- initial console mode
- whether codex resume mode was already active at session start (`_CODEX_HAS_SESSION`)

Keep it simple: plain text key/value lines are fine.

Optional (nice to have):
- add a `run.log` file inside each session directory and append `[RUN] ...` lines there (the gateway already prints `[RUN] ...` to console, but per-session run log helps).

Acceptance criteria:
- New sessions have richer `meta.txt`.

## Non-goals / keep as-is

- Do not remove full Codex stream logging. The presence of “thinking” in `stderr.log` is acceptable and expected.
- Do not change `.gitignore` rules in this task.
- Do not refactor the whole gateway; stick to targeted changes.

## Quick code pointers (where to edit)

File: `tg_codex_gateway.py`
- `/setagent` handler: `cmd_setagent()`
- agent command builder: `_agent_cmd()`
- session creation: `_create_new_session_dir()`
- run entry point: `_run_agent()`
- help text: `cmd_help()` (update if you change concurrency behavior)

## Suggested minimal implementation sketch (Policy A)

1) Add at module level:
   - `_RUN_LOCK = asyncio.Lock()`
2) In `_run_agent()`, try non-blocking acquisition:
   - If locked: reply `Busy...` and return
   - Else: `async with _RUN_LOCK:` around the entire process lifecycle (spawn -> pump -> wait/timeout -> cleanup -> telegram reply)

Note: make sure typing indicator and pump tasks always stop in `finally`, even when returning early due to “busy”.

## Test checklist (manual is fine)

1) Start gateway, send two messages quickly:
   - second message should be rejected or queued (depending on your policy), but must not start another Codex process concurrently.
2) Run `/setagent codex` then `/agent`:
   - should show `current_agent = codex`
3) Run `/new_session` then verify new `sessions/session_*/meta.txt` includes the new fields.

