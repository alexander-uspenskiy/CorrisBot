# Полный план миграции на portable paths

Дата: 2026-02-18  
Репозиторий: `C:\CorrisBot`  
Режим выполнения: **только полный перевод**, без partial rollout.

## 1) Назначение документа
Этот документ самодостаточен для запуска работ в новом чате без дополнительного контекста.

Цель:
- убрать рабочую зависимость от `C:\CorrisBot`;
- перевести runtime и source-инструкции LLM на portable модель путей;
- сохранить текущую архитектуру и поведение.

## 2) Что считать \"готово\"
Done достигается только если одновременно выполнены все пункты:
1. Критичные runtime-файлы больше не содержат hardcoded `C:\CorrisBot`.
2. Source-цепочка сборки AGENTS (`AGENTS_TEMPLATE/ROLE/SKILL`) не опирается на `C:\CorrisBot`.
3. `assemble_agents.py` корректно резолвит относительные `Read:` от текущего файла-источника.
4. `AGENTS.md` пересобраны из обновленных source-файлов.
5. E2E smoke в копии репозитория, расположенной вне `C:\CorrisBot`, успешен.

## 3) Область изменений
Изменять:
1. `Looper/CreateProjectStructure.bat`
2. `Looper/CreateWorkerStructure.bat`
3. `Looper/CodexLoop.bat`
4. `Looper/KimiLoop.bat`
5. `Gateways/Telegram/run_gateway.bat`
6. `Gateways/Telegram/tg_codex_gateway.py`
7. `Looper/assemble_agents.py`
8. `Talker/AGENTS_TEMPLATE.md`
9. `ProjectFolder_Template/Orchestrator/AGENTS_TEMPLATE.md`
10. `ProjectFolder_Template/Workers/Worker_001/AGENTS_TEMPLATE.md`
11. `Talker/ROLE_TALKER.md`
12. `Talker/SKILL_TALKER.md`
13. `Looper/ROLE_LOOPER_BASE.md`
14. `Looper/SKILL_AGENT_RUNNER.md`
15. `Looper/SKILL_GATEWAY_IO.md`
16. `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
17. `Looper/codex_prompt_fileloop.py`

Также обновить (обязательно в рамках full migration):
1. `Gateways/Telegram/AGENTS.md`
2. usage-примеры в `Looper/StartLoopsInWT.bat`, `Looper/CleanupPrompts.bat`, `Looper/create_prompt_file.py`

## 4) Целевая модель пути (единый контракт)
После миграции действуют инварианты:
1. Каждый launcher вычисляет свой root от пути скрипта (`%~dp0` / `Path(__file__)`).
2. Runtime использует единые переменные: `REPO_ROOT`, `LOOPER_ROOT`, `TALKER_ROOT`, `TEMPLATE_ROOT`.
3. Приоритет разрешения пути: explicit CLI arg -> env var -> computed default.
4. В source `Read:` допускаются относительные пути, резолв от каталога файла, где стоит `Read:`.
5. Generated `AGENTS.md` не редактируется вручную, только пересобирается.
6. Для LLM operational-команд используется единый контракт: путь к looper-скриптам берется из `LOOPER_ROOT` (не placeholder-only и не эвристики).

## 5) Обязательные CR и Anti-Hack Gates для исполнителей

### 5.1 CR-гейты (обязательно)
Выполнять CR до перехода к следующему этапу:
1. Gate A: после этапа 1.
2. Gate B: после этапов 2-3.
3. Gate C: после этапа 4.
4. Gate D: после этапа 6, перед финальным sign-off.

### 5.2 Формат CR-отчета (обязательно)
Для каждого gate фиксировать мини-отчет:
1. Findings first: `High -> Medium -> Low` с ссылками на файлы.
2. Open questions/assumptions.
3. Go/No-Go решение на следующий этап.

### 5.3 Stop-правила
1. Любой `High` = запрет перехода к следующему этапу до исправления.
2. `Medium` допускается только если есть явный mitigation + отдельный TODO в плане.
3. Нельзя коммитить этап без CR-результата по соответствующему gate.

### 5.4 Anti-Hack Gate (обязательно на каждом CR)
Перед каждым переходом задать и письменно ответить:
1. Это единая архитектурная модель путей или набор частных обходов?
2. Не добавлены ли fallback/эвристики, которые тихо возвращают в `C:\CorrisBot`?
3. Решение воспроизводимо в новой папке без ручных правок?
4. Не зависит ли решение от \"магического\" cwd/окружения, которое не гарантируется launcher-ом?

Если любой ответ отрицательный, этап возвращается в доработку до коммита.

## 6) Порядок выполнения с коммитами

### Этап 0. Подготовка и baseline
Цель: зафиксировать исходное состояние и контрольные проверки.

Сделать:
1. Создать ветку: `chore/portable-paths-2026-02-18`.
2. Снять baseline-поиск:
   - `rg -n -F "C:\\CorrisBot" --hidden --glob "!.git/" --glob "!Looper/Plans/**" --glob "!Gateways/Telegram/Plans/**"`
3. Зафиксировать baseline smoke (кратко в заметке).

Коммит:
1. Коммита нет (или служебный коммит с заметкой baseline по правилам команды).

Rollback:
1. Не требуется.

### Этап 1. Runtime hardcoded paths
Цель: убрать `C:\CorrisBot` из исполняемого запуска.

Сделать:
1. В `CreateProjectStructure.bat` вычислять `TEMPLATE_ROOT` от `SCRIPT_DIR`.
2. В `CreateWorkerStructure.bat` вычислять `SOURCE_ROOT` от `SCRIPT_DIR`.
3. В `CodexLoop.bat` и `KimiLoop.bat` заменить `cd /d C:\CorrisBot\Looper` на вычисление через `%~dp0`.
4. В `run_gateway.bat` вычислять `LOOPER_ROOT/TALKER_ROOT/WORKDIR` от местоположения bat (с возможностью env override).
5. В `tg_codex_gateway.py` заменить default `_LOOPER_ROOT` на вычисление от `__file__` (оставив env override).
6. Все launcher-скрипты должны экспортировать в дочерние процессы одинаковый набор env:
   - `REPO_ROOT`
   - `LOOPER_ROOT`
   - `TALKER_ROOT` (где применимо)

Проверки:
1. Dry-run/usage запуск каждого bat.
2. Проверка печати вычисленных root-путей.
3. Поиск `rg -n -F "C:\\CorrisBot"` по runtime-файлам должен оставить только не-критичные примеры/комментарии.
4. Из процесса лупера проверить наличие `LOOPER_ROOT` в environment.
5. Выполнить CR Gate A + Anti-Hack Gate.

Коммит:
1. `portable(runtime): replace hardcoded C:\CorrisBot with computed roots`

Rollback:
1. `git revert <commit_sha>`

### Этап 2. Сборщик AGENTS и relative Read
Цель: сделать сборку независимой от абсолютных `Read:`.

Сделать:
1. В `assemble_agents.py` изменить резолв:
   - если `Read:` абсолютный -> как есть;
   - если относительный -> `(current_file.parent / ref).resolve()`.
2. Сохранить проверки циклов и ошибок.

Проверки:
1. Тестовая сборка `Talker/AGENTS_TEMPLATE.md -> Talker/AGENTS.md`.
2. Тестовая сборка шаблонов проекта/worker.
3. Убедиться, что сборка не зависит от текущего `cwd`.

Коммит:
1. `portable(agents): resolve relative Read links from source file directory`

Rollback:
1. `git revert <commit_sha>`

### Этап 3. Миграция source Read-цепочки
Цель: убрать абсолютные `Read:` из source-файлов.

Сделать:
1. Обновить `AGENTS_TEMPLATE.md` для Talker/Orchestrator/Worker на относительные `Read:`.
2. Обновить вложенные `Read:` в:
   - `Talker/ROLE_TALKER.md`
   - `Talker/SKILL_TALKER.md`
   - `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
