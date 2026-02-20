# AUDIT PATH DE-HEURISTIC PLAN (2026-02-20)

## 1. Goal
Remove heuristic audit-path resolution from report delivery flow and replace it with explicit, fail-closed configuration.

Primary target:
- `Looper/send_reply_to_report.py` must stop inferring audit location by walking `incoming_prompt` parents.

## 2. Current Problem
Current behavior in `send_reply_to_report.py` resolves audit file by scanning path ancestors around `incoming_prompt` and looking for `Prompts/Inbox`.

Why this is unacceptable:
1. It is structural heuristic (depends on guessed directory shape).
2. It can silently pick unintended scope when prompt path is unusual.
3. It conflicts with fail-closed routing philosophy already adopted for transport.

## 3. Design Decision (No Heuristic)
Use explicit audit destination only.

Accepted sources (strict precedence):
1. `--audit-file <AbsolutePath>` CLI argument.
2. Optional `Message-Meta` field `AuditFile` (absolute path), only if enabled by policy.

Recommended for this migration:
- Implement source #1 first (mandatory).
- Keep #2 out of scope for now to avoid widening mutable surface.

Fail-closed rule:
- If `--audit-file` is missing/relative/out-of-scope -> block send with explicit error code (`report_audit_path_missing_or_invalid`).

## 4. Contract Changes
### 4.1 send_reply_to_report.py
Add required argument:
- `--audit-file` (absolute path to `report_delivery_audit.jsonl`).

Validation:
1. Absolute path only.
2. Parent directory must be allowed for current sender scope.
3. No fallback to cwd.
4. No fallback to path-walk from incoming prompt.

### 4.2 Scope Policy
Allowed audit-file roots (deterministic):
1. Talker sender scope:
- `AppRoot\Talker\Temp\...`
2. Orchestrator sender scope:
- `AgentsRoot\Orchestrator\Temp\...`
3. Worker sender scope:
- `AgentsRoot\Workers\<WorkerId>\Temp\...`

If `--audit-file` is outside allowed scope -> block.

## 5. Caller Updates
Every deterministic helper call to `send_reply_to_report.py` must pass `--audit-file`.

Required touch points:
1. Orchestrator role command templates.
2. Worker role command templates.
3. Any utility wrappers/scripts that call `send_reply_to_report.py`.

Suggested canonical values:
1. Orchestrator:
- `<ProjectRoot>\Orchestrator\Temp\report_delivery_audit.jsonl`
2. Worker:
- `<ProjectRoot>\Workers\<WorkerId>\Temp\report_delivery_audit.jsonl`
3. Talker (if it uses helper outbound):
- `<APP_ROOT>\Talker\Temp\report_delivery_audit.jsonl`

## 6. Idempotency Key (Keep Strict)
Keep composite match already introduced:
- `report_id`
- `route_session_id`
- `project_tag`
- `inbox_path`
- `result=ok`

Only behavior change in this plan:
- where audit file is read/written (explicit path, no inference).

## 7. Migration Phases
### Phase A: API Hardening
1. Add `--audit-file` required argument to `send_reply_to_report.py`.
2. Remove all audit path inference logic.
3. Add explicit validation + error codes.

### Phase B: Scope Validation
1. Implement deterministic scope checks for `--audit-file` using current routing contract roots.
2. Reject out-of-scope audit paths.

### Phase C: Call Site Update
1. Update all documented command snippets in roles.
2. Update automation/wrappers to pass explicit audit file.

### Phase D: Tests
Add/extend tests:
1. Missing `--audit-file` -> fail.
2. Relative `--audit-file` -> fail.
3. Out-of-scope `--audit-file` -> fail.
4. Valid in-scope `--audit-file` -> success.
5. Idempotency skip still works with explicit audit file.
6. Full suite regression gate passes.

## 8. Precedence Rules
For audit path resolution:
1. `--audit-file` (required)
2. otherwise hard stop

Forbidden:
1. `Path.cwd()` based audit placement.
2. `incoming_prompt` parent/ancestor probing.
3. Any “best effort” fallback audit location.

## 9. Acceptance Criteria
This plan is complete only if all are true:
1. No audit-path heuristic remains in runtime code.
2. Every `send_reply_to_report.py` invocation in role contracts includes explicit `--audit-file`.
3. Invalid/missing audit path blocks delivery early with clear error.
4. All relevant tests pass, including full `discover`.

## 10. Rollout Note
This is intentionally strict and may break ad-hoc/manual calls not passing `--audit-file`.
That is expected and desired in fail-closed mode.
