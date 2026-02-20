# REPORT CHANNEL RECOVERY PLAN (2026-02-20)

## 1. Goal
Restore guaranteed delivery of intentional "main reports" from Orchestrator/Workers to user-facing channel (Talker -> Telegram) while keeping verbose operational stream optional.

Target outcome:
- disabling noisy stream must never hide phase/final reports;
- every mandatory report has delivery evidence (prompt file + helper result);
- console-only messages are never treated as delivered reports.

## 2. Problem Summary
Observed failure class:
- Orchestrator emits large phase/final texts to local console;
- only short status messages are sent via transport helper;
- Gateway sees only prompt files, not console lines;
- result: important reports are missing in Telegram despite being visible in local logs.

Root cause:
- contract drift in message classification ("what is a report" vs "what is trace");
- no fail-closed gate requiring explicit send for mandatory report events.

## 3. Design Principles
1. Single transport mechanism:
- all outbound human-visible messages use deterministic file transport helper.
- no special bypass channel for "main report".

2. Dual semantic channels:
- `report`: mandatory, user-facing, phase/final decisions.
- `trace`: optional, operational progress/noise.

3. Fail-closed for mandatory reports:
- if `report` send is not confirmed, turn is not considered completed.

4. No heuristic classification:
- report/trace class is explicit in envelope metadata.

## 4. Message Contract (Required)
Introduce top-level metadata block for all Orchestrator/Worker outbound messages:

```text
Message-Meta:
- MessageClass: report | trace
- ReportType: phase_gate | phase_accept | final_summary | question | status
- ReportID: <stable id>
- RouteSessionID: <must match routing contract>
- ProjectTag: <must match routing contract>
```

Rules:
- `MessageClass=report` is mandatory for phase gate decisions and final summary.
- `ReportID` must be unique per report event and stable across retries.
- messages without valid `Message-Meta` are treated as invalid for transport.
- scope: this contract applies to agent-generated outbound inter-looper reports/traces, not to raw user input prompt text.

## 5. Mandatory Report Events
The following events MUST be emitted as `MessageClass=report` and sent through helper:
1. Phase start gate (optional by policy; if enabled, still mandatory delivery once emitted).
2. Phase accept/rework decision.
3. Phase done gate (`PASS`/`FAIL`).
4. Final execution summary for whole task.
5. Blocking question to user (`ReportType=question`).

Console output for these events is informational only and cannot replace transport send.

## 6. Delivery Contract
For each `MessageClass=report`:
1. Build report payload file in local temp.
2. Send via deterministic helper (`send_reply_to_report.py` or equivalent single approved helper).
3. Capture helper JSON result with:
- `status=ok`
- `delivered_file`
- `route_session_id`
4. Write audit record:
- `report_id`
- `message_class`
- `report_type`
- `delivered_file`
- `timestamp_utc`
- `result`
5. If send fails: stop normal flow and escalate (`report_delivery_failed`), no silent continue.
6. Idempotency rule:
- before retry, check audit by `report_id`;
- if `result=ok` already exists, do not emit duplicate report to user channel.

## 7. User-Facing Filtering Model
Add runtime switch in Talker/Gateway relay policy:
- `TRACE_RELAY_ENABLED=true|false`

Behavior:
- `report` always relayed.
- `trace` relayed only when `TRACE_RELAY_ENABLED=true`.

This preserves operator ability to mute noise without losing main reports.

## 8. Ownership and Boundaries
1. Orchestrator:
- owns classification of its outbound messages (`report` vs `trace`);
- must enforce mandatory report send gate.

2. Worker:
- may send `report` to Orchestrator under same contract;
- Orchestrator decides which Worker reports are forwarded upstream.

3. Talker/Gateway:
- never infer "importance" from body text;
- use explicit `MessageClass` only.

## 9. Migration Plan

### Phase A: Contract Docs
- Update role docs (`ROLE_LOOPER_BASE.md`, `ROLE_ORCHESTRATOR.md`, `ROLE_WORKER.md`, `ROLE_TALKER.md`):
  - define `Message-Meta`;
  - define mandatory report events;
  - define fail-closed send gate for `report`.

### Phase B: Helper Integration
- Ensure outbound send path always goes through deterministic helper.
- Add thin wrapper (if needed) to compose `Message-Meta` + payload consistently.
- Ban direct "console-only report" as completion signal.

### Phase C: Relay Policy
- Implement `TRACE_RELAY_ENABLED` check at Talker/Gateway relay layer.
- Guarantee `report` bypasses this filter (always delivered).
- add duplicate guard by `ReportID` on Talker/Gateway side (best-effort safety against accidental double-send).

### Phase D: Audit and Observability
- Add report delivery audit file, for example:
  - `Orchestrator\Temp\report_delivery_audit.jsonl`
- Record both success and failure with stable `ReportID`.

### Phase E: Tests (Required)
Add/extend tests for:
1. `report` is relayed when trace relay is off.
2. `trace` is suppressed when trace relay is off.
3. missing `Message-Meta` for report event -> blocked.
4. helper failure on mandatory report -> run marked failed/escalated.
5. phase/final reports produce audit entries with `delivered_file`.
6. no regression in existing routing contract validation.
7. retry of same `ReportID` does not create duplicate Telegram delivery after prior success.

## 10. Precedence Rules
For outbound relay decision:
1. `Message-Meta.MessageClass`
2. routing contract validity (`RouteSessionID`, `ProjectTag`, Reply-To scope)
3. relay runtime flag (`TRACE_RELAY_ENABLED`) for trace only

Forbidden:
- decide by text patterns ("PASS", "итог", etc.);
- decide by console verbosity level;
- assume console line == delivered message.

## 11. Acceptance Criteria
Plan is done only if all true:
1. Every phase gate/final summary is visible in user channel even with trace relay disabled.
2. For each mandatory report, there is helper delivery evidence (`delivered_file`).
3. Turning trace relay off reduces noise but does not hide reports.
4. No mandatory report can end as "console-only".

## 12. Rollout Notes
- Recommended default: `TRACE_RELAY_ENABLED=true` for burn-in week, then switch to `false` once audit confirms stable report delivery.
- During rollout, treat any `report_delivery_failed` as blocker.
