# Анализ бага: /reset не работает для Kimi runner

## Дата создания
2026-02-17

---

## 1. Описание проблемы (симптомы)

### Наблюдаемое поведение
При выполнении команды `/reset` в Telegram-боте:
1. Бот отвечает "Сессия сброшена для X отправителей" (удаляет файлы из `loop_status/`, `results/`, etc.)
2. При отправке нового сообщения Kimi runner **продолжает использовать старый `thread_id`**
3. Вместо создания новой сессии происходит "возобновление" старой

### Debug-логи
```
✅ Session files cleared:
  - tg_corriscant: 9 files removed
  - tg_othersender: 0 files removed

❌ После сброса:
  - thread_id остаётся: 52d90ef0-9fb9-47d7-a06a-429ace2fc0e0
  - Новое сообщение привязано к старой сессии Kimi CLI
```

### Ожидаемое поведение
После `/reset` должна создаваться **новая сессия** с новым UUID, история переписки не должна переноситься.

---

## 2. Архитектурный контекст

### Структура проекта
```
CorrisBot/
├── Looper/
│   ├── codex_prompt_fileloop.py  # Главный looper, управление сессиями
│   └── agent_runners.py          # CodexRunner, KimiRunner
├── Gateways/Telegram/
│   └── tg_codex_gateway.py       # Обработка /reset, запись в Talker
└── Talker/<sender_name>/         # Директории отправителей
    └── loop_state.json           # Сохранённый thread_id
```

### Ключевые компоненты

#### A. Хранение сессии (Talker)
- Каждый `sender_name` имеет свою директорию в `Talker/`
- `loop_state.json` содержит: `{"thread_id_codex": "...", "thread_id_kimi": "...", ...}`
- **Важно**: В Talker один пользователь = один `thread_id` на всех отправителей

#### B. KimiRunner (agent_runners.py)
```python
def build_command(self, prompt_text, session_id, work_dir):
    # Всегда передаём --session
    if session_id:
        cmd.extend(["--session", session_id])  # Resume existing
    else:
        import uuid
        cmd.extend(["--session", str(uuid.uuid4())])  # Force NEW session

def _detect_session_id(self, sessions_before):
    # Возвращает новую сессию из diff, иначе None (без fallback!)
```

#### C. Looper (codex_prompt_fileloop.py)
```python
def run_forever(self):
    thread_id: Optional[str] = None  # Один thread_id на ВСЕХ отправителей!
    
    # При старте: ищем thread_id во всех loop_state.json
    for sender_dir in self.get_sender_dirs():
        state_thread_id, _, updated_at = self.read_sender_state(sender_dir)
        if state_thread_id and updated_at >= best_thread_updated_at:
            thread_id = state_thread_id  # Берём самый свежий
```

#### D. Gateway (tg_codex_gateway.py)
```python
async def cmd_reset_session(update, context):
    # Очищает ВСЕ sender_dirs одновременно
    sender_count, removed_files = _reset_all_sender_dirs()
```

---

## 3. Гипотезы о причинах

### Гипотеза 1: Не все loop_state.json очищаются (ВЕРОЯТНАЯ)
**Описание**: Reset удаляет файлы только из `tg_corriscant`, но в других директориях (например, `Orc_CorrisBot_TestProject_5`) `loop_state.json` сохраняется.

**Почему это критично**:
- Looper при старте сканирует **все** sender_dirs и берёт самый свежий `thread_id`
- Если хоть один `loop_state.json` сохранился с `thread_id_kimi` — сессия восстанавливается
- `Talker` имеет shared `thread_id` для всех отправителей

**Доказательства**:
- Debug показывает: `tg_corriscant: 9 files removed`, другие: `0 files`
- `Orc_...` директории могли быть не тронуты или очищены ранее

**Статус**: Нужно проверить существование `loop_state.json` в других sender_dirs после reset

---

