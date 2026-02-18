# Prompt Pack: Orchestrator + Workers (Portable Migration)

Дата: 2026-02-18  
Репозиторий: `C:\CorrisBot`

## 1) Что делать вам (оператору)
1. Откройте новый чат с Оркестратором.
2. Вставьте блок из раздела `2) Prompt для Оркестратора`.
3. Если нужно вручную запускать отдельные Worker-чаты, используйте блоки из раздела `3) Worker Prompts`.

## 2) Prompt для Оркестратора (копировать целиком)

```text
Task: execute full portability migration using:
- Looper/Plans/PORTABILITY_MIGRATION_EXECUTION_PLAN_2026_02_18.md
- Looper/Plans/PORTABILITY_MIGRATION_AUDIT_2026_02_18.md

Hard constraints:
1) No partial rollout. Only full migration.
2) Follow the execution plan phase-by-phase with intermediate commits.
3) Mandatory CR gates: A(after stage 1), B(after stages 2-3), C(after stage 4), D(after stage 6 before final sign-off).
4) Mandatory Anti-Hack gate at each CR gate.
5) Do not edit generated AGENTS.md manually. Edit sources and rebuild.
6) Findings-first reporting at each CR gate (High -> Medium -> Low).
7) Deterministic flow only: no heuristic decisions and no parallel execution of workers for this task.
8) Safety: no destructive git/file commands (`git reset --hard`, `git checkout --`, mass deletes outside scope).

Execution model:
1) Create and run Worker_1 for stage 1 (runtime paths).
2) Create and run Worker_2 for stages 2-3 (assemble_agents + Read-chain).
3) Create and run Worker_3 for stages 4-5 (ROLE/SKILL/injected rules/docs + rebuild).
4) You (Orchestrator) perform merge-level acceptance and run stage 6 E2E from non-C:\CorrisBot path.
5) After each stage/gate, provide operator-readable status and explicit Go/No-Go.
6) Strict order (mandatory): Worker_1 -> Gate A -> Worker_2 -> Gate B -> Worker_3 -> Gate C -> Stage 6 E2E -> Gate D.
7) Do not start next worker until previous gate is `Go`.

Deliverables:
1) Commit list with SHAs per phase.
2) CR gate reports A/B/C/D with findings first.
3) Final grep report for C:\CorrisBot outside excluded plans.
4) Final E2E evidence from alternative repo path.
```

## 3) Worker Prompts (если хотите запускать вручную отдельные чаты)

### 3.1 Worker 1 (Stage 1: runtime paths)

```text
Task: execute stage 1 only from:
Looper/Plans/PORTABILITY_MIGRATION_EXECUTION_PLAN_2026_02_18.md

Scope files:
- Looper/CreateProjectStructure.bat
- Looper/CreateWorkerStructure.bat
- Looper/CodexLoop.bat
- Looper/KimiLoop.bat
- Gateways/Telegram/run_gateway.bat
- Gateways/Telegram/tg_codex_gateway.py

Requirements:
1) Remove runtime hardcoded C:\CorrisBot.
2) Use computed roots from script location and unified env contract.
3) Keep behavior backward-compatible.
4) Provide verification commands/output summary.
5) Run mandatory CR -> fix -> CR before finalizing.
6) Do not edit generated AGENTS.md manually.
7) Safety: do not use destructive git/file commands.

Verification checklist (mandatory, report pass/fail for each item):
1) `rg -n -F "C:\\CorrisBot" Looper/CreateProjectStructure.bat Looper/CreateWorkerStructure.bat Looper/CodexLoop.bat Looper/KimiLoop.bat Gateways/Telegram/run_gateway.bat Gateways/Telegram/tg_codex_gateway.py`
2) Dry-run/usage checks for updated `.bat` launchers.
3) Confirm computed roots are printed/logged and not pointing to legacy fixed path.
4) Confirm `LOOPER_ROOT` is visible in child process environment where applicable.

Deliver:
1) Patch + one commit for stage 1.
2) Short CR findings report (High/Medium/Low).
3) Checklist results table (item -> command -> expected -> actual -> status).
4) Handoff note for Gate A.
```

