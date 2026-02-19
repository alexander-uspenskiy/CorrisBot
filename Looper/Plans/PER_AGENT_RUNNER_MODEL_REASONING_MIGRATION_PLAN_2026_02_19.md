# Per-Agent Runner/Model/Reasoning Migration Plan (2026-02-19)

## 0. Goal
Migrate CorrisBot from global launch-time runner selection to deterministic per-agent configuration:
- per-agent `runner`
- per-agent `model`
- per-agent backend-specific tuning (`reasoning_effort` for Codex now)

Scope includes Talker, Orchestrator, and Workers.

This document is implementation-ready for Talker + Orchestrator + Workers, but not over-prescriptive at single-line coding level.

---

## 1. Locked Decisions (from current session)

1. Per-agent config is stored in the agent directory, not globally.
2. `runner` is stored in JSON (not txt).
3. Separate backend profile files are used:
   - `codex_profile.json`
   - `kimi_profile.json`
4. Unknown profile fields:
   - warning in log
   - ignored
   - launch continues if required known fields are valid.
5. Model list is not hardcoded in code; use runtime-root registry file.
6. Model registry is runtime-root local and templated.
7. Runtime global runner fallback from `loops.wt.json` is removed.
8. Old test projects do not require backward compatibility.
9. Runner switch is not hot-applied to already running process.
10. Non-critical settings (currently `reasoning_effort` for Codex) may be hot-applied without looper restart.
11. Talker must explicitly ask user for Orchestrator type/profile at project creation.
12. Profile mutation is allowed only from explicit user intent (no silent autonomous profile drift).
13. Every profile mutation is audited to runtime-root local change log.
14. Profile writes use mandatory file lock + atomic replace.
15. Inactive backend profile is preflight-validated before runner switch.
16. Gateway Talker boot path (`run_gateway.bat` via `CorrisBot.bat`) is part of migration scope.
17. Deterministic recovery from missing/corrupt profile does not require extra user confirmation when restore target is unambiguous.

---

## 2. Current State Check (Fact-Based)

Validated against current code:

1. Runner abstraction already exists:
   - `Looper/agent_runners.py` (`AgentRunner`, `CodexRunner`, `KimiRunner`).
2. `reasoning_effort` already exists for Codex call construction:
   - `Looper/agent_runners.py` (`model_reasoning_effort` injection).
3. Launcher already supports `--runner` and `--reasoning-effort`:
   - `Looper/StartLoopsInWT.bat`
   - `Looper/StartLoopsInWT.py`
4. Looper runtime already supports both runners and strict Kimi guard for reasoning flag:
   - `Looper/codex_prompt_fileloop.py`.
5. Session state is already split by runner key (`thread_id_codex` / `thread_id_kimi`).
6. Project and worker scaffolding already assembles per-agent `AGENTS.md`:
   - `Looper/CreateProjectStructure.bat`
   - `Looper/CreateWorkerStructure.bat`
   - `Looper/assemble_agents.py`
7. Current config remains globally runner-driven at runtime:
   - `loops.wt.json` contains top-level `"runner"`.

Conclusion: migration can reuse existing runner abstraction and launcher pipeline; main missing piece is deterministic per-agent config contract + resolver + operational flow around it.

---

## 3. Target Architecture Options (2-3) + Trade-Offs

## Option A: Per-Agent Split Files (Recommended)

Per agent directory:
- `agent_runner.json`
- `codex_profile.json`
- `kimi_profile.json`

Runtime-root level:
- `<RuntimeRoot>/AgentRunner/model_registry.json` (from template)
  - For project loopers: `<RuntimeRoot>` is project root.
  - For Talker: `<RuntimeRoot>` is `Talker` root.

Pros:
1. Clear ownership: agent settings live with the agent.
2. Backend schema separation avoids invalid mixed semantics (`kimi + reasoning_effort` confusion).
3. Easy for Talker/Orchestrator to patch only relevant file.
4. Strong operational clarity during incident investigation.

Cons:
1. More files per agent.
2. Needs strict helper tooling to avoid ad-hoc edits.