### Гипотеза 2: Kimi CLI auto-attach несмотря на --session (МЕНЕЕ ВЕРОЯТНА)
**Описание**: Kimi CLI игнорирует `--session <new_uuid>` если находит существующую сессию для workspace в `~/.kimi/sessions/<workspace_hash>/`

**Почему возможно**:
- Ранее观察到 Kimi "магически" присоединялся к старым сессиям без явного `--session`
- Файловая система сессий: `~/.kimi/sessions/<hash>/<uuid>/`
- Может быть hardcoded логика "если сессия существует — использовать её"

**Доказательства**: Нет прямых, но похожее поведение наблюдалось ранее

**Статус**: Требует проверки — посмотреть, что Kimi CLI делает с новым UUID при существующей сессии

---

### Гипотеза 3: Race condition между reset и looper (ВОЗМОЖНА)
**Описание**: 
1. Gateway вызывает `/reset`, удаляет файлы
2. Looper (в отдельном процессе/треде) видит изменения и пересоздаёт loop_state.json
3. Новый запрос от пользователя приходит до полного останова looper
4. Looper записывает старый thread_id в новый loop_state.json

**Доказательства**: Нет прямых логов race condition

**Статус**: Менее вероятна, но возможна при конкурентном доступе

---

### Гипотеза 4: Неправильная передача session_id=None (МАЛОВЕРОЯТНА)
**Описание**: После reset `thread_id` переменная в Looper не сбрасывается в `None`, и передаётся старое значение в `build_command`

**Почему маловероятно**:
- Код явно перезапускает Looper или thread_id должен быть сброшен
- Но стоит проверить логику в `run_forever()`

---

## 4. Варианты решения

### Решение A: Гарантированная очистка всех loop_state.json
**Что делать**: Убедиться, что `_reset_all_sender_dirs()` действительно находит и очищает **все** директории в `Talker/`

**Действия**:
1. Добавить логирование: список всех найденных sender_dirs перед очисткой
2. Добавить проверку: существует ли `loop_state.json` в каждой директории
3. Убедиться, что удаление происходит атомарно (все или ничего)

**Плюсы**: Простое, решает гипотезу 1
**Минусы**: Не решает гипотезу 2 (если проблема в Kimi CLI)

---

### Решение B: Явное удаление сессий Kimi CLI из файловой системы
**Что делать**: При `/reset` дополнительно удалять директорию сессии из `~/.kimi/sessions/<workspace_hash>/<uuid>/`

**Действия**:
1. В `KimiRunner` добавить метод `clear_session(session_id)`
2. В `cmd_reset_session` получать текущий `thread_id_kimi` и удалять из filesystem
3. Использовать `shutil.rmtree()` на `~/.kimi/sessions/<hash>/<uuid>/`

**Плюсы**: Гарантированно решает гипотезу 2
**Минусы**: 
- Завязка на внутреннюю структуру Kimi CLI
- Нужно знать workspace_hash
- Риск удалить не ту сессию

---

### Решение C: Изоляция сессий по sender (Архитектурное изменение)
**Что делать**: Отказаться от shared `thread_id` в Talker, каждый sender имеет свой thread_id

**Действия**:
1. В `run_forever()` использовать `Dict[sender_name, thread_id]` вместо одной переменной
2. При обработке каждого sender использовать свой thread_id
3. При `/reset` сбрасывать только конкретного sender

**Плюсы**: 
- Чистая архитектура
- Reset одного не влияет на других
**Минусы**: 
- Большое изменение (трогает CodexRunner тоже)
- Нарушает текущую логику Talker (один пользователь — одна сессия)

---

### Решение D: Команда "new session" вместо UUID для reset
**Что делать**: Вместо передачи нового UUID использовать специальный флаг или команду Kimi CLI для создания сессии

**Исследовать**:
1. Есть ли у Kimi CLI команда `--new-session` или аналог?
2. Можно ли использовать `--session ""` для强制 новой сессии?
3. Поведение при `--session $(uuidgen)` vs отсутствие флага

