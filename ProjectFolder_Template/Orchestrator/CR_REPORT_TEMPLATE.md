# CR Report Template

Этот файл задает единый формат отчета `CodeReviewer` для экономии токенов Оркестратора и стабильного приемочного CR.

## Full Form (default)
```md
# CR Report

## Scope
- Task/Plan: <path or id>
- Reviewed commit/diff: <commit-id or diff scope>
- Reviewed files:
  - <path:line or path>

## Findings
1. [SEVERITY: HIGH|MEDIUM|LOW] <title>
   - Location: <path:line>
   - Problem: <what is wrong>
   - Impact/Risk: <why this matters>
   - Required fix: <what must change>
2. ...

## Checks Performed
- <what was verified explicitly>
- <tests/commands and result summary>

## Not Verified
- <what was not checked and why>

## Risk Assessment
- Overall risk: HIGH|MEDIUM|LOW
- Release gate recommendation: BLOCK|ALLOW_WITH_RISKS|ALLOW

## Acceptance Recommendation
- Status: REJECT|NEEDS_FIX|ACCEPT
- Blocking items:
  - <id or short title>
```

## Short Form (allowed only for low-risk changes)
```md
# CR Report (Short)
- Scope: <task + files/diff>
- Findings: <none or numbered list with severity + path:line>
- Not Verified: <short list>
- Risk: LOW|MEDIUM|HIGH
- Recommendation: REJECT|NEEDS_FIX|ACCEPT
```

## Rules
- Никакой реализации в рамках CR: только анализ и рекомендации.
- Любой найденный дефект должен иметь `severity` и точную ссылку на файл (`path:line`).
- Если проверка неполная, раздел `Not Verified` обязателен.
