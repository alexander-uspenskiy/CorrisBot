# Telegram Gateway -> Looper Migration Plan

## Branch
- `feature/2026-02-13-1610-migration-to-looper`

## Goal
- Keep Telegram-facing behavior.
- Replace direct `codex exec` flow in `tg_codex_gateway.py` with file-based Looper flow.
- Use Talker looper root: `C:\CorrisBot\Talker`.

## Agreed Contracts
- Prompt transport is file-based through `Prompts\Inbox\<sender_id>`.
- Prompt filename format:
  - `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`
- Prompt must be written atomically:
  - write full content to unique temp file first
  - rename/move to final `Prompt_...md` only after write is complete
- Gateway reads one matching result file:
  - `<PromptName>_Result.md`
- Gateway forwards to Telegram what Looper console semantics shows:
  - reasoning
  - agent messages (including intermediate and final)
  - command events / command output
  - warnings/errors
- Background reaction model:
  - polling file changes (not watchdog), aligned with current Looper style
- Reset commands:
  - `/reset_session` -> reset only current sender queue/session
  - `/reset_all` -> reset whole Talker inbox

## Sender Strategy
- Sender id configurable.
- Default sender id:
  - `tg_<username>` if username exists
  - fallback `tg_<user_id>`

## High-Level Design
1. Ensure Talker looper is running (single-start behavior via `StartLoopsInWT.bat`).
2. For every Telegram prompt:
  - compute sender id
  - ensure sender folder exists
  - generate prompt filename marker with millisecond timestamp
  - atomically publish prompt file
  - watch corresponding result file in background loop
  - stream parsed events to Telegram incrementally
  - finish on `turn.completed` (with fallback timeout/error handling)
3. Keep existing `DELIVER_FILE:` behavior on streamed/final agent message chunks.

## Implementation Phases

### Phase 1: Infrastructure Wiring (no behavior parity yet)
- Add constants/config in `tg_codex_gateway.py` for:
  - looper root (`C:\CorrisBot\Looper`)
  - talker root (`C:\CorrisBot\Talker`)
  - inbox root (`C:\CorrisBot\Talker\Prompts\Inbox`)
  - polling intervals (active/idle)
- Add helpers:
  - sender id resolution
  - directory bootstrap (`Inbox`, sender dir)
  - timestamp marker generation
  - atomic prompt write (`.tmp` -> rename)
  - result path derivation from prompt path
- Add looper launcher helper:
  - run `StartLoopsInWT.bat C:\CorrisBot\Talker`
  - tolerant to already-running case
  - called at boot and safe to re-call

### Phase 2: Core Run Path Migration
- Replace `_run_agent()` direct subprocess Codex flow with Looper flow:
  - remove direct `codex exec` call path from runtime usage
  - create prompt file in sender inbox
  - poll corresponding result file for growth
  - parse appended lines and emit Telegram updates
- Keep gateway single-run lock behavior (`_RUN_LOCK`) to preserve current serial execution semantics.

### Phase 3: Result Streaming Parser
- Implement parser for Looper result stream:
  - handle JSON event lines where present
  - handle non-JSON lines (header/log text)
  - map events to Telegram-safe text format
- Streaming strategy:
  - send chunks on new meaningful events
  - avoid duplicate sends via last-offset + last-emitted markers
- Completion detection:
  - primary: `turn.completed`
  - fallback: explicit failure markers / timeout

### Phase 4: Command Surface and Reset Semantics
- Keep existing Telegram commands where valid.
- Add new commands:
  - `/reset_session`
  - `/reset_all`
- `/reset_session` behavior:
  - target current sender folder only
  - clear prompt/result files and sender `loop_state.json`
  - recreate minimal sender structure
- `/reset_all` behavior:
  - clear all sender directories under Talker inbox
  - preserve top-level inbox and service files if needed
- Keep old `/reset` and `/new_session` as aliases (optional), but map to new semantics and document.

### Phase 5: Cleanup and Backward Compatibility
- Mark direct Codex session persistence fields as deprecated or remove if no longer used:
  - `_CODEX_SESSION_ID`
  - fresh/resume flags
  - old session id extraction/persistence helpers
- Keep logs (`sessions/`) for gateway operational debugging where still useful.
- Ensure `/agent`, `/loginstatus`, and related texts do not mislead after migration.

## Data/Filesystem Model
- Write path:
  - `C:\CorrisBot\Talker\Prompts\Inbox\<sender_id>\Prompt_<marker>.md`
- Result path:
  - same folder, `Prompt_<marker>_Result.md`
- Sender state:
  - managed by Looper (`loop_state.json`) in sender folder
- Gateway temp files:
  - keep local gateway temp usage minimal and isolated

## Polling Model (Gateway Side)
- Active result streaming:
  - poll file size/mtime every ~200-300ms
- Idle wait before first bytes:
  - poll every ~500-1000ms
- Read strategy:
  - incremental read by byte offset
  - UTF-8 decode with replace on errors

## Error Handling Plan
- If looper launch fails:
  - send actionable Telegram error
  - do not write prompt
- If prompt file cannot be published atomically:
  - report failure to Telegram
- If result file never appears within initial window:
  - report timeout and suggest `/reset_session`
- If parsing fails for a line:
  - keep raw fallback text; do not break stream

## Testing Plan

### Smoke
- Start gateway; verify Talker looper auto-start attempt.
- Send one Telegram prompt:
  - prompt file appears in sender inbox
  - result file appears
  - intermediate messages are streamed
  - completion message arrives

### Reset
- `/reset_session`:
  - only current sender folder is reset
- `/reset_all`:
  - all sender folders are reset

### Delivery Directive
- Ensure `DELIVER_FILE:` directives still trigger Telegram file delivery.

### Stability
- Send several prompts sequentially and verify:
  - no duplicate chunks
  - no stuck busy lock
  - consistent completion detection

## Rollout Sequence
1. Implement Phase 1-2 behind a runtime switch (temporary safety flag).
2. Validate on local private chat.
3. Enable by default; keep old path for one short transition window.
4. Remove old direct Codex path after confidence checks.

## Risks and Mitigations
- Risk: duplicate/out-of-order streamed chunks.
  - Mitigation: strict offset tracking and event de-duplication.
- Risk: stale result files causing false reads.
  - Mitigation: derive expected result path from exact prompt marker.
- Risk: reset commands deleting too much.
  - Mitigation: explicit scoped paths and dry-run logging before delete in initial build.

## Out of Scope (for this migration)
- Multi-bot/multi-channel orchestration policies.
- Architectural changes inside Looper itself.
- Watchdog/event-driven rewrite.