3. Проверить, что весь `Read:` граф разрешим после изменений.

Проверки:
1. Пересборка `AGENTS.md`.
2. Проверка, что в source `Read:` больше нет `C:\CorrisBot`.
3. Выполнить CR Gate B + Anti-Hack Gate.

Коммит:
1. `portable(agents-source): migrate Read chains to relative links`

Rollback:
1. `git revert <commit_sha>`

### Этап 4. Миграция команд в ROLE/SKILL и runtime prompt injection
Цель: убрать hardcoded `C:\CorrisBot` из operational инструкций модели.

Сделать:
1. Переписать команды в:
   - `Talker/ROLE_TALKER.md`
   - `Looper/ROLE_LOOPER_BASE.md`
   - `Looper/SKILL_AGENT_RUNNER.md`
   - `Looper/SKILL_GATEWAY_IO.md`
2. Обновить строку-инъекцию в `Looper/codex_prompt_fileloop.py: build_loop_prompt`.
3. Использовать единый (не смешанный) portable-контракт:
   - путь к `create_prompt_file.py` и другим looper-скриптам берется через `LOOPER_ROOT`.
4. В инструкциях дать явные команды для двух shell-форм:
   - PowerShell: `$env:LOOPER_ROOT`
   - cmd: `%LOOPER_ROOT%`
5. Не использовать placeholder-only записи без механизма резолва.

Проверки:
1. Пересобрать `Talker/AGENTS.md`.
2. Проверить, что в generated AGENTS нет operational команд с `C:\CorrisBot`.
3. Проверить, что команды в ROLE/SKILL выполнимы и в PowerShell, и в cmd.
4. Выполнить CR Gate C + Anti-Hack Gate.

