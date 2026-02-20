# CR: REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20

## Scope
Reviewed file:
- `Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md`

Review focus:
- closes the reported failure class (main reports visible in console but not in Telegram);
- regression risk for existing routing fail-closed contract;
- operational control of noise vs mandatory reports.

## Findings
No blocking findings.

## Strengths
1. Root cause is modeled correctly as contract/classification drift, not transport instability (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:18`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:20`).
2. Correct separation of semantics and mechanics:
- one deterministic transport path for all outbound messages;
- explicit classes `report` vs `trace` for filtering (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:22`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:35`).
3. Mandatory report events and fail-closed delivery gate are explicit (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:54`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:79`).
4. Filtering requirement preserves signal under noise suppression: `report` always relayed (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:81`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:89`).
5. Precedence forbids heuristic inference from body text (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:135`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:144`).

## Non-Blocking Notes (Addressed in Plan)
1. Duplicate risk during retries is covered by explicit `ReportID` idempotency + relay-side duplicate guard (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:80`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:82`, `Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:117`-`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:120`).
2. Contract scope is bounded to agent-generated outbound messages to avoid confusion with raw user prompt payload (`Looper/Plans/REPORT_CHANNEL_RECOVERY_PLAN_2026_02_20.md:53`).

## Verdict
Ready for execution.

The plan is implementable, deterministic, and directly restores guaranteed visibility of main reports while keeping optional trace muting.
