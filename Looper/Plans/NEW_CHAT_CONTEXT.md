# New Chat Context (Current State)

## Project
Repository: `C:\CorrisBot\Looper`
Goal: reusable file-based looper for multi-agent platform (Orchestrator / Worker / Talker / etc.) using prompt files in inbox directories.

## Current Runtime Architecture
- Main loop script: `codex_prompt_fileloop.py`
- Single-agent launcher (legacy + still used inside WT panes): `CodexLoop.bat`
- WT production launcher (current):
  - `StartLoopsInWT.bat`
  - `StartLoopsInWT.py`
- WT layout config: `C:\CorrisBot\loops.wt.json`
- WT usage doc: `Plans/WT_LAUNCHER_USAGE.md`

## Key Design Already Implemented
1. Python looper replaces old PS1 looper.
2. Agent working directory is agent root (`-C` + `cwd`), so local `AGENTS.md` applies.
3. Multi-sender inbox model already works (`Prompts/Inbox/<Sender_ID>`).
4. Shared thread model for orchestrator flow is active (one brain, multiple sender queues).
5. Console coloring and `Console.log` tracing are in place.
6. Windows Terminal dynamic allocation is implemented:
- one launcher call = one agent
- anti-duplicate check
- fill panes up to max per tab
- then open next tab
- persistent allocation state in `Temp\wt_layout_state.json`

## Current Launch Contracts
- Run looper directly:
  - `CodexLoop.bat <project_root> <agent_path>`
- Run through WT allocator:
  - `StartLoopsInWT.bat <project_root> <agent_path> [--dry-run]`

Example:
```bat
StartLoopsInWT.bat C:\CorrisBot\ProjectFolder_Template Orchestrator
StartLoopsInWT.bat C:\CorrisBot\ProjectFolder_Template Workers\Worker_001
```

## Important Prompting Behavior Learned
- For launching another looper via agent command, direct `CodexLoop.bat` calls were replaced by `StartLoopsInWT.bat`.
- `StartLoopsInWT.bat` now returns exit code and does not `pause` on error (agent-safe).
- In prompt instructions, interactive nested shell patterns must be avoided.

## Current Queue Model In Code (to be changed next)
At this moment looper expects indexed files:
- `Prompt_0000.md`, `Prompt_0001.md`, ...
- Per-sender state stores `next_index`.

## Next Task (Planned Migration)
Migrate from index-based waiting to timestamp-based waiting.

Target filename pattern:
- `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`
- Optional deterministic suffix for tie-break (e.g. `_tNNN`) is acceptable.

Planned state model per sender:
- store only last processed timestamp marker
- choose next file as the oldest unprocessed by parsed timestamp
- global selection remains: oldest among sender-next candidates

Accepted assumptions from user:
1. Local machine only.
2. One writer per sender directory.
3. Prompt writers create temp file first and rename with final timestamp in the last moment.
4. No need for full processed registry; timestamp watermark per sender is sufficient.
5. Invalid prompt name with matching prefix should log warning once (orange/darkyellow-like severity), then skip.
6. `*_Result.md` must be excluded from candidate scan.

## Migration Notes To Keep In Mind
- Provide smooth fallback/migration for existing sender state files (`next_index` may still exist).
- Keep queue fairness across senders exactly as before.
- Do not break current WT launcher behavior.

## Relevant Files For Next Task
- `codex_prompt_fileloop.py` (main target)
- `Plans/WT_MIGRATION_PLAN.md` (historical design notes)
- `Plans/WT_LAUNCHER_USAGE.md` (already updated)
- `C:\CorrisBot\loops.wt.json`

## Recent Commits
- `c867193` Switch WT launcher to one-agent dynamic allocation and add WT orchestrator shortcut
- `e1b3f81` Improve WT pane titles by placing agent name first
- `f64aa40` Remove legacy PowerShell WT launcher and keep Python-only entrypoint
- `2ef60bf` Add Windows Terminal launchers and migration plan (with PS1 legacy variant)

## Current Working Tree Note
- `NEW_CHAT_CONTEXT.md` is intentionally untracked and used as handoff context file.
