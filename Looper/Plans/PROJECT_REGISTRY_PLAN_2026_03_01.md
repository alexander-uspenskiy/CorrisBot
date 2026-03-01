# План реализации: Project Registry для Talker-Агностика

**Дата:** 2026-03-01  
**Статус:** Готов к реализации  
**Платформа:** CorrisBot (`C:\CorrisBot`)

---

## Цель

Дать Talker внешнюю память о проектах (Project Registry) и упростить интерфейс handoff-скрипта до минимального набора параметров.

**Принцип:** Talker остаётся агностиком — он не привязан ни к какому проекту. Registry — это его «записная книжка», а не конфиг.  
**Обратная совместимость:** Не нужна. Старый интерфейс заменяется полностью. Legacy остаётся в git.

---

## Контекст проблемы

Talker обслуживает N проектов одновременно. Сейчас единственная «память» о проектах — контекст LLM-сессии.  
При handoff к оркестратору скрипт `send_orchestrator_handoff.py` требует от LLM вручную передать 4 обязательных параметра (`--app-root`, `--edit-root`, `--route-session-id`, `--project-root`), которых нет в быстром доступе. LLM вынужден «домысливать» значения, что нарушает fail-closed архитектуру.

**Корневая причина:** отсутствие персистентного реестра проектов + перегруженный интерфейс helper-скрипта.

**Связанный инцидент:** `C:\Temp\Unfuddle\uniproject.epweventsprog.20260204064808\Plans\INVESTIGATION_TALKER_ROUTING_CONTRACT_MISSING_2026_02_25.md`  
**Связанная архитектура:** `C:\CorrisBot\Looper\Plans\ROUTING_IDENTITY_FAIL_CLOSED_PLAN_2026_02_20.md`

---

## Структура проекта (для ориентации)

```
C:\CorrisBot\                          ← APP_ROOT (платформа)
├── Looper\                            ← LOOPER_ROOT (скрипты)
│   ├── send_orchestrator_handoff.py   ← модифицируется
│   ├── CreateProjectStructure.bat     ← модифицируется
│   ├── project_registry.py            ← НОВЫЙ ФАЙЛ
│   ├── route_contract_utils.py        ← не меняется
│   ├── codex_prompt_fileloop.py       ← не меняется
│   ├── create_prompt_file.py          ← не меняется
│   ├── send_reply_to_report.py        ← не меняется
│   ├── assemble_agents.py             ← не меняется (только вызывается)
│   ├── StartLoopsInWT.bat / .py       ← не меняется
│   └── CodexLoop.bat / KimiLoop.bat   ← не меняется
├── Talker\
│   ├── ROLE_TALKER.md                 ← модифицируется
│   ├── AGENTS.md                      ← пересобирается (через assemble_agents.py)
│   ├── AGENTS_TEMPLATE.md             ← не меняется
│   ├── Prompts\Inbox\routing_state.json  ← не меняется
│   └── Temp\
│       └── project_registry.json      ← НОВЫЙ ФАЙЛ (создаётся автоматически)
└── ProjectFolder_Template\            ← не меняется
```

---

## Требования к кодировке

- При модификации всех файлов — сохранять исходную кодировку и line endings.  
- `ROLE_TALKER.md` — UTF-8, CRLF.  
- `CreateProjectStructure.bat` — UTF-8, CRLF/LF mix (сохранять как есть).  
- Новые файлы `.py` — UTF-8, LF (как остальные `.py` в `Looper/`).  
- Новый `project_registry.json` — UTF-8, LF (запись через Python).

---

## Изменение 1: Новый файл `Looper/project_registry.py`

Модуль + CLI-утилита для управления реестром проектов.

### Расположение registry-файла

```
Talker/Temp/project_registry.json
```

### Как определять пути (внутри модуля)

