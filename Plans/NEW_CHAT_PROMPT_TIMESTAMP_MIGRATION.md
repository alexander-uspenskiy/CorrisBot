# Prompt For New Chat: Timestamp Queue Migration

Read this context file first:
- `C:\CorrisBot\Looper\NEW_CHAT_CONTEXT.md`

Task:
Migrate looper queue logic from index-based prompt files (`Prompt_0000.md`) to timestamp-based prompt files.

## Goal
Replace "wait for exact next index" with "find next unprocessed prompt by timestamp" while preserving sender-based queue isolation and global fairness across senders.

## Required Filename Pattern
Primary format:
- `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`

Optional:
- deterministic suffix after timestamp is allowed (example `_t001`) if parser remains strict and unambiguous.

## Required Behavior
1. Per-sender queue remains independent.
2. Per-sender state stores last processed timestamp marker (watermark), not next numeric index.
3. For each sender, candidate is oldest unprocessed prompt by parsed timestamp.
4. Global pick is oldest among sender candidates.
5. Ignore result files (`*_Result.md`) in prompt scan.
6. If filename has prompt prefix but invalid timestamp format:
- skip file
- log warning once (not spam every loop)
- warning color/severity should remain warning-like (`darkyellow`/similar)

## Assumptions (already approved)
- Single local machine.
- One writer per sender directory.
- Writers create temp file and rename to final timestamp name at completion.
- No processed registry required; per-sender timestamp watermark is enough.

## Compatibility / Migration
- Existing state files may still contain old `next_index`.
- Add safe migration/fallback handling so loop does not crash on old state.

## Constraints
- Do not change WT launcher behavior (`StartLoopsInWT.*`) in this task.
- Keep existing sender scheduling semantics except replacing index logic with timestamp logic.
- Keep logging and console behavior style as close as possible.

## Deliverables
1. Code changes in `codex_prompt_fileloop.py`.
2. Brief CR (findings first).
3. If clean, commit.
4. Mention any residual risk or edge case.

## Validation
Run at least:
- syntax/compile check for Python file
- basic dry test of filename parsing + queue selection logic (can be via local quick checks)

If something is ambiguous, decide pragmatically and document decision in final response.
