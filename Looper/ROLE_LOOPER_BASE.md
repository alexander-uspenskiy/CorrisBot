# Looper Base Rules

Work in the current agent directory and keep its root clean.

## Critical Rules (Mandatory)

- Follow role boundaries from loaded instructions strictly; do not perform actions explicitly prohibited by your role.
- If a prompt asks to pass work to another looper and report back here, treat it as asynchronous by default.
  Submit the handoff and finish the current turn without blocking wait, unless synchronous mode was explicitly requested.
- Use synchronous waiting/relay only when the user or upstream agent explicitly asks to wait for the result and return it in the same turn/message.
- Never invent synchronous mode on your own. Do not add directives like `Mode: synchronous required` unless such mode is explicitly requested in the current prompt chain.
- Do not block a turn by polling another looper state (`*_Result.md`, repeated tail/read loops, sleep+recheck cycles, "still waiting" loops).
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

- Луперы могут общаться с другими луперами через их каталоги Prompts.
- Для межлуперного транспорта обязателен helper-подход:
  - сначала используй role-specific deterministic helper, если он задан для текущего контракта/задачи;
  - `create_prompt_file.py` используй только когда role-specific helper для текущего случая не определен.
- Для generic доставки через `create_prompt_file.py`:
  - PowerShell: `py "$env:LOOPER_ROOT\create_prompt_file.py" create --inbox "<LooperFolder>\Prompts\Inbox\<SenderID>" --from-file "<LocalReportFile.md>"`
  - cmd: `py "%LOOPER_ROOT%\create_prompt_file.py" create --inbox "<LooperFolder>\Prompts\Inbox\<SenderID>" --from-file "<LocalReportFile.md>"`
- Не формируй имя `Prompt_*.md` вручную.
То есть, если агент-лупер хочет связаться с другим агентом-лупером - он должен положить файл в каталог.
Если каталога нет - создать его.
- Этот механизм является основным и обязательным каналом межлуперной коммуникации.
- Нельзя вносить прямые изменения в рабочие каталоги другого лупера (`Tools`, `Temp`, `Output`, `Plans` и т.п.), кроме записи prompt-файла в его `Prompts/Inbox/<SenderID>/`.
- Ответ между луперами также передается только новым `Prompt_*.md` в inbox отправителя запроса (по согласованному `Reply-To`).
- `*_Result.md` другого лупера не является межлуперным транспортом. Это внутренний run-log для наблюдения/диагностики.
- `create_prompt_file.py` является общим транспортным helper и НЕ заменяет role-specific deterministic helpers.
- Если для маршрута в активной роли задан специализированный helper (например, project handoff / Reply-To delivery), он имеет приоритет и обязателен.
- Запрещено понижать маршрут до прямого `create_prompt_file.py`, если required helper определен, даже при "похожем" пути inbox.
- Выбор helper должен основываться только на активном контракте/типе задачи, а не на эвристике имени sender/folder.

## Reply-To Routing Contract (Mandatory)

- Считай блок `Reply-To` валидным контрактом маршрутизации, если одновременно выполняются условия:
  - есть отдельная строка ровно `Reply-To:` (не inline-вставка);
  - в рамках этого же блока присутствует `- InboxPath:` (порядок остальных полей не важен);
  - блок не является markdown-примером (не внутри code fence и не цитата);
  - `InboxPath` не плейсхолдер вида `<...>`.
- Если есть неоднозначность, считать `Reply-To` невалидным и явно зафиксировать проблему маршрутизации вместо молчаливого reroute.
- Используй значения `Reply-To` как источник истины: `InboxPath` (куда писать), `SenderID` (если задан), `FilePattern`.
- Для fail-closed identity-контракта текущей сессии дополнительно требуй top-level блок `Route-Meta`:
  - `- RouteSessionID: <...>`
  - `- ProjectTag: <...>`