```python
def derive_talker_root() -> Path:
    """
    1. Переменная окружения TALKER_ROOT (если задана и непуста)
    2. Иначе: Path(__file__).resolve().parent.parent / "Talker"
    """

def derive_app_root() -> Path:
    """Parent директории скрипта: Path(__file__).resolve().parent.parent
    Looper/../ == C:\CorrisBot"""
```

### Формат файла `project_registry.json`

```json
{
  "version": 1,
  "projects": {
    "<ProjectTag>": {
      "project_root": "<абсолютный путь к orchestration workspace>",
      "edit_root": "<абсолютный путь к code repository, пустая строка если ещё не задан>",
      "route_session_id": "<идентификатор текущей сессии, пустая строка если ещё не было handoff>",
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>"
    }
  }
}
```

`ProjectTag` = имя конечной папки `project_root` (определяется как `Path(project_root).name`).

### Функции модуля (публичный API)

```python
def read_registry(talker_root: Path) -> dict:
    """Прочитать registry. Если файла нет — вернуть пустую структуру
    {"version": 1, "projects": {}}."""

def write_registry(talker_root: Path, data: dict) -> None:
    """Атомарная запись (tmp + rename). Создать Talker/Temp/ если не существует."""

def sanitize_for_session_id(raw: str) -> str:
    """Заменить символы, не входящие в SAFE_TOKEN_RE [A-Za-z0-9._:-],
    на '_'. Используется для безопасного включения project_tag в session_id."""

def generate_session_id(project_tag: str) -> str:
    """Сгенерировать новый route_session_id в формате:
    s-<sanitized_project_tag>-<YYYYMMDD>-<HHMMSS>-<random4hex>
    Результат должен проходить SAFE_TOKEN_RE из route_contract_utils.
    Использовать sanitize_for_session_id для обработки project_tag."""

def register_project(talker_root: Path, project_root: str, edit_root: str = "") -> dict:
    """Зарегистрировать новый проект. project_tag = Path(project_root).name.
    
    Поведение при совпадении тега:
    - Если тег уже есть и project_root совпадает — обновить edit_root
      (если передан непустой), updated_at. Тихая идемпотентная операция.
    - Если тег уже есть и project_root ОТЛИЧАЕТСЯ — вывести предупреждение
      в stderr ('warning: project tag <tag> was registered with different 
      project_root, overwriting'), обновить запись.

    Вернуть запись проекта."""

def update_project(talker_root: Path, project_tag: str, **fields) -> dict:
    """Обновить конкретные поля существующего проекта.
    Допустимые поля для обновления: edit_root, route_session_id.
    Всегда обновлять updated_at.
    Вернуть обновлённую запись. Если проект не найден — RuntimeError."""

def lookup_project(talker_root: Path, project_tag: str) -> dict:
    """Найти проект по тегу. Если не найден — RuntimeError с текстом
    'project not registered: <tag>. Use CreateProjectStructure to create it.'"""

def remove_project(talker_root: Path, project_tag: str) -> None:
    """Удалить проект из registry по тегу. Если не найден — RuntimeError."""

def list_projects(talker_root: Path) -> dict:
    """Вернуть весь словарь projects из registry."""
```

### CLI-интерфейс (subcommands)

```
py project_registry.py register --project-root <path> [--edit-root <path>]
py project_registry.py update --project-tag <tag> [--edit-root <path>] [--route-session-id <id>]
py project_registry.py lookup --project-tag <tag>
py project_registry.py list
py project_registry.py remove --project-tag <tag>
```

Успех: exit code 0, вывод в JSON (stdout).  
Ошибка: exit code 2, сообщение в stderr.  
Предупреждения: в stderr (не в stdout, чтобы не ломать JSON-парсинг).

---

## Изменение 2: Модификация `Looper/CreateProjectStructure.bat`

Добавить в конец файла, **перед** финальным `echo Project structure ensured...` (перед текущей строкой 107):

```bat
py "%LOOPER_ROOT%\project_registry.py" register --project-root "%DEST_PROJECT_ROOT%"
if errorlevel 1 (
  echo [warning] Failed to register project in Talker registry. Registration can be done manually later.
)
```