Коммит:
1. `portable(llm): remove hardcoded C:\CorrisBot from ROLE/SKILL and injected rules`

Rollback:
1. `git revert <commit_sha>`

### Этап 5. Пересборка generated AGENTS и финальная зачистка
Цель: синхронизировать generated артефакты с source.

Сделать:
1. Пересобрать:
   - `Talker/AGENTS.md`
   - при необходимости тестовые сборки шаблонов проекта/worker.
2. Обновить документационные usage-примеры, чтобы не оставалось `C:\CorrisBot` (кроме `Plans/**`).

Проверки:
1. `rg -n -F "C:\\CorrisBot" --hidden --glob "!.git/" --glob "!Looper/Plans/**" --glob "!Gateways/Telegram/Plans/**"`
2. Разрешены только явно согласованные остатки (например, исторические комментарии, если оставлены осознанно).

Коммит:
1. `portable(rebuild): regenerate AGENTS and normalize docs/examples`

Rollback:
1. `git revert <commit_sha>`

### Этап 6. E2E проверка в новой директории
Цель: доказать portability фактическим запуском не из `C:\CorrisBot`.

Сделать:
1. Скопировать/клонировать репозиторий в другой путь (например `D:\Work\CorrisBot_Portable_Test`).
2. Запустить gateway+talker из новой папки.
3. Прогнать сценарий:
   - пользовательское сообщение;
   - создание проекта;
   - запуск оркестратора;
   - обратный ответ через Talker.

Проверки:
1. В логах запусков пути указывают новую папку.
2. Нет обращений к `C:\CorrisBot`.
3. Relay/Reply-To цепочка работает без регрессий.
4. Выполнить CR Gate D + Anti-Hack Gate.

Коммит:
1. Кодового коммита может не быть.
2. При необходимости добавить короткий report-файл в `Looper/Plans`.

Rollback:
1. Если регрессия, поочередно откатывать коммиты этапов 5 -> 4 -> 3 -> 2 -> 1.

## 7) Контрольные команды (чек-лист)
1. Поиск абсолютных путей:
```powershell
rg -n -F "C:\CorrisBot" --hidden --glob "!.git/" --glob "!Looper/Plans/**" --glob "!Gateways/Telegram/Plans/**"
```
2. Пересборка AGENTS:
```powershell
py Looper/assemble_agents.py Talker/AGENTS_TEMPLATE.md Talker/AGENTS.md
py Looper/assemble_agents.py ProjectFolder_Template/Orchestrator/AGENTS_TEMPLATE.md ProjectFolder_Template/Orchestrator/test_agents.md
py Looper/assemble_agents.py ProjectFolder_Template/Workers/Worker_001/AGENTS_TEMPLATE.md ProjectFolder_Template/Workers/Worker_001/test_agents.md
```
3. Быстрые dry-run запуски:
```powershell
Looper\StartLoopsInWT.bat "C:\Temp\PortableTestProject" "Orchestrator" --dry-run
Gateways\Telegram\run_gateway.bat
```
Примечание: `run_gateway.bat` запускает реальные процессы; выполнять только в тестовом окружении.

## 8) Правила коммитов для безопасного отката
1. Один этап = один атомарный коммит.
2. Перед каждым коммитом запускать минимум локальные проверки этапа.
3. Не смешивать runtime, assembler и ROLE/SKILL в одном коммите.
4. После каждого коммита обновлять короткий progress-log в `Looper/Plans` (опционально).
5. Коммит без CR-gate отчета для этапа запрещен.

## 9) Готовый блок для нового чата
Использовать этот блок как первый prompt в новом чате:

```text
Task: execute full portability migration plan from
Looper/Plans/PORTABILITY_MIGRATION_EXECUTION_PLAN_2026_02_18.md

Hard constraints:
1) No partial rollout. Only full migration across runtime + AGENTS source chain.
2) Work strictly phase-by-phase with intermediate commits (one phase = one commit).
3) Keep rollback safety: after each phase run listed checks before commit.
4) Do not edit generated AGENTS.md manually; edit sources and rebuild.
5) Final proof must include E2E run from repo path different from C:\CorrisBot.
6) Mandatory CR gates: A(after stage1), B(after stage2-3), C(after stage4), D(before final E2E sign-off).
7) Anti-hack check is mandatory at each gate; no heuristic/fallback path logic allowed.

Deliverables:
1) code changes by phases with commit SHAs,
2) verification results per phase,
3) CR gate reports (A/B/C/D) with findings-first format,
4) final residual grep report for C:\CorrisBot outside excluded plans.
```

## 10) Итог
План рассчитан на полную миграцию без контекстной зависимости и с безопасной обратимостью через поэтапные коммиты/rollback.
