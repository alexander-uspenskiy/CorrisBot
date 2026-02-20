# План реализации: Telegram Noise Cleanup через Option E v2

**Дата:** 2026-02-21  
**Статус:** Ready for execution  
**Scope:** Устранение user-visible шума (`EDIT_ROOT`, `RUN_ROOT`) без изменения transport semantics (`VERBATIM relay`, fail-closed contracts).

## 1. Контекст и проблема

В Telegram в user-facing сообщениях периодически появляются технические строки:
- `EDIT_ROOT=C:\CorrisBot`
- `RUN_ROOT=C:\_RUN_CorrisBot`

Корневая причина: машинный envelope (`Route-Meta`, `Routing-Contract`, `Reply-To`) склеивается с payload и напрямую виден LLM. Модель зеркалит часть технического контекста в отчеты.

## 2. Source of truth (прочитать перед реализацией)

1. `Looper/Plans/TELEGRAM_CONTRACT_NOISE_RESEARCH_2026_02_20.md`
2. `Looper/Plans/CR_TELEGRAM_CONTRACT_NOISE_RESEARCH_2026_02_20.md`
3. `Looper/Plans/CR_TELEGRAM_CONTRACT_NOISE_OPTION_E_2026_02_21.md`
4. `Looper/Plans/TELEGRAM_NOISE_RESEARCH_SUMMARY_2026_02_21.md`
5. `Looper/codex_prompt_fileloop.py`
6. `Looper/route_contract_utils.py`
7. `Talker/ROLE_TALKER.md`
8. `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
9. `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`

## 3. Целевое решение (Option E v2)

Не фильтровать Telegram-выход и не парсить relay в Talker/Gateway.  
Решение делается на входе в LLM:

1. **Machine-header isolation:** в operational envelope режиме из `Incoming prompt` удаляется блок `Routing-Contract`.
2. **Safe context projection:** из удаленного контракта извлекаются поля и добавляются в read-only системный контекст prompt-а:
   - `AgentsRoot`
   - `EditRoot`
   - `RouteSessionID`
   - `ProjectTag`
   - (`AppRoot` только при явно подтвержденной необходимости).
3. **Instructional guardrail:** роли Оркестратора/Worker явно запрещают вывод operational paths в human-readable report body.

Итог: LLM не видит сырой transport-block в payload, но сохраняет минимально необходимый контекст для корректных task-contract.

## 4. Инварианты (жесткие ограничения)

1. Не менять VERBATIM relay semantics в Talker/Gateway.
2. Не вводить regex/эвристики фильтрации текста в Telegram-канале.
3. Не допускать silent drop сообщений.
4. Не ломать fail-closed routing contracts (`Route-Meta`, `Routing-Contract`, `Reply-To`, `Message-Meta`).
5. Сохранить portability split (`AppRoot`/`AgentsRoot`/`EditRoot`) в транспортных файлах.

## 5. Scope изменений

### 5.1 Код
1. `Looper/route_contract_utils.py`
2. `Looper/codex_prompt_fileloop.py`

### 5.2 Инструкции
1. `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
2. `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`
3. Если меняются формулировки guardrail, синхронизация runtime-инструкций обязательна через источник шаблонов (без ad-hoc drift в собранном `Talker/AGENTS.md`).

### 5.3 Тесты
1. `Looper/tests/test_talker_routing_stabilization.py` (расширение)
2. Новый тестовый файл (рекомендуется): `Looper/tests/test_prompt_transport_isolation.py`
3. При необходимости точечной проверки helper parsing: `Looper/tests/test_send_reply_to_report.py` (только если затронуты shared parsers).

## 6. Поэтапный план реализации

## Phase 0: Preflight
1. Зафиксировать baseline:
   - `git status --short`
   - `py -m unittest discover -s Looper/tests -p "test_*.py"`
2. Убедиться, что рабочее дерево чистое или есть явный согласованный scope.

## Phase 1: Deterministic parsing primitives
Цель: безопасно выделять и удалять markdown-блоки envelope без эвристик.

1. В `route_contract_utils.py` добавить публичные helper-функции:
   - поиск блока по exact header вне code-fence/quote;
   - удаление первого валидного блока по header;
   - извлечение payload без конкретного блока.
2. Требования к behavior:
   - exact match заголовка (`Routing-Contract:`), не inline;
   - ignore code fence и quoted lines (`>`), как в текущем `_scan_markdown_block`;
   - при отсутствии блока возвращать исходный текст без изменений;
   - не удалять соседние пользовательские секции.
3. Не менять текущую валидацию контрактов, используемую transport-скриптами.

## Phase 2: Prompt envelope isolation в loop runner
Цель: убрать `Routing-Contract` из model-visible payload, но сохранить контекст.

1. В `codex_prompt_fileloop.py` добавить preprocessing входного prompt:
   - прочитать `user_prompt_text`;
   - определить, является ли prompt **operational envelope**:
     - `sender_id` не является пользовательским (`tg_*`),
     - есть валидный `Route-Meta` (оба поля, без placeholder), и
     - блок `Routing-Contract` находится как top-level markdown block (вне code fence/quote).
   - только для operational envelope пытаться извлечь/валидировать `Routing-Contract`;
   - удалить `Routing-Contract` из payload, который уходит в `Incoming prompt`, только в operational envelope режиме.