При ошибке регистрации **не блокировать** создание проекта (не делать `exit /b`). Регистрация — мягкий пост-шаг. Вывести предупреждение и продолжить к финальному `echo` и `exit /b 0`.

---

## Изменение 3: Модификация `Looper/send_orchestrator_handoff.py`

### Новый интерфейс CLI

Обязательные параметры:
```
--project-tag <string>        Тег проекта (ключ в registry)
--user-message-file <path>    Файл с текстом пользователя
```

Опциональные параметры (оставить):
```
--edit-root <path>            Задать/обновить edit_root в registry и использовать его
--new-session                 Принудительно сгенерировать новый route_session_id
--include-reply-to            Включить Reply-To блок (рекомендуется для первого prompt)
--omit-reply-to               Не включать Reply-To блок
--suffix <string>             Суффикс для create_prompt_file.py (alnum only)
--scope <string>              Текст scope для Reply-To
--created-at-utc <string>     Timestamp для контракта (default: текущее UTC)
--sender-id <string>          SenderID для Reply-To (default: Orc_<ProjectTag>)
--local-handoff-file <path>   Выходной путь для handoff markdown
--routing-contract-file <path> Выходной путь для routing contract JSON
```

Удалённые параметры (всё вычисляется автоматически):
```
--project-root       → из registry по project-tag
--app-root           → из derive_app_root()
--agents-root        → совпадает с project-root (убрать совсем)
--route-session-id   → из registry, или автогенерация при первом handoff / --new-session
--talker-root        → из derive_talker_root()
```

### Удалить мёртвый код

Функцию `_derive_project_tag(project_root)` (текущие строки 58-59) **удалить** — `project_tag` теперь приходит из CLI напрямую.

Функцию `_resolve_agents_root(args)` (текущие строки 67-76) **удалить** — `agents_root` всегда равен `project_root` из registry, параметр `--agents-root` убран.

### Логика main()

```
1. Импортировать из project_registry: derive_talker_root, derive_app_root, 
   lookup_project, update_project, generate_session_id
2. talker_root = derive_talker_root()
3. app_root = derive_app_root()
4. project = lookup_project(talker_root, args.project_tag)
   → fail-closed если проект не зарегистрирован
5. project_root = ensure_abs_path("project-root", project["project_root"])
   → проверить что каталог существует, иначе FileNotFoundError
6. agents_root = project_root
7. edit_root:
   a. Если передан --edit-root → использовать и обновить в registry через update_project()
   b. Иначе → взять из project["edit_root"]
   c. Если пустой → fail-closed: 
      "edit_root not set for project <tag>. Pass --edit-root or register it via: 
      py project_registry.py update --project-tag <tag> --edit-root <path>"
   d. Валидация: ensure_abs_path("edit-root", edit_root)
8. route_session_id:
   a. Если --new-session → сгенерировать через generate_session_id(), сохранить в registry
   b. Иначе → взять из project["route_session_id"]
   c. Если пустой (первый handoff) → сгенерировать через generate_session_id(), сохранить в registry
   d. Валидация: ensure_safe_token("route-session-id", route_session_id)
9. talker_root validation: must == (app_root / "Talker").resolve(), must exist
10. project_tag = args.project_tag  (используется напрямую, без derive)
11. Далее — существующая логика (без изменений):
    - compute sender_id (default Orc_<ProjectTag>)
    - compute created_at_utc
    - compute include_reply_to
    - compute reply_to_inbox, orchestrator_inbox
    - ensure_path_in_root validations
    - mkdir orchestrator_inbox, reply_to_inbox
    - build routing_contract dict
    - write routing_contract JSON via _write_json()
    - build handoff content via _build_handoff_content()
    - write handoff file via _write_text()
    - deliver via _run_create_prompt()
    - verify delivery (file exists, correct inbox, correct filename)
    - output JSON result
```

### Что НЕ меняется в этом файле

