# Задача: Интеграция assemble_agents.py в систему сборки

## Контекст

Скрипт `C:\CorrisBot\Looper\assemble_agents.py` уже создан и готов к использованию.
Он рекурсивно резолвит `Read:` ссылки в MD-файлах и собирает flat-файл.

```
Usage: py assemble_agents.py <template_path> <output_path>
```

Каждая строка вида `Read: \`C:\path\to\file.md\`` заменяется содержимым указанного файла (рекурсивно).

## Что нужно сделать

### 1. Переименовать 3 файла AGENTS.md → AGENTS_TEMPLATE.md

```bat
ren "C:\CorrisBot\Talker\AGENTS.md" "AGENTS_TEMPLATE.md"
ren "C:\CorrisBot\ProjectFolder_Template\Orchestrator\AGENTS.md" "AGENTS_TEMPLATE.md"
ren "C:\CorrisBot\ProjectFolder_Template\Executors\Executor_001\AGENTS.md" "AGENTS_TEMPLATE.md"
```

> **НЕ трогать** `C:\CorrisBot\Gateways\Telegram\AGENTS.md` — это документация протокола Gateway, не шаблон агента.

### 2. Модифицировать `C:\CorrisBot\Gateways\Telegram\run_gateway.bat`

Добавить вызов ассемблера **перед** строкой `:run_wt` (перед строкой 35):

```bat
echo [BOOT] Assembling Talker AGENTS.md ...
py "%LOOPER_ROOT%\assemble_agents.py" "%TALKER_ROOT%\AGENTS_TEMPLATE.md" "%TALKER_ROOT%\AGENTS.md"
if errorlevel 1 (
  echo [ERROR] Failed to assemble Talker AGENTS.md
  pause
  exit /b 1
)
```

### 3. Модифицировать `C:\CorrisBot\Looper\CreateProjectStructure.bat`

Строка 36 — цикл `for %%F in (AGENTS.md Info.md ROLE_ORCHESTRATOR.md)`:
- Убрать `AGENTS.md` из списка → `for %%F in (Info.md ROLE_ORCHESTRATOR.md)`
- После цикла (после строки 47) добавить:

```bat
if not exist "%DEST_ROOT%\Orchestrator\AGENTS.md" (
  py "%~dp0assemble_agents.py" "%TEMPLATE_ROOT%\Orchestrator\AGENTS_TEMPLATE.md" "%DEST_ROOT%\Orchestrator\AGENTS.md"
  if errorlevel 1 (
    echo Failed to assemble Orchestrator AGENTS.md
    exit /b 7
  )
)
```

### 4. Модифицировать `C:\CorrisBot\Looper\CreateExecutorStructure.bat`

Строка 62 — цикл `for %%F in (AGENTS.md Info.md ROLE_EXECUTOR.md)`:
- Убрать `AGENTS.md` из списка → `for %%F in (Info.md ROLE_EXECUTOR.md)`
- После цикла (после строки 73) добавить:

```bat
if not exist "%DEST_ROOT%\AGENTS.md" (
  py "%~dp0assemble_agents.py" "%SOURCE_ROOT%\AGENTS_TEMPLATE.md" "%DEST_ROOT%\AGENTS.md"
  if errorlevel 1 (
    echo Failed to assemble Executor AGENTS.md
    exit /b 8
  )
)
```

### 5. Первичная сборка AGENTS.md для Talker

После переименования (шаг 1), собрать актуальный flat-файл:

```bat
py "C:\CorrisBot\Looper\assemble_agents.py" "C:\CorrisBot\Talker\AGENTS_TEMPLATE.md" "C:\CorrisBot\Talker\AGENTS.md"
```

### 6. Верификация

1. Проверить, что `C:\CorrisBot\Talker\AGENTS.md` — flat-файл, **не содержит** строк `Read:`
2. То же для сборки Orchestrator:
   ```bat
   py "C:\CorrisBot\Looper\assemble_agents.py" "C:\CorrisBot\ProjectFolder_Template\Orchestrator\AGENTS_TEMPLATE.md" "C:\CorrisBot\ProjectFolder_Template\Orchestrator\test_agents.md"
   ```
   Проверить результат, удалить `test_agents.md`.
3. То же для Executor.

## Файлы, участвующие в сборке (Read-цепочка)

| Template | Read-ссылки внутри (рекурсивно) |
|---|---|
| `Talker/AGENTS_TEMPLATE.md` | `ROLE_LOOPER_BASE.md`, `ROLE_TALKER.md` → `SKILL_GATEWAY_IO.md`, `SKILL_AGENT_RUNNER.md` |
| `Orchestrator/AGENTS_TEMPLATE.md` | `ROLE_LOOPER_BASE.md`, `SKILL_TALKER.md` → `SKILL_GATEWAY_IO.md`, `ROLE_ORCHESTRATOR.md` → `SKILL_AGENT_RUNNER.md` |
| `Executor_001/AGENTS_TEMPLATE.md` | `ROLE_LOOPER_BASE.md`, `SKILL_TALKER.md` → `SKILL_GATEWAY_IO.md`, `ROLE_EXECUTOR.md` |