## Option B: Single Unified Agent Profile

Per agent:
- `agent_profile.json` with nested blocks `runner`, `codex`, `kimi`.

Pros:
1. One file to read/edit.
2. Smaller file count.

Cons:
1. Higher risk of mixed-field mistakes.
2. More validator complexity to explain precedence and active/inactive blocks.
3. Easier to grow into "one giant settings blob".

## Option C: Central Project Matrix

Project-level only:
- one map: `agent_path -> {runner, model, tuning}`.

Pros:
1. Centralized view of all agent settings.
2. Easier bulk updates.

Cons:
1. Weak locality (agent dir no longer source of truth).
2. Higher chance of path normalization misses and silent non-applied profiles.
3. Harder to keep deterministic when agents are added dynamically.

## Recommended
Option A (per-agent split files) is most robust against hacks and silent misconfigurations in this codebase.

---

## 4. Recommended End-State Contract

## 4.0 Runtime Root Discovery Contract

To remove ambiguity, resolver must use one deterministic algorithm:

1. Input: absolute `AgentDirectory`.
2. Walk up parent directories from `AgentDirectory` until repository boundary.
3. First directory containing `AgentRunner/model_registry.json` is selected as `<RuntimeRoot>`.
4. If not found: hard error (`runtime_root_not_found`).
5. All launcher/runtime/profile tools must call this same helper; no duplicated path logic.

## 4.1 File Layout

For every agent directory (`Talker`, `Orchestrator`, `Workers/*`):

1. `agent_runner.json`
```json
{
  "version": 1,
  "runner": "codex"
}
```

2. `codex_profile.json`
```json
{
  "version": 1,
  "model": "codex-5.3",
  "reasoning_effort": "high"
}
```

3. `kimi_profile.json`
```json
{
  "version": 1,
  "model": "kimi-k2"
}
```

Runtime-root level:

4. `<RuntimeRoot>/AgentRunner/model_registry.json`
```json
{
  "version": 1,
  "codex": {
    "default_model": "codex-5.3",
    "models": ["codex-5.3", "codex-5.3-mini"],
    "reasoning_effort": ["low", "medium", "high"]
  },
  "kimi": {
    "default_model": "kimi-k2",
    "models": ["kimi-k2"]
  }
}
```

Note: values above are examples; actual list must be curated in template and updated by process.
`default_model` is mandatory for each backend and must be present in its `models` list.

## 4.2 Explicit Precedence (required)

Precedence is field-specific and deterministic.

1. `runner`
   1. CLI `--runner` (if passed)
   2. `agent_runner.json.runner`
   3. global config: not used (removed)
   4. backend default: not allowed
   - If unresolved: hard error.

2. `model`
   1. CLI `--model`
   2. active backend profile (`codex_profile.json` or `kimi_profile.json`)
   3. global config: not used
   4. backend default: policy-disabled for deterministic runs
   - If unresolved/invalid vs registry: hard error.
   - If backend has `supports_runtime_model_override=false`:
     - `CLI --model` is accepted only when equal to backend-default model from registry.
     - otherwise hard error.

3. `reasoning_effort` (Codex only)
   1. CLI `--reasoning-effort`
   2. `codex_profile.json.reasoning_effort`
   3. global config: not used
   4. backend default: allowed (if field omitted)
   - If provided, value must be in registry allowlist for Codex reasoning levels; otherwise hard error.
   - If provided with non-Codex active runner: hard error.

4. Unknown fields in profile files
   - warning + ignore.

## 4.3 Profile Mutation Policy (deterministic)

1. Profile changes are allowed only when explicitly requested by user (directly or via upstream handoff contract).
2. Talker can mutate:
   - Talker profile
   - target Orchestrator profile for project setup/reconfiguration.
3. Orchestrator can mutate:
   - Worker profiles in owned project scope.
4. Any mutation outside allowed ownership is blocked with hard error.
5. Each successful mutation appends one audit record:
   - timestamp
   - actor (`Talker`/`Orchestrator` + sender id)
   - target file
   - changed keys (old -> new)
   - request reference marker.