- `_build_handoff_content()` — формат Routing-Contract в markdown (Version: 1)
- `_run_create_prompt()` — вызов create_prompt_file.py
- `_read_text_file()` — чтение файлов с BOM-detection
- `_write_text()`, `_write_json()` — запись файлов
- `_contract_filename()` — именование файла контракта
- Валидации из `route_contract_utils.py` — `ensure_abs_path`, `ensure_path_in_root`, `ensure_safe_token`
- Формат выходного JSON — те же поля
- Константы `DEFAULT_SCOPE`, `PROMPT_FILENAME_RE`

---

## Изменение 4: Модификация `Talker/ROLE_TALKER.md`

### Секция "Project Lifecycle Responsibility" (текущие строки 17-20)

Заменить на:

```markdown
## Project Lifecycle Responsibility (Talker Itself)
- For larger workloads, Talker helps the user create full project workspaces.
- При создании проекта через `CreateProjectStructure.bat` он автоматически регистрируется в `Talker/Temp/project_registry.json`.
- Реестр проектов — это внешняя память Talker о созданных проектах (тег, путь, edit_root).
- Если пользователь указал репозиторий (edit_root) при создании проекта — сразу зарегистрируй его:
  `py "$env:LOOPER_ROOT\project_registry.py" update --project-tag "<TAG>" --edit-root "<PATH>"`
- Talker может посмотреть список проектов: `py "$env:LOOPER_ROOT\project_registry.py" list`
- Talker может удалить проект из реестра: `py "$env:LOOPER_ROOT\project_registry.py" remove --project-tag "<TAG>"`
- Talker should help the user continue work in an existing project when the user refers to it.
```

### Секция "RUN ORCHESTRATOR" (текущие строки 89-122)

Заменить строки 89-122 на:

```markdown
## RUN ORCHESTRATOR

- После создания нового проекта — запускать оркестратор для него.
- Для запуска оркестратора использовать `StartLoopsInWT.bat` через `LOOPER_ROOT`:
  - PowerShell: `& "$env:LOOPER_ROOT\StartLoopsInWT.bat" "<PROJECT_ROOT_PATH>" "Orchestrator"`
  - cmd: `"%LOOPER_ROOT%\StartLoopsInWT.bat" "<PROJECT_ROOT_PATH>" "Orchestrator"`
- `<PROJECT_ROOT_PATH>` — это корневой каталог проекта (например `C:\Temp\.TestProject`).
- Если пользователь просит запустить оркестратор — запускать запрошенный. Подразумевается, что структура уже создана.
  Может быть в свободной форме, например "Вернемся к нашему проекту" — по контексту понимай о каком речь, и если проект уже дошёл до стадии оркестратора — запускай.
- Передача задач оркестратору делается через единый deterministic helper:
  - скрипт: `send_orchestrator_handoff.py` (в каталоге `LOOPER_ROOT`)
  - скрипт получает данные проекта из реестра `Talker/Temp/project_registry.json` по тегу
  - перед запуском сохрани исходный текст пользователя в локальный файл (`<LocalUserMessageFile.md>`) без переформулировки
  - первый prompt в проектной сессии (включить Reply-To):
    - PowerShell: `py "$env:LOOPER_ROOT\send_orchestrator_handoff.py" --project-tag "<PROJECT_TAG>" --user-message-file "<LocalUserMessageFile.md>" --include-reply-to`
    - cmd: `py "%LOOPER_ROOT%\send_orchestrator_handoff.py" --project-tag "<PROJECT_TAG>" --user-message-file "<LocalUserMessageFile.md>" --include-reply-to`
  - последующие prompt в той же проектной сессии:
    - PowerShell: `py "$env:LOOPER_ROOT\send_orchestrator_handoff.py" --project-tag "<PROJECT_TAG>" --user-message-file "<LocalUserMessageFile.md>" --omit-reply-to`
    - cmd: `py "%LOOPER_ROOT%\send_orchestrator_handoff.py" --project-tag "<PROJECT_TAG>" --user-message-file "<LocalUserMessageFile.md>" --omit-reply-to`
  - если edit_root ещё не задан для проекта, добавь `--edit-root "<EDIT_ROOT>"` при первом handoff
  - для принудительного начала новой маршрутной сессии используй флаг `--new-session`
  - при успехе скрипт возвращает JSON с `delivered_file` и `routing_contract_file`; используй эти поля как источник истины для подтверждения отправки.
- `ProjectTag` определяй из registry (команда `list`) или как имя конечного каталога `<PROJECT_ROOT_PATH>`.
- Для выбранного проекта используй один и тот же `ProjectTag` во всех дальнейших сообщениях.
- В ПЕРВОМ prompt к оркестратору по выбранному проекту обязательно используй `--include-reply-to`.
  - Этот блок обязателен для первого сообщения в проектной сессии и при явной смене маршрута.
  - Если маршрут не менялся, используй `--omit-reply-to` и не дублируй Reply-To в каждом следующем prompt.
  - `Route-Meta` и `Routing-Contract` считаются обязательными для всей цепочки проектной сессии (`RouteSessionID` должен оставаться неизменным).
```

