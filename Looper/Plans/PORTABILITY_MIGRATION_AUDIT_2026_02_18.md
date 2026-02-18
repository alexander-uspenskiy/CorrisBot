# Аудит portability: отказ от абсолютных путей

Дата: 2026-02-18  
Репозиторий: `C:\CorrisBot`

## 1) Объем проверки и допущения
Проверены:
- runtime-скрипты и конфиги: `*.bat`, `*.py`, `*.json`, `*.toml`, `*.yaml`, `*.yml`
- инструкционный слой LLM: `AGENTS_TEMPLATE.md`, `ROLE_*.md`, `SKILL_*.md`, `AGENTS.md`
- исключены архивные/исторические планы: `Looper/Plans/**`, `Gateways/Telegram/Plans/**`

Поиск: `rg` по паттернам `C:\`, `C:\CorrisBot`, `X:\...`.

## 2) Коррекция оценки сложности
Текущая оценка после ревью: **средняя** (при условии, что миграция выполняется полностью, без partial rollout).

Когда сложность становится выше:
- если делать по частям;
- если оставить старые fallback-пути в runtime;
- если обновить скрипты, но не обновить source-файлы инструкций, из которых пересобирается `AGENTS.md`.

Важно:
- `Talker/AGENTS.md` действительно генерируемый артефакт; править его вручную не нужно.
- Но если source (`AGENTS_TEMPLATE/ROLE/SKILL`) содержит `C:\CorrisBot`, этот же путь попадет в новый сгенерированный `AGENTS.md`.

## 3) Что реально блокирует portability (критично)

### 3.1 Runtime hardcoded root
1. `Looper/CreateProjectStructure.bat:7`
- `set "TEMPLATE_ROOT=C:\CorrisBot\ProjectFolder_Template"`

2. `Looper/CreateWorkerStructure.bat:8`
- `set "SOURCE_ROOT=C:\CorrisBot\ProjectFolder_Template\Workers\Worker_001"`

3. `Looper/CodexLoop.bat:2`, `Looper/KimiLoop.bat:2`
- `cd /d C:\CorrisBot\Looper`

4. `Gateways/Telegram/run_gateway.bat:5-7`
- фиксированы `TALKER_ROOT`, `LOOPER_ROOT`, `WORKDIR` на `C:\CorrisBot\...`

5. `Gateways/Telegram/tg_codex_gateway.py:211`
- default `_LOOPER_ROOT = C:\CorrisBot\Looper`

Следствие: перенос в другую папку может запускать старое дерево или падать.

### 3.2 AGENTS source-chain c абсолютными `Read:`
1. `Talker/AGENTS_TEMPLATE.md:11,14`
2. `ProjectFolder_Template/Orchestrator/AGENTS_TEMPLATE.md:2,5,8`
3. `ProjectFolder_Template/Workers/Worker_001/AGENTS_TEMPLATE.md:2,5,8`

Следствие: source-пайплайн сборки привязан к фиксированному пути.

## 4) Что не блокирует запуск напрямую, но искажает поведение агентов

### 4.1 Абсолютные команды в ROLE/SKILL (source для сборки)
- `Talker/ROLE_TALKER.md`
- `Looper/ROLE_LOOPER_BASE.md:28`
- `Looper/SKILL_AGENT_RUNNER.md:12,21,70`
- `Looper/SKILL_GATEWAY_IO.md:33`
- `Talker/SKILL_TALKER.md:29`
- `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md:187`

Риск: после полной сборки `AGENTS.md` модель продолжает генерировать старые абсолютные команды.

### 4.2 Инъекция в runtime prompt
- `Looper/codex_prompt_fileloop.py:326` содержит абсолютный путь в тексте правил.

## 5) Низкий приоритет (документация/usage)
- `Gateways/Telegram/AGENTS.md`
- примеры usage в `StartLoopsInWT.bat`, `CleanupPrompts.bat`, `create_prompt_file.py`

Это не основной блокер, но лучше синхронизировать для чистоты и чтобы не закреплять старые шаблоны команд.

## 6) Что требуется для полного перевода

1. Ввести единый root-контракт запуска:
- вычисление корня от пути скрипта (`%~dp0` / `Path(__file__)`);
- runtime-переменные (`REPO_ROOT`, `LOOPER_ROOT`, `TALKER_ROOT`, `TEMPLATE_ROOT`);
- единый приоритет: CLI arg > env var > computed default.

2. Убрать hardcoded `C:\CorrisBot` из runtime-скриптов.

3. Перевести `Read:` в source-шаблонах на portable формат и доработать `assemble_agents.py`:
- относительные `Read:` должны резолвиться от каталога файла, в котором они записаны.

4. Обновить source-инструкции ROLE/SKILL (не generated output), затем пересобрать `AGENTS.md`.

5. Добавить контрольный gate:
- проверка `rg "C:\\CorrisBot"` (без `Plans/**`) должна давать 0 критичных попаданий.

## 7) Риски и минимизация

1. Риск: оставить runtime fallback на старое дерево.
- Мера: в startup-логах печатать итоговые `REPO_ROOT/LOOPER_ROOT/TALKER_ROOT`.

2. Риск: сломать сборку `Read:` при переходе на relative.
- Мера: сначала правка `assemble_agents.py`, потом миграция `Read:`.

3. Риск: рассинхрон между runtime и LLM source.
- Мера: выполнять полную миграцию в рамках одного плана с промежуточными коммитами и финальной E2E-проверкой.

## 8) Вывод
Если делать **полный перевод сразу по всем слоям** (runtime + source-инструкции + сборка AGENTS), задача технически прямолинейная и контролируемая.

Ключевая сложность не в \"строковой замене\" как таковой, а в том, чтобы не оставить ни одного рабочего пути, который уводит процесс обратно в `C:\CorrisBot`.
