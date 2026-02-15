# Задача для агента: расследование пунктов 4 и 5 (Orchestrator мог не прочитать инструкции)

## Цель
Разобрать инцидент из теста и дать доказательный ответ на два вопроса:
1. Читал ли Orchestrator свои инструкции (`AGENTS.md`/`ROLE_ORCHESTRATOR.md`) в момент работы.
2. Если не читал — почему (включая гипотезу неверного `cwd`/не того `AGENTS.md`).
3. Если читал — почему нарушил ключевые правила роли (в частности не создал Executor и сделал реализацию сам).

Важно: сначала расследование и причинно-следственная картина. Исправления кода в этой задаче не делать.

## Границы и контекст
- Репозиторий: `C:\CorrisBot`
- Инцидентный прогон: ночь 2026-02-15 (локально).
- Текущий статус проекта:
  - Пункт 2 уже закрыт (async delivery в gateway).
  - Пункт 7 уже закрыт (async-by-default в правилах).
  - Для расследования п.4/п.5 опирайся на артефакты **того прогона**, а не на текущее поведение после фиксов.

## Почему это важно
Пункты 4/5:
- Orchestrator «считал сам».
- Orchestrator «не создал ни одного лупера».

Обе аномалии похожи на сценарий, где роль Orchestrator не была применена (или применена частично/неверно).

## Артефакты (обязательные источники)
### 1) Talker-side лог прогона
- `C:\CorrisBot\Talker\Prompts\Inbox\tg_corriscant\Prompt_2026_02_15_01_53_53_590.md`
- `C:\CorrisBot\Talker\Prompts\Inbox\tg_corriscant\Prompt_2026_02_15_01_53_53_590_Result.md`

Что там важно:
- Talker отправил задачу в `C:\Temp\CorrisBot_TestProject_3\Orchestrator\Prompts\Inbox\Talker\Prompt_2026_02_15_01_54_40_865.md`
- Talker сам читал `...Orchestrator...Prompt_..._Result.md` и пересказывал его.

### 2) Snapshot проекта, где реально работал Orchestrator
- `C:\Temp\CorrisBot_TestProject_3\Orchestrator\AGENTS.md`
- `C:\Temp\CorrisBot_TestProject_3\Orchestrator\ROLE_ORCHESTRATOR.md`
- `C:\Temp\CorrisBot_TestProject_3\Orchestrator\Prompts\Inbox\Console.log`
- `C:\Temp\CorrisBot_TestProject_3\Orchestrator\Prompts\Inbox\Talker\Prompt_2026_02_15_01_54_40_865.md`
- `C:\Temp\CorrisBot_TestProject_3\Orchestrator\Prompts\Inbox\Talker\Prompt_2026_02_15_01_54_40_865_Result.md`
- `C:\Temp\CorrisBot_TestProject_3\Talker\Prompts\Inbox\Orc_CorrisBot_TestProject_3\Prompt_2026_02_15_01_58_23_538.md`

### 3) Скриптовая цепочка создания/запуска (для проверки порядка сборки и cwd)
- `C:\CorrisBot\Looper\CreateProjectStructure.bat`
- `C:\CorrisBot\Looper\StartLoopsInWT.py`
- `C:\CorrisBot\Looper\CodexLoop.bat`
- `C:\CorrisBot\Looper\codex_prompt_fileloop.py`
- `C:\Temp\CorrisBot_TestProject_3\Temp\wt_layout_state.json`

## Что проверить пошагово
1. Восстанови фактическую хронологию (по таймстампам):
- когда Talker положил prompt Orchestrator;
- когда Orchestrator начал обработку;
- когда сформировался `..._Result.md`;
- когда Orchestrator отправил отчет в project Talker inbox.

2. Проверь, какой именно instruction-set был доступен Orchestrator во время прогона:
- из snapshot `C:\Temp\CorrisBot_TestProject_3\Orchestrator\AGENTS.md`;
- отдельно выдели правила про:
  - обязательность делегирования кода исполнителям;
  - ограничение на самостоятельную реализацию кода;
  - ожидание создания/переиспользования Executors.

3. Проверь гипотезу «не тот cwd / не тот AGENTS.md»:
- найди в `Console.log` и `..._Result.md` фактические признаки рабочего каталога (`.` / `..`, перечисление файлов, структура);
- сопоставь с ожидаемым `C:\Temp\CorrisBot_TestProject_3\Orchestrator`;
- проверь цепочку запуска (`StartLoopsInWT.py` -> `CodexLoop.bat` -> `codex_prompt_fileloop.py`) на предмет, где задается `-C` и `cwd` для codex.

4. Проверь гипотезу «AGENTS.md не был собран/не существовал на момент запуска»:
- по `CreateProjectStructure.bat` определи порядок (сборка `AGENTS.md` до/после запуска);
- по snapshot подтверди наличие `AGENTS.md` в момент обработки;
- оцени, есть ли признаки гонки между созданием структуры и стартом лупера.

5. Проверь поведенческий конфликт:
- Orchestrator по факту сам написал скрипты в `C:\Temp\TestProject_3` и не создал Executor.
- Дай обоснование, это:
  - (A) скорее "инструкции не загружены/не применены";
  - (B) или "инструкции загружены, но модель выбрала нарушить".

## Формат вывода (обязателен)
Сделай отчет в отдельном `.md` файле:
- `C:\CorrisBot\Gateways\Telegram\Plans\Task_P4_P5_Orchestrator_Role_Read_Investigation_Report.md`

Структура отчета:
1. Краткий вердикт (1-3 предложения):
- Читал/не читал инструкции? Уровень уверенности (High/Medium/Low).

2. Доказательства по хронологии (с конкретными timestamp и путями).

3. Доказательства по `cwd` и выбору `AGENTS.md`.

4. Разбор причин п.4 и п.5:
- отдельный вывод по п.4;
- отдельный вывод по п.5.

5. Root cause tree:
- основная причина;
- сопутствующие факторы;
- почему это не было поймано раньше.

6. Точечные рекомендации (без правок кода в этой задаче):
- максимум 3 изменения для предотвращения повтора.

## Критерии приемки
- Нет предположений без ссылок на артефакт/строку/файл.
- Есть четкий ответ на дилемму:
  - "не читал" -> почему именно;
  - "читал" -> почему тогда не следовал.
- Отчет разделяет факты прогона и изменения, внесенные позже (п.2/п.7).

## Ограничения
- Не менять код и не запускать рефакторинг.
- Не перезапускать инфраструктуру.
- Только расследование и отчет.
