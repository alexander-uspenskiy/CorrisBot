# Session Handoff (2026-02-17): Reply-To, Prompt Routing, Kimi/Looper Incident

## 1) Контекст сессии

Целью было ужесточить и формализовать инструкции AGENTS/template-цепочки для мультиагентной коммуникации (Talker <-> Orchestrator <-> Workers), без регрессии рабочего поведения Codex.

Отдельно разбирался инцидент от **2026-02-17**: Talker не переслал сообщение от оркестратора, хотя файл появился в `Talker/Prompts/Inbox/Orc_.CorrisBot_TestProject_6/`.

---

## 2) Ключевой инцидент и root cause

### Симптом

- Файл был создан:  
  `Talker/Prompts/Inbox/Orc_.CorrisBot_TestProject_6/Prompt_2026_02_17_15_55_000.md`
- Но Talker его не обработал и не переслал пользователю.

### Фактическая причина

- Looper отбрасывает файл как невалидный marker:
  - в формате отсутствует блок `SS` (секунды);
  - фактически marker: `2026_02_17_15_55_000` (6 сегментов), а ожидается `YYYY_MM_DD_HH_MM_SS_mmm` (7 сегментов).
- Подтверждение в логах:
  - `Talker/Prompts/Inbox/Console.log`:
    - warning: `Skipping prompt with invalid timestamp format ... Prompt_2026_02_17_15_55_000.md`

### Важный вывод

- Проблема была **не** в том, что watcher смотрит только `tg_corriscant`.
- Причина: невалидное имя prompt-файла.
- Невалидное имя было создано **LLM tool call (WriteFile)**, а не централизованным marker-генератором скриптов.

---

## 3) Что изменено в этой сессии

### 3.1 Ужесточение Reply-To контракта

Обновлены шаблоны/роли:

- `Looper/ROLE_LOOPER_BASE.md`
- `Looper/SKILL_GATEWAY_IO.md`
- `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
- `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`

Основное:

- формализован валидный `Reply-To` блок;
- зафиксированы шаги маршрутизации (extract -> ensure/create inbox -> write -> verify);
- добавлены anti-false-routing ограничения;
- учтён `relay`-исключительный кейс Talker.

### 3.2 Переход на script-only создание Prompt файлов

Добавлен helper-скрипт:

- `Looper/create_prompt_file.py`

Идея:

- больше не собирать имя `Prompt_*.md` вручную в tool вызовах (`WriteFile`, `echo >`, etc.);
- создавать prompt только через helper:
  - `py "C:\CorrisBot\Looper\create_prompt_file.py" create --inbox "<InboxPath>" --from-file "<LocalReportFile.md>"`

Правила синхронизированы в:

- `Looper/ROLE_LOOPER_BASE.md`
- `Looper/SKILL_GATEWAY_IO.md`
- `Looper/SKILL_AGENT_RUNNER.md`
- `Talker/ROLE_TALKER.md`
- `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
- `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`

Дополнительно:

- в `Looper/codex_prompt_fileloop.py` в injected loop rules добавлена явная инструкция использовать helper и не handcraft filename.

### 3.3 Исправление бага helper-скрипта (коллизии + suffix)

После CR найден и исправлен баг в `create_prompt_file.py`:

- retry при `--suffix` мог всегда падать из-за regex-несовместимого marker;
- исправлена логика построения retry-marker при suffix.

### 3.4 Согласование архитектуры `FilePattern`

По коду подтверждено: архитектура использует фиксированный pattern (`Prompt_...` и `Prompt_..._Result`).

Поэтому правила приведены к факту:

- поддерживается только стандартный `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md` (опц. alnum suffix);
- при несовпадении `Reply-To.FilePattern` -> `unsupported FilePattern` и остановка.

---

## 4) Коммиты сессии

1. `5d0bb6e`  
   `Harden Reply-To routing contract across looper templates`

2. `0ede458`  
   `Enforce script-only prompt creation and align Reply-To pattern rules`

---

## 5) Что проверено

- Сборка AGENTS из template:
  - Talker
  - Orchestrator (template)
  - Worker (template)
- `py -m py_compile`:
  - `Looper/create_prompt_file.py`
  - `Looper/codex_prompt_fileloop.py`
- Smoke test helper-скрипта:
  - успешное создание `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`
  - проверка retry/коллизий (включая suffix)

---

## 6) Остаточные риски / незакрытое

1. Защита пока в основном policy-level.
   - Есть helper + инструкции + injected rules.
   - Но нет полного hard runtime-interceptor, который бы блокировал `WriteFile` с handcraft `Prompt_*.md`.

2. Исторические уже созданные проекты/агенты могут иметь старые `AGENTS.md`.
   - Template обновлены, но существующие инстансы нужно пересобрать/обновить отдельно.

3. Не выполнен полноценный e2e прогон живой цепочки:
   - `Talker -> Orchestrator(Kimi) -> Talker -> Gateway`.

---

## 7) Рекомендуемое продолжение в следующей сессии

1. Добавить runtime guard в `Looper/codex_prompt_fileloop.py`:
   - детектить попытки ручного создания `Prompt_*.md`;
   - логировать/фейлить turn с явной ошибкой протокола.

2. Сделать utility для массовой пересборки AGENTS в уже существующих проектах.

3. Провести e2e сценарий на реальном проекте:
   - проверить доставку ответов через `Reply-To`;
   - отдельно протестировать кейс с неверным именем prompt и expected error path.

4. (Опционально) Добавить unit-тесты на marker/regex и helper allocation.

---

## 8) Быстрые ссылки на ключевые файлы

- `Looper/create_prompt_file.py`
- `Looper/codex_prompt_fileloop.py`
- `Looper/ROLE_LOOPER_BASE.md`
- `Looper/SKILL_GATEWAY_IO.md`
- `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
- `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`
- `Talker/ROLE_TALKER.md`
- `Talker/Prompts/Inbox/Console.log`
- `Talker/Prompts/Inbox/Orc_.CorrisBot_TestProject_6/Prompt_2026_02_17_15_55_000.md`

