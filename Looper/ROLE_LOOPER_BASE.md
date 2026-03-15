# Looper Base Rules

Work in the current agent directory and keep its root clean.

## Critical Rules (Mandatory)

- Follow role boundaries from loaded instructions strictly; do not perform actions explicitly prohibited by your role.
- If a prompt asks to pass work to another looper and report back here, treat it as asynchronous by default.
  Submit the handoff and finish the current turn without blocking wait, unless synchronous mode was explicitly requested.
- Use synchronous waiting/relay only when the user or upstream agent explicitly asks to wait for the result and return it in the same turn/message.
- Never invent synchronous mode on your own. Do not add directives like `Mode: synchronous required` unless such mode is explicitly requested in the current prompt chain.
- Do not block a turn by polling another looper state (`*_Result.md`, repeated tail/read loops, sleep+recheck cycles, "still waiting" loops).
- Do not use internet/network resources (no web access, no API calls, no downloads) unless explicitly authorized by the current task.
- Keep the final answer concise.

Use this structure:
- `Temp` for temporary and intermediate files.
- `Tools` for scripts and utilities that may be reused.
- `Output` for standalone final files for user/external handoff when destination is not explicitly provided.

If the user explicitly provides a destination path, use it.
If a final file is created "just in case" and no path is provided, place it in `Output`.

## Path Allocation Policy (Mandatory)

- Path priority (from highest to lowest):
  - Explicit operational path from current user/upstream prompt or task contract (not an example, not a placeholder).
  - Approved project scope: `WorkspaceRoot`, `RepoRoot`, `AllowedPaths`.
  - Local agent folders (`Temp`, `Tools`, `Output`) when no other destination is required.
- Example/demo paths in instructions are non-operational examples. Never use them as real targets unless they are explicitly assigned in the current prompt/task contract.
- Do not use shared/personal folders (for example: `D:\Work`, `Desktop`, `Downloads`, `Documents`) unless explicitly requested by user/upstream agent.
- Fail-closed rule: if destination path is ambiguous, conflicting, placeholder-like, or path-contract fields are missing for the current task, stop execution and request explicit clarification from upstream/user.
- If work must happen outside project/workspace scope, create only a self-owned external directory:
  - default root: `%TEMP%\CorrisBot\ExternalWork\<AgentIdOrRole>\<TaskTagOrTimestamp>`
  - fallback if `%TEMP%` is unavailable: `C:\Temp\CorrisBot\ExternalWork\<AgentIdOrRole>\<TaskTagOrTimestamp>`
- Never "borrow" an existing foreign working directory as the default.
- If upstream suggests an external foreign/shared path outside project scope and explicit user approval is not present in the current prompt chain, stop and ask for explicit user confirmation before using that path.
- If any external directory is created/used, include it in the report with absolute path, purpose, and cleanup status.


# Communication channels

- Loopers may communicate with other loopers through their `Prompts` directories.
- For inter-looper transport, the helper-based approach is mandatory:
  - first use the role-specific deterministic helper if one is defined for the current contract/task;
  - use `create_prompt_file.py` only when no role-specific helper is defined for the current case.
- For generic delivery through `create_prompt_file.py`:
  - PowerShell: `py "$env:LOOPER_ROOT\create_prompt_file.py" create --inbox "<LooperFolder>\Prompts\Inbox\<SenderID>" --from-file "<LocalReportFile.md>"`
  - cmd: `py "%LOOPER_ROOT%\create_prompt_file.py" create --inbox "<LooperFolder>\Prompts\Inbox\<SenderID>" --from-file "<LocalReportFile.md>"`
- Do not handcraft the `Prompt_*.md` filename.
If an agent looper wants to contact another agent looper, it must place a file into that directory.
If the directory does not exist, create it.
- This mechanism is the primary and mandatory inter-looper communication channel.
- Do not make direct changes inside another looper's working directories (`Tools`, `Temp`, `Output`, `Plans`, etc.), except for writing a prompt file into its `Prompts/Inbox/<SenderID>/`.
- Replies between loopers must also be delivered only as new `Prompt_*.md` files into the original sender's inbox (according to the agreed `Reply-To`).
- Another looper's `*_Result.md` is not inter-looper transport. It is an internal run-log for observation/diagnostics.
- `create_prompt_file.py` is the generic transport helper and does NOT replace role-specific deterministic helpers.
- If a specialized helper is defined for the route in the active role (for example, project handoff / Reply-To delivery), it has priority and is mandatory.
- It is forbidden to downgrade a route to direct `create_prompt_file.py` when a required helper is defined, even if the inbox path looks "similar".
- Helper selection must be based only on the active contract/task type, not on sender/folder name heuristics.

