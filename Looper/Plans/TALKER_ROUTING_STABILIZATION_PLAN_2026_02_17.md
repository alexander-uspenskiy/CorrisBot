# Talker Routing Stabilization Plan (Self-Contained)

Date: 2026-02-17  
Scope: `Talker` routing only  
Mode: single user / single Talker loop / single Talker LLM session

## 1) Problem Summary

Observed incident:
- Orchestrator produced a valid response and wrote it to Talker inbox.
- Talker processed that message, but relay was delivered to `tg_user` instead of the real user sender (`tg_corriscant`).
- As a result, Telegram user did not receive Orchestrator reply.

Confirmed from logs:
- Talker selected internal sender prompt and processed it.
- Relay file was created in wrong sender folder (`Talker/Prompts/Inbox/tg_user/..._relay_Result.md`).

Root cause:
- Relay target depended on LLM-generated YAML target value, with no strict runtime contract for user route.

## 2) Operating Model (Explicit Assumptions)

For current product mode:
- one real user,
- one Talker looper process,
- one Talker LLM session,
- multiple internal agents (`Orc_*`, `Worker_*`, etc.).

Implication:
- no multi-user routing logic is needed in Talker runtime;
- Talker should have one fixed user destination route.

## 3) Target Contract (Authoritative)

Introduce one canonical runtime field:
- `user_sender_id` (fixed user destination sender id).

Rules:
1. Relay delivery is allowed only to `user_sender_id`.
2. If `user_sender_id` is empty, relay must fail with explicit protocol error.
3. If relay YAML `target` != `user_sender_id`, relay must fail with explicit protocol error.
4. No heuristics, no fallback, no "guessing", no auto-rewrite of target.
5. On actual delivery path, destination directory must be created if missing (`mkdir`), per base IO contract.

Terminology constraint:
- Do not use "active channel" semantics in code/docs for this mode.
- Use fixed `user_sender_id`.

## 4) State File Contract

Path:
- `Talker/Prompts/Inbox/routing_state.json`

Schema:
- `user_sender_id: string | ""`
- `updated_at: string`
- `updated_by: string` where value is one of:
  - `bootstrap`
  - `operator_command`
  - `reset`

State mutation rules:
- `user_sender_id` changes only by explicit operator action or reset.
- Processing ordinary prompts (user or internal) must not auto-change `user_sender_id`.

## 5) Bootstrap and Control Surface (v1)

Bootstrap policy (v1):
- only operator command is supported:
  - `/routing set-user <SenderID>`

Control commands to support:
- `/routing show`
- `/routing set-user <SenderID>`
- `/routing clear`

Until bootstrap is done:
- relay attempts must emit explicit protocol error and skip delivery.

## 6) Runtime Relay Algorithm

For each processed prompt:
1. Read `routing_state.json` (if missing -> `user_sender_id = ""`).
2. Run normal agent processing.
3. If relay block exists in result:
   - validate `user_sender_id` is set;
   - validate `target == user_sender_id`;
   - if valid:
     - ensure destination exists (`mkdir(parents=True, exist_ok=True)`),
     - write `Prompt_<timestamp>_relay_Result.md` into `Inbox/<user_sender_id>/`;
   - if invalid:
     - log explicit `[relay] protocol error: ...`,
     - do not deliver.

## 7) Migration From Existing Docs/Rules

Current docs still contain project mapping model:
- `<ProjectTag> -> <UserSenderID>`

For this product mode, migrate to fixed route model:
1. Mark project mapping as deprecated for Talker single-user runtime.
2. Define `user_sender_id` as single source of truth for relay delivery.
3. Clarify that internal `Reply-To` contracts do not mutate Talker user route.

## 8) Files To Change

Runtime:
- `Looper/codex_prompt_fileloop.py`

Docs (must be synchronized in same change set):
- `Talker/ROLE_TALKER.md`
- `Talker/AGENTS.md`
- `Looper/SKILL_GATEWAY_IO.md` (only relevant routing sections)
- any template source that regenerates Talker AGENTS (if used in this repository flow)

Scope guard:
- Any runtime branch added for this routing contract must be Talker-scoped, so other loopers are not affected.

## 9) Implementation Phases

Phase A: Docs-first alignment
- update terms to `user_sender_id` (remove "active channel" language),
- remove ambiguity between project mapping and fixed single-user route,
- document operator bootstrap commands.

Phase B: Runtime implementation
- enforce strict `user_sender_id` relay validation,
- remove auto-switch logic,
- keep mkdir on successful delivery path,
- ensure reset clears routing state.

Phase C: Control commands
- implement `/routing show`, `/routing set-user`, `/routing clear`.

Phase D: Verification
- unit and e2e checks (see section 10),
- smoke on test project,
- only then rollout.

## 10) Test Matrix (Mandatory)

Unit-level:
1. `user_sender_id` unset + relay block -> protocol error, no delivery.
2. `target != user_sender_id` -> protocol error, no delivery.
3. `target == user_sender_id` + missing destination folder -> folder created, relay delivered.
4. reset command/signal -> `routing_state.json` cleared.

E2E:
1. User message arrives -> Talker forwards to Orchestrator.
2. Orchestrator replies with relay YAML.
3. Talker delivers to fixed `user_sender_id`.
4. Telegram user receives message.

Negative E2E:
1. Orchestrator replies with wrong target.
2. Talker logs protocol error.
3. No misdelivery into alternative sender folder.

## 11) Pre-CR Checklist (Before Merge)

Design:
- one source of truth (`user_sender_id`) exists,
- no auto-switch behavior remains,
- protocol errors are explicit for unset/mismatch,
- mkdir behavior is preserved on actual delivery.

Implementation:
- no heuristic/fallback target resolution code,
- no prefix-based route selection logic,
- Talker-only scope is enforced,
- reset path clears routing state reliably.

Release:
- tests from section 10 are green,
- operator recovery path works,
- rollback steps are validated.

## 12) Rollback Plan

If regression appears:
1. Revert routing change commits.
2. Remove/clear `Talker/Prompts/Inbox/routing_state.json`.
3. Restart Talker loop.
4. Re-run smoke scenario.

## 13) Definition Of Done

Done only if all are true:
1. Talker never delivers relay to any target except `user_sender_id`.
2. No heuristic target recovery remains.
3. Wrong or missing target causes explicit protocol error only.
4. Telegram user receives Orchestrator reply in tested flow.
5. Docs and runtime are consistent in one merged state.

## 14) Ready-To-Use New-Chat Handoff Block

Use this block verbatim in a new chat:

```
Task: implement Talker routing stabilization using fixed user_sender_id contract.

Read first:
- Looper/Plans/TALKER_ROUTING_STABILIZATION_PLAN_2026_02_17.md

Hard requirements:
1) Single source of truth: routing_state.json -> user_sender_id.
2) Relay delivery only if YAML target == user_sender_id.
3) If user_sender_id unset OR target mismatch -> explicit protocol error, no delivery.
4) No heuristics, no fallback, no auto-switch logic.
5) Keep mkdir on successful delivery path.
6) Scope changes to Talker behavior; do not regress other loopers.
7) Update docs in same change set:
   - Talker/ROLE_TALKER.md
   - Talker/AGENTS.md
   - Looper/SKILL_GATEWAY_IO.md (relevant parts only)

Deliverables:
- code changes,
- doc changes,
- short CR summary with findings first,
- verification results for test matrix in the plan.
```
