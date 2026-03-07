# SKILL AGENT-RUNNER

> **For orchestrators:** Creating a Worker is the MANDATORY first step after receiving a task.
> The Orchestrator is not allowed to implement code directly. All implementation tasks are delegated through this skill.
> If the task allows multiple subtasks to run in parallel, create multiple executors.
> For sequential startup of multiple loopers, use `start_loops_sequential.py` (not an ad-hoc set of separate commands).

Path note:
- All paths in this skill's examples are demonstrational.
- Do not use an example path as the operational default unless it is explicitly assigned in the current task contract/user request.
- For external working directories, follow the `Path Allocation Policy` from `ROLE_LOOPER_BASE`.

# Creating the looper agent file structure

The script creates the agent folder **inside the current working directory**.

- Choose a name for the agent (for example, `Worker_001` or `Project_Orchestrator`).
- First, create the file structure for the looper:
1. Go to the folder where you want to create the agent directory (`cd` or `Set-Location`).
2. Run the creation script from `%LOOPER_ROOT%`.

Examples:
- PowerShell (create in the current folder):
  `Set-Location "<ParentDirPath>"; & "$env:LOOPER_ROOT\CreateWorkerStructure.bat" "<AgentFolderName>" "<ExpectedSenderID>"`
- cmd:
  `cd /d "<ParentDirPath>" && "%LOOPER_ROOT%\CreateWorkerStructure.bat" "<AgentFolderName>" "<ExpectedSenderID>"`

Parameters:
- `AgentFolderName`: name of the folder to create (plain name, not a path).
- `ExpectedSenderID`: logical sender ID from which this agent will receive tasks (for example, `Talker`, `Orc_Project1`).
Important: the second parameter is the logical sender name (SenderID), not the folder name. The orchestrator may be located in the `Orchestrator` directory while using SenderID `Orc1`.

# Launching an agent looper
- After the file structure is created, launch the looper itself (terminal script + AI agent).
- Launch it through `StartLoopsInWT.bat` via `LOOPER_ROOT`:
  - PowerShell: `& "$env:LOOPER_ROOT\StartLoopsInWT.bat" "<ProjectRootPath>" "<RelativePathToAgent>"`
  - cmd: `"%LOOPER_ROOT%\StartLoopsInWT.bat" "<ProjectRootPath>" "<RelativePathToAgent>"`
The first parameter is the path to the project; the second is the relative path to the agent inside the project.
There may be many projects in one application (the example is fictional; do not search for it).
For example, `c:\Minesweeper\.MigrationToIOs` is a project for iOS migration.
Or `c:\Minesweeper\.UIRefactoring` may be a refactoring project.
- If multiple loopers must be started, use the deterministic helper:
  - PowerShell: `py "$env:LOOPER_ROOT\start_loops_sequential.py" --project-root "<ProjectRootPath>" "<RelPath1>" "<RelPath2>"`
  - cmd: `py "%LOOPER_ROOT%\start_loops_sequential.py" --project-root "<ProjectRootPath>" "<RelPath1>" "<RelPath2>"`
- For smoke/safe verification, `--dry-run` is allowed:
  - `py "$env:LOOPER_ROOT\start_loops_sequential.py" --project-root "<ProjectRootPath>" --dry-run "<RelPath1>" "<RelPath2>"`
- `start_loops_sequential.py` guarantees sequential startup and stop-on-first-error.
- Parallelization happens at the task/executor level after startup, not at the level of simultaneous WT panel startup.

# Choosing the CLI agent (runner)

Looper supports two CLI agents for task execution:
- **Codex** (OpenAI) - the default agent, used by default
- **Kimi** (Kimi Code CLI) - an alternative agent

## Profiles and profile operations (Phase 5)

Source of truth for runner/model/reasoning:
- `agent_runner.json`
- `codex_profile.json`
- `kimi_profile.json`
- runtime-root registry: `<RuntimeRoot>/AgentRunner/model_registry.json`
  (NOT inside ORCHESTRATOR!! but RuntimeRoot folder!!)

Use the deterministic helper for profile setup/update:
- `Looper/profile_ops.py`

### Validate profiles
- PowerShell:
  - `py "$env:LOOPER_ROOT\profile_ops.py" validate --agent-dir "<AgentDir>"`
- cmd:
  - `py "%LOOPER_ROOT%\profile_ops.py" validate --agent-dir "<AgentDir>"`

### Change runner
- Orchestrator -> Worker:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-runner --agent-dir "<ProjectRoot>\Workers\Worker_001" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --runner codex`
- Talker -> Orchestrator/Talker:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-runner --agent-dir "<ProjectRoot>\Orchestrator" --actor-role talker --actor-id "<TalkerSenderID>" --request-ref "<RequestRef>" --intent explicit --runner kimi`

### Change backend model/reasoning
- Set model:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-backend --agent-dir "<AgentDir>" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --backend codex --model codex-5.3-mini`
- Set Codex reasoning (reasoning may differ: low, medium, high, etc.):
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-backend --agent-dir "<AgentDir>" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --backend codex --reasoning-effort high`

Rules:
- mutation is allowed only with explicit intent (`--intent explicit` + `--request-ref`).
- the helper performs ownership check, lock + atomic replace, and writes audit records to `<RuntimeRoot>/AgentRunner/profile_change_audit.jsonl`.
- mutation errors are also written to audit with `result=error`.

## Launch overrides (temporary)

- Launch path uses per-agent resolver/profile as baseline.
- CLI overrides (`--runner`, `--model`, `--reasoning-effort`) are allowed as launch/runtime overrides under the phase 3-4 contract.
- `loops.wt.json` is used only for WT layout/window settings, not as the runtime source of truth for runner.
- Legacy fields `runner` / `_runner_help` in `loops.wt.json` were removed in the final cutover (Phase 7).

## Kimi Runner specifics

- Session ID is determined through the filesystem (`~/.kimi/sessions/`)
- There is no analogue of `turn.completed` - the process ends on EOF
- The prompt is passed through the `-c` argument (not through stdin)
- Long prompts (>8000 characters) are automatically written to a temporary file

### Stopping an agent looper (graceful)

When an agent looper is no longer needed, stop it via inbox prompt command:

1. Create local file with first line `/looper stop` (for example: `Temp\looper_stop.md`).
2. Publish it to target sender inbox using helper script:
   - PowerShell: `py "$env:LOOPER_ROOT\create_prompt_file.py" create --inbox "Prompts\Inbox\<SenderID>" --from-file "Temp\looper_stop.md"`
   - cmd: `py "%LOOPER_ROOT%\create_prompt_file.py" create --inbox "Prompts\Inbox\<SenderID>" --from-file "Temp\looper_stop.md"`
3. Ensure the first non-empty line is exactly:
   `/looper stop`
4. Do not add any other command on that first line.

Behavior:
- The looper stops at script level (no LLM call for this prompt).
- The prompt is marked as processed, and the process exits cleanly.
- Later, restart with the same launcher (WT launcher) to continue normal work.
