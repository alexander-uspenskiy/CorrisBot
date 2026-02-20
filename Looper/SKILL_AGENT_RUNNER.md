# SKILL AGENT-RUNNER

> **Для оркестраторов:** Создание Worker — это ОБЯЗАТЕЛЬНЫЙ первый шаг после получения задачи.
> Оркестратор не имеет права выполнять код самостоятельно. Все задачи реализации делегируются через этот скил.
> Если задача допускает параллельное выполнение нескольких подзадач — создавай нескольких исполнителей.
> Для последовательного старта нескольких луперов используй `start_loops_sequential.py` (не ad-hoc набор отдельных команд).

Path note:
- Все пути в примерах этого skill являются демонстрационными.
- Не используй примерный путь как рабочий default, если он не задан явно в текущем task contract/пользовательском запросе.
- Для внешних рабочих каталогов следуй `Path Allocation Policy` из `ROLE_LOOPER_BASE`.

# Создание структуры файлов агента лупера
- Выбираем название агенту. Должно быть простым, совместимым с файловой системой.
- Сначала создается структура файлов для работы лупера:
Run the script from the target parent folder, or call it by full path.  
Examples:
- PowerShell: `Set-Location "<ProjectPath>\Workers"; & "$env:LOOPER_ROOT\CreateWorkerStructure.bat" "Worker_002" "Orc1"`
- cmd: `cd /d "<ProjectPath>\Workers" && "%LOOPER_ROOT%\CreateWorkerStructure.bat" "Worker_002" "Orc1"`
(quotes are required if arguments contain spaces; using quotes always is recommended).
(Здесь нюанс, что для Workers агентов есть отдельный подкаталог `Workers` в каталоге проекта).
Переходим в папку, где хотим создать каталог для агента, и запускаем оттуда. 
Первый праметр - это имя агента, второй - `SenderID` того, от кого этот агент ожидает входящие prompt-файлы (например, `Orc1`, `Orchestrator`, `Talker`).
Важно: второй параметр - это логическое имя отправителя (SenderID), а не имя каталога. Оркестратор может быть расположен в каталоге `Orchestrator`, но использовать SenderID `Orc1`.

# Запуск агента-лупера
- После создания файловой структуры запускается сам Лупер (как скрипт-терминала + ИИ агент). 
- Создается через запуск `StartLoopsInWT.bat` через `LOOPER_ROOT`:
  - PowerShell: `& "$env:LOOPER_ROOT\StartLoopsInWT.bat" "<ProjectPath>" "Workers\Worker_002"`
  - cmd: `"%LOOPER_ROOT%\StartLoopsInWT.bat" "<ProjectPath>" "Workers\Worker_002"`
Первый параметр - это путь до проекта, второй - название лупера. 
Проектов в одном приложении может быть много (Пример вымышленный искать не нужно).
Например, `c:\Minesweeper\.MigrationToIOs`  - Это проект миграции на iOs.
А может быть `c:\Minesweeper\.UIRefactoring` - это проект рефакторинга.
- Если нужно запустить несколько луперов, используй deterministic helper:
  - PowerShell: `py "$env:LOOPER_ROOT\start_loops_sequential.py" --project-root "<ProjectPath>" "Workers\Worker_002" "Workers\Worker_003"`
  - cmd: `py "%LOOPER_ROOT%\start_loops_sequential.py" --project-root "<ProjectPath>" "Workers\Worker_002" "Workers\Worker_003"`
- Для smoke/безопасной проверки допускается `--dry-run`:
  - `py "$env:LOOPER_ROOT\start_loops_sequential.py" --project-root "<ProjectPath>" --dry-run "Workers\Worker_002" "Workers\Worker_003"`
- `start_loops_sequential.py` гарантирует последовательный запуск и stop-on-first-error.
- Параллелизация делается на уровне задач/исполнителей после старта, а не на уровне одновременного старта WT-панелей.

# Выбор CLI-агента (runner)

Looper поддерживает два CLI-агента для выполнения задач:
- **Codex** (OpenAI) — дефолтный агент, используется по умолчанию
- **Kimi** (Kimi Code CLI) — альтернативный агент

## Профили и профильные операции (Phase 5)

Источник истины для runner/model/reasoning:
- `agent_runner.json`
- `codex_profile.json`
- `kimi_profile.json`
- runtime-root registry: `<RuntimeRoot>/AgentRunner/model_registry.json`

Для setup/update профилей использовать deterministic helper:
- `Looper/profile_ops.py`

### Проверка профилей (validate)
- PowerShell:
  - `py "$env:LOOPER_ROOT\profile_ops.py" validate --agent-dir "<AgentDir>"`
- cmd:
  - `py "%LOOPER_ROOT%\profile_ops.py" validate --agent-dir "<AgentDir>"`

### Изменение runner
- Orchestrator -> Worker:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-runner --agent-dir "<ProjectRoot>\Workers\Worker_001" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --runner codex`
- Talker -> Orchestrator/Talker:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-runner --agent-dir "<ProjectRoot>\Orchestrator" --actor-role talker --actor-id "<TalkerSenderID>" --request-ref "<RequestRef>" --intent explicit --runner kimi`

### Изменение backend model/reasoning
- Set model:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-backend --agent-dir "<AgentDir>" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --backend codex --model codex-5.3-mini`
- Set Codex reasoning:
  - `py "$env:LOOPER_ROOT\profile_ops.py" set-backend --agent-dir "<AgentDir>" --actor-role orchestrator --actor-id "<OrchestratorSenderID>" --request-ref "<RequestRef>" --intent explicit --backend codex --reasoning-effort high`

Правила:
- mutation разрешена только при явном intent (`--intent explicit` + `--request-ref`).
- helper применяет ownership-check, lock + atomic replace, и пишет audit в `<RuntimeRoot>/AgentRunner/profile_change_audit.jsonl`.
- ошибки мутации также пишутся в audit с `result=error`.

## Launch overrides (временные)

- Launch path использует per-agent resolver/profile как baseline.
- CLI overrides (`--runner`, `--model`, `--reasoning-effort`) допустимы как launch/runtime overrides по контракту фаз 3-4.
- `loops.wt.json` используется только для WT layout/оконных настроек, не как runtime source-of-truth для runner.
- Legacy fields `runner` / `_runner_help` в `loops.wt.json` удалены в финальном cutover (Phase 7).

## Особенности Kimi Runner

- Session ID определяется через файловую систему (`~/.kimi/sessions/`)
- Нет аналога `turn.completed` — процесс завершается по EOF
- Промпт передаётся через аргумент `-c` (не через stdin)
- Длинные промпты (>8000 символов) автоматически записываются во временный файл

### Stopping an agent looper (graceful)

When an agent looper is no longer needed, stop it via inbox prompt command:

1. Create local file with first line `/looper stop` (for example: `Temp\looper_stop.md`).
2. Publish it to target sender inbox using helper script:
   - PowerShell: `py "$env:LOOPER_ROOT\create_prompt_file.py" create --inbox "Prompts\Inbox\<SenderID>" --from-file "Temp\looper_stop.md"`
   - cmd: `py "%LOOPER_ROOT%\create_prompt_file.py" create --inbox "Prompts\Inbox\<SenderID>" --from-file "Temp\looper_stop.md"`
3. Ensure the first non-empty line is exactly:
   `/looper stop`
4. Do not add any other command on that first line.

Behavior:
- The looper stops at script level (no LLM call for this prompt).
- The prompt is marked as processed, and the process exits cleanly.
- Later, restart with the same launcher (WT launcher) to continue normal work.