Строки 123-177 (VERBATIM handoff contract, relay rules, routing commands) — **оставить без изменений**.

---

## Изменение 5: Пересборка `Talker/AGENTS.md`

После правки `ROLE_TALKER.md` выполнить:

```powershell
py "C:\CorrisBot\Looper\assemble_agents.py" "C:\CorrisBot\Talker\AGENTS_TEMPLATE.md" "C:\CorrisBot\Talker\AGENTS.md"
```

Верифицировать:
- В пересобранном `AGENTS.md` присутствуют новые инструкции из ROLE_TALKER.md
- В `AGENTS.md` НЕТ упоминаний `--app-root`, `--project-root`, `--route-session-id` в секции RUN ORCHESTRATOR

---

## Порядок реализации

| Шаг | Файл | Действие |
|-----|-------|----------|
| 1 | `Looper/project_registry.py` | Создать новый модуль (functions + CLI) |
| 2 | Ручная проверка шага 1 | Прогнать CLI-команды из чек-листа (registry) |
| 3 | `Looper/CreateProjectStructure.bat` | Добавить вызов `register` в конец |
| 4 | `Looper/send_orchestrator_handoff.py` | Переписать CLI-интерфейс и main(), удалить мёртвый код |
| 5 | `Talker/ROLE_TALKER.md` | Обновить секции Project Lifecycle и RUN ORCHESTRATOR |
| 6 | `Talker/AGENTS.md` | Пересобрать через `assemble_agents.py` |
| 7 | Тесты handoff | Проверить handoff-сценарии из чек-листа |

---

## Fail-Closed сценарии

| Ситуация | Поведение |
|----------|-----------|
| `--project-tag` не найден в registry | Ошибка: `project not registered: <tag>. Use CreateProjectStructure to create it.` |
| `project_root` из registry не существует на диске | Ошибка: `project root not found: <path>` |
| `edit_root` не задан (ни в registry, ни через `--edit-root`) | Ошибка: `edit_root not set for project <tag>. Pass --edit-root or register it via: py project_registry.py update --project-tag <tag> --edit-root <path>` |
| Registry-файл повреждён (невалидный JSON) | Ошибка: `project registry is corrupt: <path>` |
| `route_session_id` не проходит SAFE_TOKEN_RE | Ошибка (валидация из `route_contract_utils`) |
| Запись в registry при создании проекта не удалась | Предупреждение (не блокирует создание проекта) |

---

## Чек-лист тестирования

### Registry CLI (шаг 2)