6. Exception for deterministic self-healing:
   - if profile is missing/corrupt and restorable target is unambiguous (last known good state or template default),
     restore is allowed without extra user confirmation.
   - such restore must produce incident log + audit record with `reason=self_heal`.

## 4.4 Backend Capability Policy (model override support)

1. Each runner has explicit capability flag in resolver metadata:
   - `supports_runtime_model_override: true|false`.
2. If capability is `true`:
   - resolved model is mandatory and must be applied at runtime.
3. If capability is `false`:
   - resolver still validates profile model against registry.
   - runtime cannot switch model per launch; only backend default is usable.
   - profile model must equal declared backend-default model id from registry; otherwise hard error.
4. Capability and effective behavior must be shown in dry-run diagnostics.

## 4.5 Audit Log Contract

1. Per runtime-root audit path:
   - `<RuntimeRoot>/AgentRunner/profile_change_audit.jsonl`
2. One JSON line per mutation/recovery event.
3. Mandatory fields:
   - `timestamp`
   - `actor`
   - `action` (`set_runner|set_model|set_reasoning|self_heal_restore|other`)
   - `target_file`
   - `changes`
   - `request_ref`
   - `result` (`ok|error`)
4. On validation failure/blocked mutation, write rejected event with `result=error`.

## 4.6 Runtime Apply Rules

1. Runner changes: apply only on next process launch.
2. Model changes: apply on next process launch (same as runner for now).
3. Codex `reasoning_effort`: may be reloaded per prompt cycle without restart.
4. If process was started with CLI `--reasoning-effort`, CLI value is pinned for the process lifetime:
   - profile hot-reload for `reasoning_effort` is ignored
   - warning is written to runtime log.

## 4.7 Last-Known-Good Snapshot Contract

1. Per-agent snapshot path:
   - `<AgentDirectory>/AgentRunner/last_known_good/`
2. Snapshot set contains copies of:
   - `agent_runner.json`
   - `codex_profile.json`
   - `kimi_profile.json`
3. Snapshot is updated only after successful validation and successful atomic write.
4. Snapshot update does not wait for launch-bound runtime apply (`runner`/`model`).
   - launch-bound apply status is tracked separately in runtime logs.
5. Self-heal restore order:
   1. `last_known_good` snapshot
   2. template defaults
6. Self-heal log/audit must include restore source:
   - `restore_source=last_known_good|template_default`.

## 4.8 Resolver -> Batch Bridge Contract

To avoid brittle JSON parsing in `.bat`, add a lightweight resolver bridge CLI:

1. Script contract:
   - `resolve_agent_config.py --agent-dir <path> --format bat_env`
2. Output contract:
   - prints one `KEY=VALUE` per line for required launch fields only.
   - minimum keys: `RUNNER`, `MODEL`, `REASONING_EFFORT`, `SOURCE_RUNNER`, `SOURCE_MODEL`, `SOURCE_REASONING`.
3. Failure contract:
   - non-zero exit code
   - single-line machine-readable error code on stderr.
4. `StartLoopsInWT.bat` and `run_gateway.bat` consume only this bridge output; no direct JSON parsing in batch files.

---

## 5. Validation & Error Policy

## 5.1 Fail-Fast Errors

Hard error (no launch) if:
1. `agent_runner.json` missing or invalid JSON.
2. `runner` not in allowed set.
3. Active backend profile missing.
4. Required known field (`model`) missing in active backend profile.
5. `model` not in runtime-root registry for active backend.
6. CLI/profile field is incompatible with active runner (for known fields).
7. `reasoning_effort` is provided with invalid type/value for Codex allowlist.
8. Registry backend block is invalid (`default_model` missing or not present in backend `models`).

## 5.2 Soft Errors

Warning + continue:
1. Unknown fields in any profile file.
2. Inactive backend profile unknown fields (warn with file path).

Strict preflight before runner switch:
1. JSON parse/schema/model validation for target backend profile must pass.
2. If preflight fails, runner switch is rejected (hard error), current runner remains unchanged.

