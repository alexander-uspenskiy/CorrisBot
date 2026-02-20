# Execution Report: Telegram Noise Cleanup (Option E v2)
**Date:** 2026-02-21

## Overview
This document summarizes the execution of the "Telegram Noise Cleanup (Option E v2)" plan. The objective was to eliminate the leaking of technical paths (`AppRoot`, `AgentsRoot`, `EditRoot`) into the human-readable payload delivered to users (e.g., via Telegram), while strictly adhering to the fail-closed transport semantics and maintaining the `VERBATIM` relay rule.

## Changed Files
1. `Looper/route_contract_utils.py`
2. `Looper/codex_prompt_fileloop.py`
3. `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
4. `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`
5. `Looper/tests/test_prompt_transport_isolation.py`
6. `Looper/tests/test_talker_routing_stabilization.py`

## Key Implementation Decisions (Diffs)

### 1. `route_contract_utils.py`
- Added the `remove_markdown_block` helper function.
- It robustly parses markdown blocks using exactly the same logic as the existing `_scan_markdown_block`.
- It properly ignores blocks inside code fences (`` ` ``) and markdown quotes (`>`).
- Completely strips out the entire `Routing-Contract:` section if present, ensuring it never hits the LLM context if not explicitly projected.

### 2. `codex_prompt_fileloop.py`
- Updated `build_loop_prompt` to detect `Routing-Contract:` in operational envelopes.
- Replaced the full `Routing-Contract:` block with a stripped-down `Transport Context (Read-Only):` projection.
- Base projection only includes `RouteSessionID` and `ProjectTag`.
- Path variables (`AgentsRoot`, `EditRoot`) are securely projected **only** if the context is `Orchestrator`. 
- Added `worker_name` argument to dynamically apply this logic.
- Talker agents remain correctly limited to `Fixed User Sender ID`.

### 3. Role Guardrails (`ROLE_ORCHESTRATOR.md`, `ROLE_WORKER.md`)
- Appended a strict rule under `## Communication Discipline` / `## Delivery Contract (Mandatory)`:
  - "Никогда не выводи системные пути (`AppRoot`, `AgentsRoot`, `EditRoot`) в читаемом тексте (human-readable body) сообщений/отчетов."
- This establishes the policy at the top structural level.

### 4. Tests Added
- Authored `test_prompt_transport_isolation.py` covering edge-case parsing of markdown blocks.
- Expanded `test_talker_routing_stabilization.py` with three new unit test suites to ensure proper block stripping and secure context projection based on correct agent roles.

## Commands Executed and Results
```bash
py -m unittest discover -s Looper/tests -p "test_*.py"
# ...
# Ran 84 tests in 67.346s
# OK
```
Unit tests are 100% green. 

## Residual Risks
- The markdown block parser behaves deterministically but could break if the platform transitions away from markdown-based envelopes into another format in the future.
- User payloads with a coincidentally identical header name `Routing-Contract:` outside fences would be processed by this logic. The probability of an actual user messaging the bot with this specific exact header format is extremely low.

## Status
Tasks from the implementation plan have been completed according to scope. Acceptance criteria achieved.
