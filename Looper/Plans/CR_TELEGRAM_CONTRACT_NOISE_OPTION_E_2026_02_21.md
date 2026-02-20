# Code Review (CR): Machine-Header Isolation Plan (Option E)

**Date**: 2026-02-21
**Target Document**: `implementation_plan.md` (Implementation of Option E)
**Focus**: Architectural safety, fail-closed mechanics, contract adherence, risk of regression.

## 1. Plan Overview
The proposed plan aims to solve the Telegram output "noise" (`EDIT_ROOT`, `RUN_ROOT`) by having `codex_prompt_fileloop.py` explicitly parse and remove the `Routing-Contract:` and `Reply-To:` blocks from the incoming markdown before presenting the prompt string to the LLM. 

## 2. Findings & Critical Flaws

### ❌ Critical Flaw: Loss of Absolute Path Context (Blind Orchestrator)
- **Problem:** According to `ROLE_ORCHESTRATOR.md`, the Orchestrator must enforce strict path governance for Worker tasks. It is required to specify `RepoRoot`, `WorkspaceRoot`, and `AgentsRoot` in each `task-prompt` directed to a Worker.
- If `codex_prompt_fileloop.py` perfectly hides the `Routing-Contract` from the user message, the LLM Orchestrator will have **no knowledge** of its own environment. It will not know what `EDIT_ROOT` or `APP_ROOT` is unless explicitly passed by the user in every message.
- **Impact:** The Orchestrator will fail to construct valid JSON/YAML task contracts for Workers (unable to populate `RepoRoot`). It will either hallucinate paths, fail-close and constantly ask the user for the path, or generate invalid tasks. This causes a massive system regression.

### ⚠️ Minor Flaw: Missing Instructional Reinforcement
- While removing the machine-readable block reduces the "copy-paste/echo" effect, LLMs still tend to leak their system prompts into output when generating comprehensive reports.
- If the paths are reintroduced via another mechanism, they must be explicitly prohibited from appearing in human-readable reports to guarantee cleanliness.

## 3. Recommended Fixes (Option E V2)

The core idea of extracting the YAML-like block is excellent, but we must project the necessary environment variables back into the LLM's context safely.

1. **Safe Context Projection:**
   In `codex_prompt_fileloop.py` (`build_loop_prompt`), after stripping the `Routing-Contract` block from the user message, the Python runner must inject a plain-text context into the **Read-Only System Rules** section (e.g., alongside "Loop execution rules (strict):").
   ```text
   Project Environment (Read-Only Context):
   - App Root: <AppRoot>
   - Agents Root: <AgentsRoot>
   - Edit Root (Repo): <EditRoot>
   ```
   By placing it here instead of the "Incoming prompt" body, the LLM understands it as system background, not a payload that needs mirroring.

2. **Instructional Guardrail (Option A hybrid):**
   Update `ROLE_ORCHESTRATOR.md` and `ROLE_WORKER.md` as originally considered in Option A:
   *"Never echo or mirror operational paths (AppRoot, AgentsRoot, EditRoot) in your human-readable reports. These paths are internal system context."*

3. **Verify Header Stripping Logic:**
   Ensure `strip_markdown_block` in `route_contract_utils.py` is extremely precise. It must not accidentally truncate the actual verbatim `User-Message` if it happens to contain similar formatting or keywords.

## 4. Final Verdict
**STATUS: REVISION REQUIRED**

The current implementation plan will cause a total operational halt for the Orchestrator's delegation capability due to path context starvation. 

**Next Action:** Update `implementation_plan.md` to incorporate "Safe Context Projection" in `codex_prompt_fileloop.py` and the associated instructional guardrails in the roles.
