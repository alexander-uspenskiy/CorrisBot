# Per-Agent Model/Reasoning - Context For New Chat (2026-02-19)

## 1) Purpose
- Подготовить чистый контекст для нового чата.
- Продолжить проект: от текущего global/launch-time runner к пер-агентной параметризации `runner + model + reasoning`.
- Сразу заложить защиту от костылей (pre-mortem и архитектурные критерии качества).

## 2) Current State Snapshot (fact-based)

### 2.1 Runtime abstraction is already split by runner
- `AgentRunner` abstraction implemented: `Looper/agent_runners.py`.
- Two concrete backends:
  - `CodexRunner`: `Looper/agent_runners.py:104`
  - `KimiRunner`: `Looper/agent_runners.py:280`
- Output formats are normalized into common event model via `parse_output_line(...)` in each runner:
  - Codex parser: `Looper/agent_runners.py:182`
  - Kimi parser: `Looper/agent_runners.py:338`

### 2.2 Reasoning override for Codex is already present (per-call)
- `CodexRunner` has optional `reasoning_effort`: `Looper/agent_runners.py:116`
- It is injected into Codex CLI as config override:
  - `Looper/agent_runners.py:174`
  - `Looper/agent_runners.py:175`
- Looper CLI accepts `--reasoning-effort`:
  - `Looper/codex_prompt_fileloop.py:1117`
- Kimi guard exists (hard validation error):
  - `Looper/codex_prompt_fileloop.py:1128`
- Reasoning parameter is wired into runner creation:
  - `Looper/codex_prompt_fileloop.py:1157`

### 2.3 Launcher pipeline already supports per-launch runner selection
- `StartLoopsInWT.bat` supports:
  - `--runner codex|kimi`
  - `--reasoning-effort low|medium|high`
  - See: `Looper/StartLoopsInWT.bat:29`, `Looper/StartLoopsInWT.bat:47`
- `StartLoopsInWT.py` supports the same args and validation:
  - `Looper/StartLoopsInWT.py:460`
  - `Looper/StartLoopsInWT.py:463`
  - `Looper/StartLoopsInWT.py:496`
- CLI command generation forwards reasoning into loop invocation:
  - `Looper/StartLoopsInWT.py:227`
  - `Looper/StartLoopsInWT.py:235`
  - `Looper/StartLoopsInWT.py:553`

### 2.4 Session state already handles multi-runner separation
- Per-runner state key format: `thread_id_<runner>`:
  - `Looper/codex_prompt_fileloop.py:146`
  - `Looper/codex_prompt_fileloop.py:175`
  - `Looper/codex_prompt_fileloop.py:203`
- Explicit mention of `thread_id_codex/thread_id_kimi` present in comments:
  - `Looper/codex_prompt_fileloop.py:145`

### 2.5 Config is still mostly global
- Top-level `loops.wt.json` has only global runner:
  - `loops.wt.json:7`
- No per-agent model/reasoning map yet.

## 3) Problem To Solve Next
- Нужна персональная параметризация каждого агента:
  - `runner` per agent
  - `model` per agent (at least for Codex; maybe Kimi if supported)
  - `reasoning` per agent (Codex)
- Сейчас это можно задавать на запуск, но нет устойчивой проектной конфигурации "агент -> профиль".

## 4) Desired End-State (target architecture)

### 4.1 Conceptual target
- Единый source-of-truth профилей агентов.
- Прозрачный fallback chain:
  1. explicit CLI flags
  2. per-agent profile
  3. global defaults
  4. backend native defaults
- Строгая валидация совместимости параметров:
  - `reasoning` only for Codex
  - `model` only where backend supports runtime override

### 4.2 Recommended config model (pragmatic)
- Extend `loops.wt.json` with an `agents` map keyed by normalized `agent_path`.
- Example concept:
  - `agents.Orchestrator.runner = codex`
  - `agents.Orchestrator.codex.model = ...`
  - `agents.Orchestrator.codex.reasoning_effort = high`
  - `agents.Workers\\Worker_X.runner = kimi`
- Keep current top-level `runner` as global fallback for backward compatibility.

## 5) Migration Complexity Assessment

### 5.1 What is easy
- Output format differences are already encapsulated in runner classes.
- Session isolation by runner already exists.
- Launch path already propagates runner and (now) reasoning.

### 5.2 What is medium complexity
- Config design and validation matrix (avoid ambiguous precedence).
- Keeping `.bat` and `.py` argument behavior consistent.
- Error ergonomics when profile asks unsupported params for selected backend.

### 5.3 What is risky
- Stringly-typed `agent_path` keys causing profile misses due to path normalization mismatch.
- Silent fallback to global defaults hiding misconfiguration.
- Spreading backend-specific option logic across too many files.

## 6) Anti-Hack Pre-Mortem (\"imagine it's done and ugly\")

Potential bad outcomes to prevent:
1. "Works, but no one can explain precedence in 2 minutes."
2. "Half options apply from profile, half only from CLI, silently."
3. "Per-agent config exists, but launcher normalizes paths differently, so profiles randomly miss."
4. "Kimi receives Codex-only options and silently ignores them."
5. "Support burden: every new backend option requires edits in 5 places."

Quality gates to avoid this:
1. Single explicit precedence table in docs and code comments.
2. One normalization function for agent path used everywhere.
3. Fail-fast for unsupported backend params (no silent ignore).
4. Centralize backend option mapping in runner layer.
5. Add table-driven tests for profile resolution.

## 7) Suggested Implementation Stages (high-level)

Stage A: Config contract only
- Define schema for per-agent profiles.
- Implement strict validation and deterministic precedence.
- Keep behavior unchanged when `agents` section absent.

Stage B: Runner/profile wiring
- Resolve effective runtime config for selected agent.
- Pass resolved options into `CodexRunner`/`KimiRunner` factories.
- Preserve current CLI overrides as highest priority.

Stage C: Model support expansion
- Codex: add per-agent model override (if runtime config is supported in current CLI version).
- Kimi: add model override only if runtime-compatible; otherwise explicit unsupported state.

Stage D: Hardening
- Negative tests for incompatible options.
- Dry-run diagnostics showing effective profile and source (CLI/profile/global).
- Migration notes and rollback strategy.

## 8) Open Questions For Next Chat
1. Where to store per-agent profiles: only `loops.wt.json` or optional local files per agent?
2. Should unsupported fields be hard errors or warnings with refusal to launch?
3. Do we need "locked profiles" (for production-like deterministic runs)?
4. How much backend-agnostic schema vs backend-specific nested blocks?

## 9) Start Prompt For New Chat
Use this prompt to continue in a fresh context:

```md
Контекст: открой и используй файл `Looper/Plans/PER_AGENT_MODEL_REASONING_ARCH_CONTEXT_2026_02_19.md` как source of truth.

Задача на этот чат:
1) Кратко (но предметно) проверь актуальность описанного current state по коду.
2) Предложи 2-3 варианта конечной архитектуры per-agent профилей (`runner + model + reasoning`) с trade-offs.
3) Выбери рекомендуемый вариант и объясни почему он устойчивее к костылям.
4) Сформируй поэтапный migration plan.
5) Сделай pre-mortem этого плана: "представь, что уже внедрили и получилось плохо" — найди слабые места и исправь план.
6) Дай финальный, критически отревьюенный план, пригодный для реализации.

Ограничения:
- Пока без правок кода.
- Фокус на архитектуре, валидации, обратной совместимости и эксплуатационной понятности.
- Явно зафиксируй precedence (CLI vs profile vs global vs backend-default).
```

