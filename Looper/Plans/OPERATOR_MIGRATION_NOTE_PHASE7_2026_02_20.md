# Operator Migration Note (Phase 7 Cutover, 2026-02-20)

## 1) Final Architecture Snapshot

Global runner selection via `loops.wt.json.runner` is removed.

Source-of-truth is per-agent profile set + runtime-root registry:
- Per-agent files:
  - `agent_runner.json`
  - `codex_profile.json`
  - `kimi_profile.json`
- Runtime-root registry:
  - `<RuntimeRoot>/AgentRunner/model_registry.json`

`loops.wt.json` now keeps WT layout/window concerns only.

## 2) Where Config Lives

Project runtime root:
- `C:\<ProjectRoot>\AgentRunner\model_registry.json`

Project agents:
- Orchestrator:
  - `C:\<ProjectRoot>\Orchestrator\agent_runner.json`
  - `C:\<ProjectRoot>\Orchestrator\codex_profile.json`
  - `C:\<ProjectRoot>\Orchestrator\kimi_profile.json`
- Worker:
  - `C:\<ProjectRoot>\Workers\<WorkerId>\agent_runner.json`
  - `C:\<ProjectRoot>\Workers\<WorkerId>\codex_profile.json`
  - `C:\<ProjectRoot>\Workers\<WorkerId>\kimi_profile.json`

Talker runtime root:
- `C:\CorrisBot\Talker\AgentRunner\model_registry.json`
- `C:\CorrisBot\Talker\agent_runner.json`
- `C:\CorrisBot\Talker\codex_profile.json`
- `C:\CorrisBot\Talker\kimi_profile.json`

## 3) How To Check Effective Config

Bridge CLI (batch-safe):
- `py C:\CorrisBot\Looper\resolve_agent_config.py --agent-dir <AgentDir> --format bat_env`

Expected keys:
- `RUNNER`
- `MODEL`
- `REASONING_EFFORT`
- `SOURCE_RUNNER`
- `SOURCE_MODEL`
- `SOURCE_REASONING`

Launcher dry-run checks:
- `C:\CorrisBot\Looper\StartLoopsInWT.bat <ProjectRoot> Orchestrator --dry-run`
- `C:\CorrisBot\Looper\StartLoopsInWT.bat <ProjectRoot> Workers\Worker_001 --dry-run`

Gateway dry-run check:
- `cmd /c "set REPO_ROOT=C:\CorrisBot&& set LOOPER_ROOT=C:\CorrisBot\Looper&& set TALKER_ROOT=C:\CorrisBot\Talker&& set TEMPLATE_ROOT=C:\CorrisBot\ProjectFolder_Template&& set WORKDIR=C:\CorrisBot\Gateways\Telegram&& call C:\CorrisBot\Gateways\Telegram\run_gateway.bat --dry-run"`

## 4) Common Machine Error Codes

Resolver / bridge:
- `runtime_root_not_found`
- `agent_runner_missing`
- `active_profile_missing`
- `active_profile_invalid_json`
- `model_not_in_registry`
- `reasoning_invalid`
- `reasoning_incompatible_with_runner`
- `registry_backend_invalid`
- `unsupported_format`

Profile operations (`profile_ops.py`):
- `explicit_intent_required`
- `ownership_violation`
- `lock_timeout`
- `write_conflict`
- `template_default_not_available`

## 5) Recovery Hints

1. `runtime_root_not_found`
- Ensure `<RuntimeRoot>/AgentRunner/model_registry.json` exists.
- Ensure `--agent-dir` points inside expected runtime tree.

2. `model_not_in_registry` / `reasoning_invalid`
- Check `model_registry.json` allowlists first.
- Then update profile via deterministic helper:
  - `py C:\CorrisBot\Looper\profile_ops.py set-backend ... --intent explicit --request-ref <Ref>`

3. `ownership_violation`
- Talker may mutate Talker/Orchestrator profile scopes.
- Orchestrator may mutate Worker profile scopes.
- Re-run with correct actor scope.

4. `active_profile_invalid_json` / missing profile files
- Use deterministic self-heal:
  - `py C:\CorrisBot\Looper\profile_ops.py self-heal --agent-dir <AgentDir> --actor-role <talker|orchestrator> --actor-id <ActorId> --request-ref <Ref> --intent explicit`
- Restore order:
  - `last_known_good` snapshot first
  - template default second

5. `lock_timeout` / `write_conflict`
- Indicates concurrent mutation contention.
- Retry operation; do not perform manual partial edits.

## 6) Audit Location

Profile mutation audit log:
- `<RuntimeRoot>/AgentRunner/profile_change_audit.jsonl`

Snapshot location:
- `<AgentDir>/AgentRunner/last_known_good/`

`result=ok` and `result=error` entries are both expected by contract.
