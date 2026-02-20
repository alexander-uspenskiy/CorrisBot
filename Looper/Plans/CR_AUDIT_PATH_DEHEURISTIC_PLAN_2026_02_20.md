# CR: AUDIT_PATH_DEHEURISTIC_PLAN_2026_02_20

## Scope
Reviewed file:
- `Looper/Plans/AUDIT_PATH_DEHEURISTIC_PLAN_2026_02_20.md`

Focus:
- remove heuristic audit-path behavior;
- preserve fail-closed transport model;
- avoid introducing new ambiguous precedence.

## Findings
No blocking findings.

## Strengths
1. Correctly identifies the current weak point: parent-path probing around `incoming_prompt` is heuristic and should be removed.
2. Enforces explicit configuration with fail-closed behavior (`--audit-file` required).
3. Defines deterministic scope policy for audit path and rejects out-of-scope writes.
4. Keeps idempotency semantics stable (composite key remains unchanged).
5. Includes concrete migration phases and mandatory negative tests.

## Non-Blocking Notes
1. Strict requirement for `--audit-file` will break undocumented manual usage; this is acceptable and explicitly documented.
2. If future need appears for metadata-driven audit path (`Message-Meta.AuditFile`), it should be introduced only with strict ownership and scope checks (not in this plan).

## Verdict
Ready for execution.

Plan is aligned with "no heuristic + fail-closed" policy and should reduce routing/audit ambiguity without widening behavioral surface.
