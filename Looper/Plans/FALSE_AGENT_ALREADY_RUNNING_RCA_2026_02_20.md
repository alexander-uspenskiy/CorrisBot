# Root Cause Analysis: Ложный "Agent already running" на bootstrap

## 1. Короткий Root-Cause

**Основная причина (Primary Root-Cause): Кэширование аргументов в командной строке `wt.exe`.**
Механизм `test_agent_already_running` основан на чтении `CommandLine` процессов через WMI (`Win32_Process`). Когда оркестратор успешно запсукает первый таб воркера в Windows Terminal, процесс `wt.exe` стартует с аргументами вроде `wt.exe -w ... cmd.exe /c "CodexLoop.bat --project-root C:\ProjectA --agent-path Workers\Worker_001"`. 
Если этот воркер падает (или закрывается), но само окно терминала `wt.exe` остается жить (т.к. в нем открыты другие вкладки, например, Talker или Orchestrator), то операционная система **навсегда сохраняет исходную командную строку запуска `wt.exe`**. При попытке повторного запуска `StartLoopsInWT.py` видит строку `wt.exe...` с нужными путями и ошибочно решает, что агент всё еще жив, хотя фактический дочерний процесс (`python.exe` воркера) давно умер.

**Вторичная причина (Secondary Root-Cause): Эвристический поиск подстрок.**
Функция проверки использует `contains_path_token`, которая просто ищет "кусочки" путей в общей строке вызова без привязки к ключам (`--project-root`, `--agent-path`). Это создает коллизию раздельных root'ов: если Talker работает из `C:\_RUN_CorrisBot\Talker`, а Orchestrator из `C:\CorrisBot`, срабатывает ложное узнавание путей, так как строка `C:\CorrisBot` является подстрокой `C:\_RUN_CorrisBot`!

---

## 2. Доказательства (Воспроизведение и логи)

Для подтверждения была написана система скриптов. 
Если запросить процессы через:
```powershell
Get-CimInstance Win32_Process | Select-Object Name, CommandLine
```
Мы получаем результат:
```json
[
  {
    "Name": "wt.exe",
    "CommandLine": "wt.exe -w Default new-tab cmd.exe /c \"CodexLoop.bat --project-root C:\\CorrisBot --agent-path Workers\\Worker_001\""
  }
]
```
Так как в этой строке есть и `codexloop.bat`, и `C:\CorrisBot`, и `Workers\Worker_001`, фильтр `test_agent_already_running` сразу отвечает `True`, блокируя старт, полагаясь на "живой процесс", который на самом деле является просто окном GUI-терминала.

Вторичная уязвимость (смешение рутов) воспроизводится вот таким вызовом, в котором `StartLoopsInWT` также ложно блокирует старт:
```python
mock_cmd = r'python.exe codex_prompt_fileloop.py --project-root "C:\CorrisBot2" --agent-path "Workers\Worker_001"'
# При попытке запустить C:\CorrisBot\Workers\Worker_001
# `has_project` дает True, `has_agent_rel` дает True.
# Ложный Already Running!
```

---

## 3. Минимальный fail-closed фикс без эвристик (Предлагаемая стратегия)

Согласно требованию не лечить сразу, вот **план лечения**:

1. **Исключение Terminal Host:** Из результатов WMI-запроса `get_process_command_lines()` необходимо превентивно отбрасывать любые процессы с именами `wt.exe` и `WindowsTerminal.exe` (путем запроса поля `Name` наряду с `CommandLine`). Таким образом, stale-процесс терминала больше не будет блокировать старт.
2. **Точный парсинг аргументов:** Привести поиск к "жесткому" контракту (fail-closed). Написать функцию `extract_cmd_arg(cmdline, arg_name)`, которая честно вычленяет точное значение после флага `--project-root` и `--agent-path`, учитывая кавычки.
3. **Строгая валидация путей:** Заменить поиск через `has_project = contains_path_token(...)` на прямое сравнение строк (с нормализацией слешей):
   `if extracted_project == project_norm and extracted_agent == agent_rel_norm:`
4. **Отказ от эвристик:** Удалить `contains_path_token` полностью.

Такой подход гарантирует запуск, если физически убит дочерний скрипт, и 100% страхует от совпадений имен папок у других проектов.
