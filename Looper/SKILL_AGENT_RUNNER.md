# SKILL AGENT-RUNNER

> **Для оркестраторов:** Создание Executor — это ОБЯЗАТЕЛЬНЫЙ первый шаг после получения задачи.
> Оркестратор не имеет права выполнять код самостоятельно. Все задачи реализации делегируются через этот скил.
> Если задача допускает параллельное выполнение нескольких подзадач — создавай нескольких исполнителей и запускай их одновременно.

# Создание структуры файлов агента лупера
- Выбираем название агенту. Должно быть простым, совместимым с файловой системой.
- Сначала создается структура файлов для работы лупера:
Run the script from the target parent folder, or call it by full path.  
Example: `cd /d <ProjectPath>\Executors && "C:\CorrisBot\Looper\CreateExecutorStructure.bat" "Executor_002" "Orc1"` (quotes are required if arguments contain spaces; using quotes always is recommended).
(Здесь нюанс, что для Executors агентов есть отдельный подкаталог `Executors` в каталоге проекта).
Переходим в папку, где хотим создать каталог для агента, и запускаем оттуда. 
Первый праметр - это имя агента, второй - `SenderID` того, от кого этот агент ожидает входящие prompt-файлы (например, `Orc1`, `Orchestrator`, `Talker`).
Важно: второй параметр - это логическое имя отправителя (SenderID), а не имя каталога. Оркестратор может быть расположен в каталоге `Orchestrator`, но использовать SenderID `Orc1`.

# Запуск агента-лупера
- После создания файловой структуры запускается сам Лупер (как скрипт-терминала + ИИ агент). 
- Создается через запуск бат файла:
`C:\CorrisBot\Looper\StartLoopsInWT.bat "<ProjectPath>" "Executors\Executor_002"`
Первый параметр - это путь до проекта, второй - название лупера. 
Проектов в одном приложении может быть много (Пример вымышленный искать не нужно).
Например, `c:\Minesweeper\.MigrationToIOs`  - Это проект миграции на iOs.
А может быть `c:\Minesweeper\.UIRefactoring` - это проект рефакторинга.

# Выбор CLI-агента (runner)

Looper поддерживает два CLI-агента для выполнения задач:
- **Codex** (OpenAI) — дефолтный агент, используется по умолчанию
- **Kimi** (Kimi Code CLI) — альтернативный агент

## Указание runner при запуске

### Через StartLoopsInWT.py
В конфигурационном файле `loops.wt.json` добавьте поле `"runner"`:
```json
{
  "runner": "kimi",
  "max_panes_per_tab": 4
}
```
Допустимые значения: `"codex"` (по умолчанию) или `"kimi"`.

### Через .bat файлы напрямую
- **Codex**: `CodexLoop.bat <project_root> [agent_path]`
- **Kimi**: `KimiLoop.bat <project_root> [agent_path]`

### Через codex_prompt_fileloop.py
```bash
py -3 codex_prompt_fileloop.py --project-root <path> --agent-path <path> --runner <codex|kimi>
```

## Особенности Kimi Runner

- Session ID определяется через файловую систему (`~/.kimi/sessions/`)
- Нет аналога `turn.completed` — процесс завершается по EOF
- Промпт передаётся через аргумент `-c` (не через stdin)
- Длинные промпты (>8000 символов) автоматически записываются во временный файл

### Stopping an agent looper (graceful)

When an agent looper is no longer needed, stop it via inbox prompt command:

1. Create local file with first line `/looper stop` (for example: `Temp\looper_stop.md`).
2. Publish it to target sender inbox using helper script:
   `py "C:\CorrisBot\Looper\create_prompt_file.py" create --inbox "Prompts\Inbox\<SenderID>" --from-file "Temp\looper_stop.md"`
3. Ensure the first non-empty line is exactly:
   `/looper stop`
4. Do not add any other command on that first line.

Behavior:
- The looper stops at script level (no LLM call for this prompt).
- The prompt is marked as processed, and the process exits cleanly.
- Later, restart with the same launcher (WT launcher) to continue normal work.