## 5.3 Recovery Responsibility

1. Talker profile missing/broken:
   - loud startup error and user-visible escalation.
   - deterministic restore when restore target is unambiguous.
2. Orchestrator profile missing/broken:
   - Talker escalates to user and performs deterministic restore when unambiguous.
3. Worker profile missing/broken:
   - Orchestrator escalates, restores profile deterministically, and marks worker as `needs_relaunch`.
   - Process relaunch is done by launch controller path (WT launcher/watchdog/manual operator), not by implicit in-process hot restart.
4. Deterministic restore does not require separate user confirmation.
5. Every restore writes:
   - runtime error log entry
   - audit record (`action=self_heal_restore`)
   - restore source marker (`last_known_good|template_default`).

---

## 6. Migration Plan (Phased)

## Phase 0: Capability Probe (short, mandatory)

Goal: remove ambiguity around CLI support for model override syntax per runner.

Tasks:
1. Verify Codex CLI runtime model override method in target environment.
2. Verify Kimi CLI runtime model override method in target environment.
3. Record supported flags/syntax in a short technical note in `Looper/Plans`.
4. Freeze first registry values set.

Exit gate:
1. Team has one agreed syntax per backend (or explicit "unsupported yet").
2. Capability matrix is frozen (`supports_runtime_model_override` per backend).
3. For backends without model override, registry default-model policy is frozen.

## Phase 1: Config Contract + Registry + Templates

Tasks:
1. Add template files:
   - `ProjectFolder_Template/AgentRunner/model_registry.json`
   - default `agent_runner.json`, `codex_profile.json`, `kimi_profile.json` for Orchestrator and Worker template.
2. Add Talker profile files in `Talker/`.
3. Add Talker local registry file:
   - `Talker/AgentRunner/model_registry.json`
   - same schema as runtime-root registry contract.
4. Update scaffold scripts:
   - `CreateProjectStructure.bat` to create/copy project registry and Orchestrator profile files.
   - `CreateWorkerStructure.bat` to copy worker profile files.
5. Keep file writes atomic.

Exit gate:
1. New project + new worker always contain required profile files.

## Phase 2: Central Resolver/Validator Module

Tasks:
1. Introduce one shared module (single source of truth) for:
   - agent path normalization
   - runtime-root discovery (section 4.0 contract)
   - profile loading
   - registry loading
   - validation
   - effective config resolution with source labels.
2. Add API result shape:
   - effective `runner/model/reasoning`
   - `source` map for each field (`cli/profile/backend-default`).
3. Add deterministic error codes/messages.
4. Add lightweight bridge CLI for batch launchers:
   - `resolve_agent_config.py --agent-dir <path> --format bat_env`
   - stable key/value output for `.bat` consumers.

Exit gate:
1. No duplicated config resolution logic in launcher/runtime.
2. Batch launchers consume resolver bridge output without JSON parsing.

## Phase 3: Launcher Integration (`StartLoopsInWT`)

Tasks:
1. Replace global `"runner"` read from `loops.wt.json` with per-agent resolver call.
2. Keep CLI overrides on top.
3. Remove runtime dependency on `loops.wt.json.runner`.
4. Keep `loops.wt.json` only for WT layout concerns.
5. Add `--model` end-to-end in launcher entry points:
   - `StartLoopsInWT.bat`
   - `StartLoopsInWT.py`
   - `start_loops_sequential.py`
6. Migrate Gateway Talker boot path to the same resolver contract:
   - `Gateways/Telegram/run_gateway.bat` must resolve Talker runner/profile from Talker runtime root, not from `loops.wt.json.runner`.
   - integration must use resolver bridge CLI (`--format bat_env`) only.
7. Extend dry-run output with effective resolved config + source.

Exit gate:
1. Launch path uses per-agent runner deterministically for Talker/Orchestrator/Workers.

## Phase 4: Looper Runtime Integration (`codex_prompt_fileloop.py` + runners)

Tasks:
1. Wire resolved/CLI-overridden `model` into active runner launch command.
2. Implement per-prompt reload of Codex `reasoning_effort` from profile file.
3. If runtime detects `agent_runner.json` changed to different runner:
   - log warning "runner change applies next launch", do not hot-switch.