### 3.2 Worker 2 (Stages 2-3: assemble + Read chain)

```text
Task: execute stages 2-3 only from:
Looper/Plans/PORTABILITY_MIGRATION_EXECUTION_PLAN_2026_02_18.md

Scope files:
- Looper/assemble_agents.py
- Talker/AGENTS_TEMPLATE.md
- ProjectFolder_Template/Orchestrator/AGENTS_TEMPLATE.md
- ProjectFolder_Template/Workers/Worker_001/AGENTS_TEMPLATE.md
- Talker/SKILL_TALKER.md
- Talker/ROLE_TALKER.md (only Read-chain related parts)
- ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md (Read-chain related part)

Requirements:
1) Relative Read resolution must be from source file directory.
2) Migrate source Read links away from absolute C:\CorrisBot.
3) Rebuild and verify AGENTS generation.
4) Run mandatory CR -> fix -> CR.
5) Do not edit generated AGENTS.md manually.
6) Safety: do not use destructive git/file commands.

Verification checklist (mandatory, report pass/fail for each item):
1) Build succeeds from repo root (`py Looper/assemble_agents.py ...`).
2) Build succeeds from a different cwd (for example from `Looper/` with adjusted relative args).
3) `Read:` chain resolves without absolute `C:\CorrisBot` in source templates.
4) Rebuilt outputs are produced from updated sources.

Deliver:
1) Patch + exactly one commit for stage 2 and exactly one commit for stage 3.
2) Validation summary for build from different cwd.
3) Checklist results table (item -> command -> expected -> actual -> status).
4) Handoff note for Gate B.
```

### 3.3 Worker 3 (Stages 4-5: LLM operational commands + docs + rebuild)

```text
Task: execute stages 4-5 only from:
Looper/Plans/PORTABILITY_MIGRATION_EXECUTION_PLAN_2026_02_18.md

Scope files:
- Talker/ROLE_TALKER.md
- Looper/ROLE_LOOPER_BASE.md
- Looper/SKILL_AGENT_RUNNER.md
- Looper/SKILL_GATEWAY_IO.md
- Looper/codex_prompt_fileloop.py
- Gateways/Telegram/AGENTS.md
- Looper/StartLoopsInWT.bat
- Looper/CleanupPrompts.bat
- Looper/create_prompt_file.py
- generated AGENTS rebuild outputs

Requirements:
1) Remove operational hardcoded C:\CorrisBot from ROLE/SKILL/injected rules/docs.
2) Use unified LOOPER_ROOT-based command contract.
3) Ensure commands are explicit for PowerShell and cmd where needed.
4) Rebuild generated AGENTS and validate residual grep.
5) Run mandatory CR -> fix -> CR.
6) Do not edit generated AGENTS.md manually.
7) Safety: do not use destructive git/file commands.

Verification checklist (mandatory, report pass/fail for each item):
1) `rg -n -F "C:\\CorrisBot"` over stage-4/5 scope files shows no operational hardcoded paths.
2) `Talker/AGENTS.md` rebuilt after source changes.
3) Commands include explicit PowerShell (`$env:LOOPER_ROOT`) and cmd (`%LOOPER_ROOT%`) forms where required.
4) Residual grep outside excluded plans matches expected clean state.

Deliver:
1) Patch + exactly one commit for stage 4 and exactly one commit for stage 5.
2) Residual grep summary.
3) Checklist results table (item -> command -> expected -> actual -> status).
4) Handoff note for Gate C.
```

## 4) Короткий шаблон запроса к Оркестратору на старт Worker-чата

```text
Вот промпт для Worker <N>. Запусти этого Worker и делегируй ему задачу дословно.
После получения результата выполни приемочный CR и дай мне Go/No-Go по соответствующему gate.
```

## 5) Что должен вернуть Оркестратор вам в конце
1. Список коммитов по этапам.
2. Отчеты CR-gates A/B/C/D.
3. Подтверждение Anti-Hack gate по каждому этапу.
4. Финальный E2E отчет из пути вне `C:\CorrisBot`.
