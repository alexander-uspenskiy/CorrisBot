# PHASE 0 Technical Note: Runtime Model Override Capability Probe (2026-02-19)

## Scope
- Phase: 0 (Capability Probe)
- CID: `PHASE_0|TASK_PHASE0|CID_20260219_P0_W001`
- Edit root: `C:\CorrisBot`
- Probe mode: local CLI help/version only (no network calls)

## Source of Truth Used
1. `C:\CorrisBot\Looper\Plans\PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md`
2. `C:\CorrisBot\Looper\Plans\CR_PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md`
3. `C:\CorrisBot\Looper\Plans\CR2_PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md`

## Probe Commands (factual)
1. `codex -V`
- Result: `codex-cli 0.104.0`

2. `codex --help | rg -n -- "Usage:|--model|Model the agent should use"`
- Result lines:
  - `Usage: codex [OPTIONS] [PROMPT]`
  - `-m, --model <MODEL>`
  - `Model the agent should use`

3. `codex exec --help | rg -n -- "Usage:|--model|Model the agent should use"`
- Result lines:
  - `Usage: codex exec [OPTIONS] [PROMPT] [COMMAND]`
  - `-m, --model <MODEL>`
  - `Model the agent should use`

4. `kimi -V`
- Result: `kimi, version 1.12.0`

5. `kimi --help | rg -n -- "Usage:|--model|LLM model to use|--print|--prompt"`
- Result lines:
  - `Usage: kimi [OPTIONS] COMMAND [ARGS]...`
  - `--model -m TEXT`
  - `LLM model to use`
  - `--prompt,--command -p,-c TEXT`
  - `--print`

## Capability Matrix (frozen for Phase 1/2)
`supports_runtime_model_override`:
- `codex`: `true`
  - Confirmed runtime syntax: `codex -m <MODEL> ...` and `codex exec -m <MODEL> ...`
- `kimi`: `true`
  - Confirmed runtime syntax: `kimi --model <MODEL> ...` (alias `-m`)

Schema note (frozen):
- Capability flags are resolver metadata per plan section 4.4.
- Registry JSON in Phase 1 stores model defaults/lists; capability flags are not required as registry fields.

## Frozen Initial Registry Defaults (Phase 1 seed)
Frozen initial values to implement in registry/template for first migration cut:

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

Notes:
- Model IDs above are frozen from the migration plan's initial set (section 4.1 examples) as Phase 1 bootstrap defaults.
- Operational validation against real provider availability is deferred to later phases/tests.

## Explicit Input for Phase 1/2 (no ambiguity)
1. Phase 1 must create/update registry files with the frozen defaults above at:
- `ProjectFolder_Template/AgentRunner/model_registry.json`
- `Talker/AgentRunner/model_registry.json`
2. Phase 2 resolver/validator must treat both backends as `supports_runtime_model_override=true`.
3. CLI -> resolver mapping for model field is mandatory for both backends:
- Codex: `--model` / `-m`
- Kimi: `--model` / `-m`
4. If runtime/backend invocation path does not currently forward model, it is an implementation gap, not a capability gap, and must be closed in Phase 2/3 wiring.

## Constraints / Risks
1. Probe confirms CLI interface support, not provider-side model existence/auth/runtime success.
2. Current `Looper/agent_runners.py` does not yet pass `--model` to Codex/Kimi runner commands; runtime wiring work remains for next phases.
3. `reasoning_effort` remains Codex-only by contract.

## PHASE 0 Exit Gate
PASS for Phase 0 scope:
- Per-backend syntax is confirmed (no `unsupported yet` backends in this environment).
- Capability matrix is frozen.
- Initial registry defaults are frozen.
- Inputs for Phase 1/2 are explicit.