2. Safe projection:
   - в `build_loop_prompt` добавить read-only секцию (до `Incoming prompt:`):
     - `RouteSessionID`
     - `ProjectTag`
     - `AgentsRoot`
     - `EditRoot`
   - `AppRoot` не проецировать по умолчанию; добавлять только при явно подтвержденной необходимости контрактом/кодом.
   - scope projection:
     - для Orchestrator: `RouteSessionID`, `ProjectTag`, `AgentsRoot`, `EditRoot`;
     - для Worker: только `RouteSessionID`, `ProjectTag`;
     - для Talker: не проецировать path roots.
   - секцию добавлять только когда контракт валидно извлечен в operational envelope режиме.
3. Fail-closed guard:
   - если prompt определен как operational envelope и `Routing-Contract` malformed (не проходит валидацию), завершать turn ошибкой с понятным сообщением;
   - если `Routing-Contract:` встречается в обычном пользовательском тексте/примере (не operational envelope), не включать fail-closed блокировку и не резать payload;
   - не пытаться “угадывать” или частично восстанавливать поля.

## Phase 3: Role guardrail
Цель: запретить повторное засорение user-facing отчетов.

1. В `ROLE_ORCHESTRATOR.md` добавить явное правило:
   - не выводить `AppRoot/AgentsRoot/EditRoot` в human-readable body.
   - если path нужен для машинной логики, держать его только в transport metadata/contract.
2. В `ROLE_WORKER.md` добавить симметричное правило для отчетов Worker -> Orchestrator.
3. Формулировки сделать короткими, без дублей, без конфликта с текущими fail-closed правилами.

## Phase 4: Тесты (обязательно)

### 4.1 Unit tests для block isolation
Добавить тесты на:
1. корректное удаление `Routing-Contract` блока;
2. отсутствие удаления в code fence;
3. отсутствие удаления в quoted block;
4. корректная работа при нескольких секциях в prompt;
5. malformed block -> controlled failure (для operational envelope flow);
6. строка/пример с `Routing-Contract:` в обычном user text не вызывает fail-closed и не режет payload.

### 4.2 Prompt build tests
Проверить:
1. в итоговом `prompt_text` нет сырого блока `Routing-Contract:` в `Incoming prompt`;
2. read-only projection присутствует и содержит ожидаемые поля;
3. `Reply-To`/`Route-Meta` payload не повреждаются, если по дизайну остаются model-visible.

### 4.3 Regression tests
Минимум выполнить:
1. `py -m unittest Looper.tests.test_talker_routing_stabilization`
2. `py -m unittest Looper.tests.test_report_channel_recovery`
3. `py -m unittest Looper.tests.test_send_reply_to_report`
4. `py -m unittest discover -s Looper/tests -p "test_*.py"`

## Phase 5: Acceptance check
Проверка “готово” только при выполнении всех критериев:
1. В новых user-facing relay сообщениях нет `EDIT_ROOT`/`RUN_ROOT` path-хвоста по умолчанию.
2. Orchestrator продолжает формировать валидные worker task-contract (не ослеплен).
3. Никаких изменений в Talker/Gateway relay semantics.
4. Нет новых flaky/heuristic механизмов.
5. Все тесты зеленые.

## 7. Риски и как их закрыть

1. **Риск:** чрезмерное удаление текста (payload truncation).  
   **Митигировать:** deterministic parser + unit tests на edge-cases.
2. **Риск:** ослепление Оркестратора по path context.  
   **Митигировать:** role-scoped safe projection (`AgentsRoot`/`EditRoot` только для Orchestrator).
3. **Риск:** конфликт с transport fail-closed.  
   **Митигировать:** transport scripts не трогать, fail-closed включать только в operational envelope режиме.

## 8. Что запрещено в этой задаче

1. Вводить regex-фильтры в Gateway для user output.
2. Парсить/резать relay payload в Talker “по содержимому”.
3. Делать fallback “если блок не найден — молча продолжить с частичным контекстом”, если найден malformed header.

## 9. Deliverables от исполнителя

1. Кодовые изменения по scope.
2. `EXEC`-отчет:
   - `Looper/Plans/EXEC_TELEGRAM_NOISE_OPTION_E_V2_2026_02_21.md`
3. `CR`-отчет:
   - `Looper/Plans/CR_EXEC_TELEGRAM_NOISE_OPTION_E_V2_2026_02_21.md`

В `EXEC` обязательно:
1. список измененных файлов;
2. ключевые diff-решения;
3. команды тестов и результаты;
4. остаточные риски.

В `CR` обязательно:
1. findings по severity с `file:line`;
2. явная проверка, что `VERBATIM relay` не затронут;
3. вердикт `ready / ready with minor fixes / not ready`.

## 10. Commit policy

1. Минимум 1 атомарный commit после зеленого тестового прогона.
2. Рекомендуемо 2 commits:
   - `core: isolate routing-contract from model payload with safe projection`
   - `docs/tests: add guardrails and isolation coverage`

## 11. Быстрая проверка для заказчика (после merge)

1. Запустить типовой проектный цикл с Оркестратором.
2. Проверить Telegram: нет строк `EDIT_ROOT`/`RUN_ROOT` в обычных статусных/фазовых отчетах.
3. Проверить, что делегирование Worker продолжает работать и отчеты приходят по прежнему маршруту.