4. Keep existing per-runner session key behavior.
5. Add `--model` argument support in `codex_prompt_fileloop.py` and pass into runner constructors.

Exit gate:
1. `reasoning_effort` change in profile is reflected without restart (Codex).
2. Runner/model remain launch-bound and deterministic.

## Phase 5: Profile Update Operations (Talker/Orchestrator flow)

Tasks:
1. Add deterministic helper script for profile operations (recommended):
   - validate profile
   - set runner
   - set backend model/reasoning
   - enforce ownership/authorization rules
   - writes with mandatory lock + atomic replace
   - append audit log record.
2. Update Talker instructions:
   - project creation must ask Orchestrator profile explicitly (mandatory).
   - allow user to specify worker profile policy.
3. Update Orchestrator instructions:
   - allowed to set/update worker profiles.
4. Update `SKILL_AGENT_RUNNER.md` with operational commands for profile setup/update.

Exit gate:
1. No ad-hoc manual profile mutation in runtime-critical paths.

## Phase 6: Tests (table-driven + integration)

Required tests:

1. Unit (resolver/validator):
   - valid/invalid JSON
   - missing files
   - unknown fields warning behavior
   - model not in registry
   - precedence correctness.
   - invalid `reasoning_effort` type/value -> hard error.
   - invalid registry backend block (`default_model` missing or not in `models`) -> hard error.
   - backend capability branch:
     - `supports_runtime_model_override=false` + CLI `--model` mismatch -> hard error
     - `supports_runtime_model_override=false` + CLI `--model` equals registry default -> allowed.

2. Integration (launcher):
   - per-agent runner selection from profile
   - CLI override precedence
   - no global `loops.wt.json.runner` fallback.
   - gateway boot resolves Talker runner/profile without `loops.wt.json.runner`.

3. Runtime:
   - codex reasoning hot-reload
   - CLI `--reasoning-effort` pins value; profile hot-reload ignored with warning
   - runner change not hot-applied (warning only)
   - deterministic self-heal restore writes audit record (`action=self_heal_restore`)
   - deterministic self-heal restore uses `last_known_good` first, template fallback second
   - lock contention during profile write is handled deterministically (no partial writes).
   - concurrent read/write race (looper reading while orchestrator writes) has no partial/invalid read result.
   - snapshot isolation: profile update for one worker does not alter another worker snapshot.

4. Path resolution:
   - runtime-root discovery from different agent depths (Talker, Orchestrator, nested Worker) resolves correct registry root.
   - missing `AgentRunner/model_registry.json` on parent chain returns deterministic hard error.

5. Bootstrap:
   - new project contains orchestrator profile + registry
   - new worker contains worker profile files.
   - Talker runtime root contains local registry/profile files.

Exit gate:
1. Green tests + manual smoke for Talker startup, Orchestrator launch, Worker launch.

## Phase 7: Cutover + Cleanup

Tasks:
1. Remove `runner` and `_runner_help` from `loops.wt.json`.
2. Update docs/help text in launcher scripts and AGENTS instructions.
3. Add one migration note for operators:
   - where profiles live
   - how to inspect effective config
   - common error messages.
4. Remove legacy runner read logic from `Gateways/Telegram/run_gateway.bat`.

Exit gate:
1. Runtime no longer reads global runner from `loops.wt.json`.

---

## 7. Pre-Mortem ("Implemented and it went badly")

Assume bad outcome: "System launches, but behavior is inconsistent and hard to debug."

Likely failure points:

1. Resolver logic duplicated between launcher and runtime.
   - symptom: launch runner differs from runtime expectations.
2. Unknown field warnings too weak.
   - symptom: typos silently degrade intended config.
3. Runner/profile edits race between Talker/Orchestrator updates.
   - symptom: partial writes, invalid JSON at launch.
4. Model registry drifts from actual available CLI models.
   - symptom: frequent false validation failures.