**Плюсы**: Может быть "правильным" способом
**Минусы**: Неизвестно, существует ли такая команда

---

## 5. Рекомендуемый план отладки

### Шаг 1: Проверить гипотезу 1 (наиболее вероятную)
```bash
# После /reset выполнить:
find Talker/ -name "loop_state.json" -exec echo "Found: {}" \; -exec cat {} \;
```
Ожидаемо: файлы должны отсутствовать или содержать `thread_id_kimi: null`

### Шаг 2: Проверить гипотезу 2
```bash
# Проверить сессии Kimi перед и после
ls -la ~/.kimi/sessions/<workspace_hash>/
# Запустить Kimi с новым UUID и проверить, создаётся ли новая директория
```

### Шаг 3: Добавить логирование в Looper
В `read_sender_state()` и `write_sender_state()` добавить debug output:
```python
print(f"[DEBUG] {sender_dir}: thread_id={thread_id}, exists={os.path.exists(state_path)}")
```

### Шаг 4: Проверить передачу аргументов
В `KimiRunner.build_command()` добавить:
```python
print(f"[KimiRunner] session_id={session_id}, will use uuid={new_uuid}")
```

---

## 6. Связанные файлы

| Файл | Роль в баге |
|------|-------------|
| `Looper/codex_prompt_fileloop.py` | Управление thread_id, чтение/запись loop_state.json |
| `Looper/agent_runners.py` | KimiRunner.build_command(), опция --session |
| `Gateways/Telegram/tg_codex_gateway.py` | Обработка /reset, вызов _reset_all_sender_dirs() |
| `Talker/*/loop_state.json` | Хранилище сессий (возможно, не очищается полностью) |
| `~/.kimi/sessions/` | Файловая система сессий Kimi CLI |

---

## 7. Дополнительные замечания

- **Talker архитектура**: Предполагает одного пользователя Telegram, поэтому thread_id общий для всех sender_dirs. Это упрощает логику, но создаёт проблему с reset.
- **Codex vs Kimi**: Codex использует stdin/stdout и thread_id из output. Kimi использует файловую систему и аргумент `--session`. Разные механизмы — разные баги.
- **Временная метка**: После reset важно, чтобы `loop_state.json` либо отсутствовал, либо имел `updated_at` старше, чем у "забытых" директорий.

---

## 8. История коммитов (Git)

### Коммиты, связанные с лечением /reset (в обратном хронологическом порядке)

```
b20a380 fix: /reset now clears all sender states in Talker for proper session reset
2d286f3 fix: per-sender thread_id to prevent cross-contamination after /reset  
8b60997 fix: remove fallback to old session in Kimi post_run_hook to fix /reset
b9bfb67 fix: Kimi creates new session on /reset by generating UUID instead of auto-attaching
55bf185 fix: prevent infinite loop in Kimi result processing
```

### Коммит ДО начала работы над /reset

**`cd2ad97` — feat: per-runner result parsing in gateway via <!-- runner: X --> metadata**

Это последний коммит перед началом работы над исправлением /reset. В этом коммите мы закончили базовую интеграцию Kimi CLI (runner selection, parsing результатов), но ещё не трогали логику сброса сессий.

### Что было добавлено до начала лечения:

| Коммит | Описание |
|--------|----------|
| `a720539` | feat: add KimiRunner implementation for Kimi Code CLI support |
| `2234b6e` | refactor: delegate agent-specific logic to AgentRunner in LoopRunner |
| `c040d2c` | feat: add AgentRunner abstraction and CodexRunner implementation |
| `5832de1` | feat: per-agent runner selection via --runner argument |
| `694a4ac` | feat: per-runner session storage in loop_state.json |
| `52c8894` | feat: run_gateway.bat reads runner from loops.wt.json |
| `cd2ad97` | **feat: per-runner result parsing in gateway** ← Точка отсчёта |

---

*Создано для совместной отладки между агентами*
