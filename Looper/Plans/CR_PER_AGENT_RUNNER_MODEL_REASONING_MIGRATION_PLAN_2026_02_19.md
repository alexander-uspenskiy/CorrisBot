# Full CR: Migration Plan (Per-Agent Runner/Model/Reasoning)

### 1) Findings (ordered by severity)

**Finding 1: Single `last_known_good` folder will clobber multiple agents in the same project**
- **Severity:** Critical
- **Что не так:** В п. 4.7 указан путь для бэкапов: `<RuntimeRoot>/AgentRunner/last_known_good/`. Из-за того, что `<RuntimeRoot>` для проекта — это его корневая директория, все агенты этого проекта (Orchestrator, Worker1, Worker2) будут сохранять свои `agent_runner.json` и профили в одну и ту же папку. 
- **Почему это риск:** При сохранении снапшота файлы разных агентов будут перезаписывать друг друга (race condition). Если придется восстанавливать `Worker1` из `last_known_good`, он может получить профиль `Orchestrator`'а или другого воркера, чье сохранение было последним. Это приведет к полной поломке конфигурации агентов внутри проекта.
- **Ссылка на файл+строку:** `Looper/Plans/PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md:264` (раздел 4.7)
- **Конкретное исправление:** Изменить путь хранения snapshot'а на per-agent storage. Например: `<RuntimeRoot>/AgentRunner/last_known_good/<AgentName>/` или `<AgentDirectory>/.last_known_good/`.

**Finding 2: Отсутствие механизма интеграции Resolver API с `.bat` файлами**
- **Severity:** High
- **Что не так:** В Phase 3 требуется заменить чтение глобального "runner" через `loops.wt.json` на вызов per-agent resolver'а внутри `.bat` скриптов (`StartLoopsInWT.bat`, `run_gateway.bat`), но не описано, *как* именно `.bat` должен детерминировано распарсить эти данные.
- **Почему это риск:** Обработка каскадной логики json/fallback/cli внутри Batch-скрипта невозможна без костылей. Если скрипт запуска будет вызывать тяжелый Python-процесс с нестандартным выводом или парсить json регулярками, запуск всей системы может быть хрупким. 
- **Ссылка на файл+строку:** `Looper/Plans/PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md:376` (раздел Phase 3)
- **Конкретное исправление:** Добавить в Phase 2 создание легковесного адаптера-экспортера (например, `resolve_agent_config.py --agent <path> --output-format bat_env`), который будет отдавать переменные окружения или параметры запуска прямо в `.bat`. 

**Finding 3: Противоречие CLI Priorities (Precedence) и механизма Hot-Reload**
- **Severity:** High
- **Что не так:** В п. 4.2 указано, что CLI аргументы (например, `--reasoning-effort`) имеют приоритет `1`, жестко перекрывая профиль из файла. При этом в п. 4.6 (Runtime Apply Rules) сказано, что `reasoning_effort` поддерживает подгрузку (hot-reload) "per prompt cycle". 
- **Почему это риск:** Если процесс стартовал с CLI флагом `--reasoning-effort=high`, а пользователь затем изменил файл профиля на `low` (ожидая hot-reload, заявленного в п.4.6), система, согласно приоритету п.4.2, должна всегда применять `high` (из CLI), игнорируя файл. Либо CLI флаг навсегда блокирует hot-reload, либо ломает принцип приоритетности.
- **Ссылка на файл+строку:** Строки 198 (Priority) и 259 (Runtime Apply)
- **Конкретное исправление:** Явно прописать поведение в 4.6: "Если передан CLI аргумент, он фиксирует значение на всё время работы процесса (hot-reload из файла игнорируется, выдается warning в лог)". Либо уточнить, что CLI задает только стартовое значение.

**Finding 4: Интеграция Orchestrator Self-heal и Windows Terminal (WT)**
- **Severity:** Medium
- **Что не так:** В п. 5.3 заявлено, что при падении/утере профиля воркера: "Orchestrator ... restores profile deterministically, retries launch."
- **Почему это риск:** Orchestrator работает как скрипт-лупер. Поднятие новых агентов в текущей архитектуре идет через `StartLoopsInWT`. Если процесс `Worker` упал (crash), Orchestrator может починить его json-файл на диске, но он *не сможет* сделать `retries launch` заново в контексте той же вкладки WT.
- **Ссылка на файл+строку:** `Looper/Plans/PER_AGENT_RUNNER_MODEL_REASONING_MIGRATION_PLAN_2026_02_19.md:312`
- **Конкретное исправление:** Уточнить: Orchestrator восстанавливает профиль на диске, а затем отчитывается пользователю (через Talker) с просьбой руками перезапустить упавшего агента (или использует внешний Watchdog). То есть "config retry", а не "process retry".

### 2) Gaps in Test Strategy
1. **Отсутствие тестов изоляции бэкапов (Snapshot Isolation):** Нет интеграционного теста, который бы удостоверился, что обновление конфигурации одного агента не перезаписывает снапшоты других агентов в рамках сложного проекта из нескольких Workers. Это обязательно выстрелит в регрессии.
2. **Отсутствие тестов разрешения путей (Root Resolver):** Нет тестов на логику определения `<RuntimeRoot>`. Поскольку `Talker` и `Workers` лежат в разной иерархии, нужен тест, подтверждающий, что Resolver корректно находит `model_registry.json`, поднимаясь по дереву, а не сваливается с ошибкой пути.
3. **Отсутствие тестов гонок (Race Conditions) при записи файлов:** План заявляет `atomic replace` и `mandatory file lock`, но в Phase 6 нет тестов на попытки одновременного чтения (лупером) и записи (Оркестратором). 

### 3) Contradictions / Ambiguities
1. **Ambiguity в определении `<RuntimeRoot>`:**
   - В тексте: "For project loopers: `<RuntimeRoot>` is project root. For Talker: `<RuntimeRoot>` is `Talker` root".
   - **Что нужно унифицировать:** Как именно код исполняемого скрипта понимает, где находится этот Runtime Root? Должен быть единый алгоритм без хардкода (например: скрипт идет вверх от папки агента, пока не найдет `AgentRunner/model_registry.json`).
2. **Конфликт `last_known_good` директории:** 
   - Как объяснено в Finding 1, использование единой глобальной для корневой папки директории конфликтует с независимостью агентов проекта.
   - **Что нужно унифицировать:** Поместить все per-agent артефакты (включая бэкапы снапшотов) строго внутрь или в привязку к пути `<AgentDirectory>`, а не к `<RuntimeRoot>`.

### 4) Final Verdict
`Ready with minor fixes`

**Must-fix before execution:**
1. Исправить путь `last_known_good` снапшотов с единого на per-agent storage (`.../last_known_good/<AgentName>/` или `<AgentDirectory>/.last_known_good/`), чтобы избежать перезаписи чужих бэкапов.
2. Четко описать интерфейс доставки (API) resolved-конфигов из Python скриптов в `.bat` запускаторы (Gateway/WT), чтобы не сломать boot-процесс платформы.
3. Разрешить коллизию между "CLI override precedence" и "hot reload of `reasoning_effort`" (написать, что CLI флаги лочат hot-reload, либо наоборот).
4. Зафиксировать однозначный унифицированный алгоритм вычисления пути к `<RuntimeRoot>` от папки текущего агента для поиска registry.