5. Hot-reload behavior not explicit to operators.
   - symptom: users expect runner/model to switch instantly.
6. Path mismatch when agents are dynamically created.
   - symptom: profile not found or wrong profile read.
7. Gateway still reads removed global runner key.
   - symptom: Talker startup boot fails after cutover.

Mitigations injected into plan:

1. One resolver module only (Phase 2) used by both launcher/runtime.
2. Warning format standard:
   - include file path + field + ignored value.
3. Atomic write + mandatory file lock in helper script.
4. Registry maintenance process:
   - update by explicit task, versioned file, documented ownership.
   - registry file lives in each runtime root (`<RuntimeRoot>/AgentRunner/model_registry.json`).
5. Explicit runtime log line on profile change:
   - "runner/model apply next launch; reasoning applies next prompt (Codex)".
6. Shared path-normalization helper reused by:
   - launcher
   - profile tools
   - any Talker/Orchestrator profile management scripts.
7. Gateway boot path uses same resolver as launcher/runtime (single config truth).

---

## 8. Final Critically Reviewed Plan (for execution)

## 8.1 Workstreams

1. Core config runtime:
   - resolver/validator module
   - runtime apply rules
2. Launch/bootstrap:
   - `StartLoopsInWT*` integration
   - template/scaffold updates
3. Agent operations:
   - profile management helper
   - Talker/Orchestrator/SKILL docs update
4. Quality gates:
   - unit/integration tests
   - smoke script checklist.

## 8.2 Order of Execution

1. Phase 0 -> Phase 1 -> Phase 2 first (architecture lock).
2. Then run parallel:
   - Phase 3 (launcher)
   - Phase 5 docs/helper operations
3. Then Phase 4 runtime wiring.
4. Then Phase 6 tests.
5. Final Phase 7 cutover and cleanup.

## 8.3 Non-Negotiable Acceptance Criteria

1. Every launched agent resolves runner from its own profile files.
2. No runtime dependency on `loops.wt.json.runner`.
3. Effective config and source are visible in logs/dry-run.
4. CLI `--model` override is wired end-to-end (launcher -> runtime -> runner).
5. Codex `reasoning_effort` can be changed without restart.
6. Runner change never hot-switches active process.
7. Missing/invalid active profile stops launch with clear error.
8. Unknown profile fields generate warnings and are ignored.
9. Talker creation flow requires explicit Orchestrator profile selection.
10. Profile mutation without explicit user intent is rejected, except deterministic `self_heal_restore`.
11. Profile mutation is lock-protected and audit-logged.
12. Talker runtime root contains valid local registry (`Talker/AgentRunner/model_registry.json`).
13. Gateway Talker boot remains functional after `loops.wt.json.runner` removal.
14. Invalid `reasoning_effort` never reaches runtime execution (blocked by validator).
15. Self-heal restore uses deterministic source order (`last_known_good` -> `template_default`).

---

## 9. Deliverables Checklist

1. New/updated profile and registry template files.
2. Shared resolver/validator module.
3. Launcher integration changes (`StartLoopsInWT.py/.bat`, `start_loops_sequential.py`, `Gateways/Telegram/run_gateway.bat`, and related help text).
4. Runtime integration changes (`codex_prompt_fileloop.py`, `agent_runners.py` as needed).
5. Profile helper script(s) for deterministic mutation.
6. Last-known-good snapshot mechanism with per-agent location:
   - `<AgentDirectory>/AgentRunner/last_known_good/`.
7. Updated instructions:
   - `Talker/ROLE_TALKER.md`
   - `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
   - `Looper/SKILL_AGENT_RUNNER.md`
8. Full tests for resolver/launcher/runtime/bootstrap.
9. Final cutover commit removing global runner from `loops.wt.json`.

---

## 10. Notes for Orchestrator Execution

1. Keep changes behind clear phase commits.
2. Do not mix config contract design and runtime behavior in one large commit.
3. If CLI model override capability is unclear, block Phase 4 until Phase 0 probe is signed off.
4. Prefer deterministic tooling for profile writes; avoid ad-hoc JSON editing in prompts.
