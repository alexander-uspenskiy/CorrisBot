# SKILL AGENT-RUNNER

# Создание структуры файлов агента лупера
- Выбираем название агенту. Должно быть простым, совместимым с файловой системой.
- Сначала создается структура файлов для работы лупера:
Run the script from the target parent folder, or call it by full path.  
Example: `cd /d C:\Temp\ProjectName\Executors && "C:\CorrisBot\Looper\CreateExecutorStructure.bat" "Executor_002" "Orc1"` (quotes are required if arguments contain spaces; using quotes always is recommended).
(Здесь нюанс, что для Executors агентов есть отдельный подкаталог `Executors` в каталоге проекта).
Переходим в папку, где хотим создать каталог для агента, и запускаем оттуда. 
Первый праметр - это имя агента, второй - имя того, с кем он будет на связи (например, Orchestrator или Talker).

# Запуск агента-лупера
- После создания файловой структуры запускается сам Лупер (как скрипт-терминала + ИИ агент). 
- Создается через запуск бат файла:
`C:\CorrisBot\Looper\StartLoopsInWT.bat "C:\CorrisBot\ProjectFolder_Template" "Executors\Executor_001"`
Первый параметр - это путь до проекта, второй - название лупера. 
Проектов в одном приложении может быть много (Пример вымышленный искать не нужно).
Например, `c:\Minesweeper\.MigrationToIOs`  - Это проект миграции на iOs.
А может быть `c:\Minesweeper\.UIRefactoring` - это проект рефакторинга.

### Stopping an agent looper (graceful)

When an agent looper is no longer needed, stop it via inbox prompt command:

1. Create a normal prompt file in the target sender inbox (`Prompts/Inbox/<SenderID>/Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`).
2. Set the first non-empty line to exactly:
   `/looper stop`
3. Do not add any other command on that first line.

Behavior:
- The looper stops at script level (no LLM call for this prompt).
- The prompt is marked as processed, and the process exits cleanly.
- Later, restart with the same launcher (WT launcher) to continue normal work.