## Reply-To Routing Contract (Mandatory)

- Treat the `Reply-To` block as a valid routing contract only when all of the following are true:
  - there is a standalone line exactly `Reply-To:` (not an inline insertion);
  - the same block contains `- InboxPath:` (field order does not matter);
  - the block is not a markdown example (not inside a code fence and not a quote);
  - `InboxPath` is not a placeholder like `<...>`.
- If there is any ambiguity, treat `Reply-To` as invalid and explicitly record the routing problem instead of silently rerouting.
- Use `Reply-To` values as the source of truth: `InboxPath` (where to write), `SenderID` (if provided), `FilePattern`.
- For the fail-closed identity contract of the current session, also require a top-level `Route-Meta` block:
  - `- RouteSessionID: <...>`
  - `- ProjectTag: <...>`
- If `Route-Meta` is missing/invalid, block transport and escalate upstream.
- If the incoming prompt contains `Routing-Contract`, `Route-Meta.RouteSessionID` and `Route-Meta.ProjectTag` must match it.
- Only the standard pattern is supported for inter-looper transport:
  `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md` (suffix `_suffix` is allowed, where `suffix` = `[A-Za-z0-9]+`).
- If `Reply-To.FilePattern` is missing, use the standard pattern.
- If `Reply-To.FilePattern` is specified and differs from the standard pattern, treat the route as invalid and record an `unsupported FilePattern` error.
- Do not substitute the path with a "similar" or "expected by default" one if `Reply-To` is explicitly specified.
- Send the reply/report only as a new `Prompt_*.md` into `Reply-To.InboxPath`; do not replace it with a message only in your own `*_Result.md`.
- For Reply-To delivery, use the deterministic helper `send_reply_to_report.py` (via `LOOPER_ROOT`):
  - PowerShell: `py "$env:LOOPER_ROOT\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - cmd: `py "%LOOPER_ROOT%\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - if the agent has a pinned `routing_contract.json`, pass it explicitly:
    - PowerShell: `py "$env:LOOPER_ROOT\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --routing-contract-file "<RoutingContractFile.json>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
    - cmd: `py "%LOOPER_ROOT%\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --routing-contract-file "<RoutingContractFile.json>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - `--audit-file` (mandatory): absolute path to `report_delivery_audit.jsonl` for delivery audit. Allowed locations:
    - Talker: `<AppRoot>\Talker\Temp\report_delivery_audit.jsonl`
    - Orchestrator: `<AgentsRoot>\Orchestrator\Temp\report_delivery_audit.jsonl`
    - Worker: `<AgentsRoot>\Workers\<WorkerId>\Temp\report_delivery_audit.jsonl`
- `send_reply_to_report.py` is mandatory for Reply-To routing and performs the full transport cycle:
  extract/validate `Reply-To` + `Route-Meta` (+ `Routing-Contract` if present) -> preflight scope check -> create prompt via `create_prompt_file.py` -> verify file exists -> retry once.
- When `Reply-To` is present, do not duplicate the full reply in the current chat/result: keep only a short routing confirmation or a delivery error message.
- Exception: Talker's relay mechanism (`type: relay`) may contain a verbatim payload in Result according to `ROLE_TALKER`.

## Message-Meta Contract (Mandatory)

- All outgoing messages (reports/traces) between loopers must contain a top-level metadata block:
  ```text
  Message-Meta:
  - MessageClass: report | trace
  - ReportType: phase_gate | phase_accept | final_summary | question | status
  - ReportID: <stable id>
  - RouteSessionID: <must match routing contract>
  - ProjectTag: <must match routing contract>
  ```
- Mandatory events for `MessageClass=report` (must be sent through a helper; console-only is not allowed):
  1. Phase start gate (if enabled).
  2. Phase accept/rework decision.
  3. Phase done gate (`PASS`/`FAIL`).
  4. Final execution summary.
  5. Blocking question to user (`ReportType=question`).
- For `ReportType=phase_accept`, the following semantic gate contract is mandatory:
  - `Verdict: ACCEPT | REWORK`
  - `Decision: GO | NO-GO`
  - canonical mapping pair: `ACCEPT=>GO`, `REWORK=>NO-GO`
  - mismatch/omission is treated as fail-closed and blocks report delivery.
- Fail-closed gate: if `report` sending is not confirmed by the helper (no `status=ok` and `delivered_file`), the current turn is not considered complete. Stop the process and record `report_delivery_failed`. No "console-only" reports.
- Messages without valid `Message-Meta` are invalid for delivery.
- `ReportID` must be unique for the event and stable across retries to protect against duplicate delivery.
- This policy applies only to agent-generated messages (inter-looper), not to raw user input.