- Если `Route-Meta` отсутствует/невалиден, блокируй transport и эскалируй upstream.
- Если во входящем prompt есть `Routing-Contract`, `Route-Meta.RouteSessionID` и `Route-Meta.ProjectTag` обязаны совпадать с ним.
- Для межлуперного транспорта поддерживается только стандартный pattern:
  `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md` (допустим суффикс `_suffix`, где `suffix` = `[A-Za-z0-9]+`).
- Если `Reply-To.FilePattern` отсутствует, используй стандартный pattern.
- Если `Reply-To.FilePattern` задан и отличается от стандартного pattern, считай маршрут невалидным и зафиксируй ошибку `unsupported FilePattern`.
- Нельзя подменять путь на "похожий" или "ожидаемый по умолчанию", если явно указан `Reply-To`.
- Ответ/отчет отправляй только новым `Prompt_*.md` в `Reply-To.InboxPath`; не заменяй это сообщением только в своем `*_Result.md`.
- Для Reply-To доставки используй deterministic helper `send_reply_to_report.py` (через `LOOPER_ROOT`):
  - PowerShell: `py "$env:LOOPER_ROOT\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - cmd: `py "%LOOPER_ROOT%\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - если у агента есть pinned `routing_contract.json`, передавай его явно:
    - PowerShell: `py "$env:LOOPER_ROOT\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --routing-contract-file "<RoutingContractFile.json>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
    - cmd: `py "%LOOPER_ROOT%\send_reply_to_report.py" --incoming-prompt "<IncomingPromptFile.md>" --routing-contract-file "<RoutingContractFile.json>" --report-file "<LocalReportFile.md>" --audit-file "<AuditFilePath>"`
  - `--audit-file` (обязательный): абсолютный путь к `report_delivery_audit.jsonl` для аудита доставки. Допустимые расположения:
    - Talker: `<AppRoot>\Talker\Temp\report_delivery_audit.jsonl`
    - Orchestrator: `<AgentsRoot>\Orchestrator\Temp\report_delivery_audit.jsonl`
    - Worker: `<AgentsRoot>\Workers\<WorkerId>\Temp\report_delivery_audit.jsonl`
- `send_reply_to_report.py` обязателен для Reply-To маршрута и выполняет весь транспортный цикл:
  extract/validate `Reply-To` + `Route-Meta` (+ `Routing-Contract` if present) -> preflight scope check -> create prompt via `create_prompt_file.py` -> verify file exists -> retry once.
- При `Reply-To` не дублируй полный ответ в текущем чате/result: оставляй только краткое подтверждение маршрутизации или сообщение об ошибке доставки.
- Исключение: relay-механизм Talker (`type: relay`) может содержать verbatim payload в Result по правилам `ROLE_TALKER`.

## Message-Meta Contract (Mandatory)

- Все исходящие сообщения (отчеты/трассы) между луперами должны содержать top-level блок метаданных:
  ```text
  Message-Meta:
  - MessageClass: report | trace
  - ReportType: phase_gate | phase_accept | final_summary | question | status
  - ReportID: <stable id>
  - RouteSessionID: <must match routing contract>
  - ProjectTag: <must match routing contract>
  ```
- Обязательные события для `MessageClass=report` (должны отправляться через helper, нельзя оставлять только в консоли):
  1. Phase start gate (если включен).
  2. Phase accept/rework decision.
  3. Phase done gate (`PASS`/`FAIL`).
  4. Final execution summary.
  5. Blocking question to user (`ReportType=question`).
- Fail-closed gate: если отправка `report` не подтверждена хелпером (нет `status=ok` и `delivered_file`), текущий turn не считается завершенным. Необходимо остановить процесс и зафиксировать `report_delivery_failed`. Никаких "console-only" отчетов.
- Сообщения без валидного `Message-Meta` считаются невалидными для отправки.
- `ReportID` должен быть уникальным для события и стабильным при ретраях для защиты от отправки дубликатов.
- Эта политика относится только к сообщениям самих агентов (межлуперным), а не к сырому пользовательскому вводу.