- [ ] `project_registry.py register --project-root "C:\Temp\TestProj"` — создаёт registry, добавляет проект с пустым edit_root
- [ ] `project_registry.py register --project-root "C:\Temp\TestProj2" --edit-root "C:\Code\Repo"` — с edit_root
- [ ] `project_registry.py register --project-root "C:\Temp\TestProj"` повторно — идемпотентно, без ошибки
- [ ] `project_registry.py register --project-root "D:\Other\TestProj"` — предупреждение в stderr (тег совпадает, путь отличается), обновление записи
- [ ] `project_registry.py register --project-root "C:\Temp\.DotProject"` — тег с точкой в начале, проверить что session_id генерируется корректно
- [ ] `project_registry.py list` — выводит все проекты в JSON
- [ ] `project_registry.py lookup --project-tag "TestProj"` — находит проект, JSON
- [ ] `project_registry.py lookup --project-tag "Nonexistent"` — ошибка, exit code 2
- [ ] `project_registry.py update --project-tag "TestProj" --edit-root "C:\NewPath"` — обновляет edit_root
- [ ] `project_registry.py remove --project-tag "TestProj"` — удаляет запись
- [ ] `project_registry.py remove --project-tag "Nonexistent"` — ошибка, exit code 2

### CreateProjectStructure integration (шаг 3)

- [ ] `CreateProjectStructure.bat "C:\Temp\TestProj3"` — проект создан И зарегистрирован в registry
- [ ] `project_registry.py lookup --project-tag "TestProj3"` — подтверждает регистрацию

### Handoff (шаг 7)

- [ ] `send_orchestrator_handoff.py --project-tag "TestProj" --user-message-file msg.md --edit-root "C:\Code" --include-reply-to` — первый handoff: edit_root сохраняется в registry, session_id генерируется и сохраняется
- [ ] `send_orchestrator_handoff.py --project-tag "TestProj" --user-message-file msg.md --omit-reply-to` — повторный handoff: edit_root и session_id из registry
- [ ] `send_orchestrator_handoff.py --project-tag "Nonexistent" --user-message-file msg.md` — fail-closed
- [ ] `send_orchestrator_handoff.py --project-tag "TestProj" --user-message-file msg.md` без edit_root в registry — fail-closed с подсказкой
- [ ] `send_orchestrator_handoff.py --project-tag "TestProj" --user-message-file msg.md --new-session` — генерирует новый session_id, сохраняет в registry
- [ ] Формат выходного JSON — те же поля (status, route_session_id, project_tag, delivered_file и т.д.)
- [ ] Доставленный handoff-файл содержит валидные блоки Route-Meta и Routing-Contract

### ROLE и AGENTS (после шага 6)

- [ ] Пересобранный `Talker/AGENTS.md` содержит обновлённые инструкции из ROLE_TALKER.md
- [ ] В `AGENTS.md` нет упоминаний `--app-root`, `--project-root`, `--route-session-id` в секции RUN ORCHESTRATOR
- [ ] В `AGENTS.md` присутствует `--project-tag` в примерах вызова handoff

---

## Файлы, которые НЕ меняются

- `Looper/route_contract_utils.py` — валидация контракта, формат тот же
- `Looper/codex_prompt_fileloop.py` — loop-логика, формат промптов тот же
- `Looper/create_prompt_file.py` — создание prompt-файлов
- `Looper/send_reply_to_report.py` — обратный транспорт (Worker/Orc → Talker)
- `Looper/StartLoopsInWT.bat` + `StartLoopsInWT.py` — запуск лупера
- `Looper/CodexLoop.bat` / `KimiLoop.bat` — запуск лупера
- `Looper/ROLE_LOOPER_BASE.md` — базовые правила
- `Looper/assemble_agents.py` — сборщик (только вызывается в шаге 6)
- `Talker/Prompts/Inbox/routing_state.json` — хранит user_sender_id, не связан с проектами
- `Talker/AGENTS_TEMPLATE.md` — шаблон (ссылается на ROLE_TALKER.md через Read:)
- `Talker/SKILL_TALKER.md` — навык для других агентов
- `ProjectFolder_Template/*` — шаблон проекта
