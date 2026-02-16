# Отчет: Relay Bypass для Talker Looper

## Дата выполнения
2026-02-16

## Задача
Реализация механизма relay bypass для Talker Looper — автоматическая доставка сообщений от внутренних агентов (Orc, Executor) к пользователю без лишних LLM-вызовов.

---

## Выполненные изменения

### 1. ROLE_TALKER.md (строки 86-104)

**Изменено:** Правило relay для входящих внутренних сообщений.

**Было:** Talker создавал prompt-файл вручную в inbox пользователя.

**Стало:** Talker использует YAML-блок в своём Result-файле:

```markdown
- Правило relay для входящих внутренних сообщений (sender вида `Orc_*`, `Executor_*`):
  - **КРИТИЧНО**: ты НЕ должен создавать файлы вручную в inbox пользователя (`tg_*`)
  - формат ответа для автоматической ретрансляции:

    ```
    ---
    type: relay
    target: <UserSenderID>
    from: <sender_id текущего промпта>
    ---
    [Orc_<ProjectTag>]: <оригинальный текст сообщения verbatim>
    ```

  - содержимое после YAML-блока передаётся пользователю **verbatim**
  - после YAML-блока Talker может добавить свой ответ отправителю — этот текст пойдёт только в Result исходного sender-а
```

---

### 2. codex_prompt_fileloop.py

Добавлены методы в класс `LoopRunner`:

#### `detect_relay_block(result_path: Path)` (строки 611-691)

Парсит Result-файл и извлекает YAML-блок relay.

**Особенности реализации:**
- Ищет `---` только в начале строки (защита от ложных срабатываний в JSON)
- Проверяет точное значение `type: relay` (не подстрока)
- Извлекает поля `target`, `from`
- Возвращает `(target, relay_content)` или `None`

**Формат YAML-блока:**
```yaml
---
type: relay
target: tg_corriscant
from: Orc_TestProject
---
[Orc_TestProject]: Сообщение для пользователя
```

#### `_is_valid_target_name(target: str)` (строки 693-703)

Валидация имени target-папки.

**Проверки:**
- Запрещены `..`, `/`, `\` (path traversal защита)
- Не пустая строка
- Без начальных/конечных пробелов

#### `handle_relay_delivery(target: str, relay_content: str)` (строки 705-734)

Создаёт relay-файл в target inbox.

**Имя файла:** `Prompt_<timestamp>_relay_Result.md`
- Пример: `Prompt_2026_02_16_13_45_30_123_relay_Result.md`
- Суффикс `_relay` позволяет Gateway идентифицировать файл
- Расширение `_Result.md` гарантирует, что Looper проигнорирует файл

**Обработка ошибок:**
- Невалидный target → ошибка в консоль, файл не создаётся
- Ошибка записи (OSError) → ошибка в консоль, looper продолжает работу

#### Изменение в `run_forever()` (строки 837-843)

```python
# --- Relay bypass: auto-deliver relay content to target inbox ---
# NOTE: Relay is processed AFTER thread_id validation to avoid duplicate
# deliveries if looper crashes/restarts due to missing thread_id.
relay_result = self.detect_relay_block(result_path)
if relay_result is not None:
    relay_target, relay_content = relay_result
    self.handle_relay_delivery(relay_target, relay_content)
```

**Важно:** Relay-блок выполняется **после** проверки `thread_id`.

**Почему:** Если `thread_id` не обнаружен, looper падает с исключением. Раньше relay создавался до проверки, и при перезапуске looper'а тот же prompt обрабатывался заново → **дублирование** сообщения пользователю. Теперь relay создаётся только после успешной валидации `thread_id`.

---

### 3. AGENTS.md

Пересобран автоматически из `AGENTS_TEMPLATE.md` и `ROLE_TALKER.md`.

**Команда сборки:**
```powershell
python C:\CorrisBot\Looper\assemble_agents.py C:\CorrisBot\Talker\AGENTS_TEMPLATE.md C:\CorrisBot\Talker\AGENTS.md
```

Результат: `[OK] Assembled C:\CorrisBot\Talker\AGENTS.md (207 lines)`

---

## Проверки

| Проверка | Результат |
|----------|-----------|
| Синтаксис Python | ✅ OK |
| `codex_prompt_fileloop.py --help` | ✅ OK |
| Парсинг `type: relay` (точное совпадение) | ✅ OK |
| Защита от `---` в JSON | ✅ OK |
| Валидация target (path traversal) | ✅ OK |
| Timestamp regex (`2026_02_16_13_00_00_123_relay`) | ✅ OK |
| Кодировка UTF-8 | ✅ OK |

---

## Рекомендации по использованию

### Для составителя промпта (Talker):

При получении сообщения от внутреннего агента (`Orc_*`, `Executor_*`):

1. **Не создавай файл вручную** в `tg_*` inbox
2. **Используй YAML-блок** в своём Result-файле:
   ```
   ---
   type: relay
   target: tg_corriscant
   from: Orc_TestProject
   ---
   [Orc_TestProject]: Текст сообщения verbatim
   ```
3. **Можно добавить ответ отправителю** после YAML-блока — он пойдёт только в Result агента

### Пример полного ответа Talker:

```markdown
---
type: relay
target: tg_corriscant
from: Orc_CorrisBot_TestProject_5
---
[Orc_CorrisBot_TestProject_5]: Задача выполнена. Созданы 3 файла:
- config.json
- main.py
- README.md

Принято, передал пользователю.
```

В этом примере:
- Всё до и включая `[Orc_...]: ...` пойдёт пользователю через Gateway
- Текст "Принято, передал пользователю." пойдёт только в Result Orc (не ретранслируется)

---

## Файлы изменены

- `C:\CorrisBot\Talker\ROLE_TALKER.md` — обновлено правило relay
- `C:\CorrisBot\Looper\codex_prompt_fileloop.py` — добавлены методы relay
- `C:\CorrisBot\Talker\AGENTS.md` — пересобран автоматически

---

## Git Commit

```
commit 7fe5101
Author: Kimi Code CLI
Date:   2026-02-16

feat: implement relay bypass for Talker looper

- Add detect_relay_block() to parse YAML relay blocks from Result files
- Add handle_relay_delivery() to create *_relay_Result.md files
- Add _is_valid_target_name() for path traversal protection
- Update ROLE_TALKER.md with new relay format (YAML block)
- Rebuild AGENTS.md from template
- Move relay processing after thread_id validation to prevent duplicates

Relay bypass allows internal agents (Orc, Executor) to send messages
to users without extra LLM calls or content distortion.
```

**Изменённые файлы:**
- `Looper/codex_prompt_fileloop.py` (+2 новых метода, ~120 строк)
- `Talker/ROLE_TALKER.md` (переписано правило relay)
- `Talker/AGENTS.md` (пересобран из шаблона)
- `Looper/Plans/talker_relay_bypass.md` (файл задачи)
- `Looper/Plans/talker_relay_bypass_REPORT.md` (этот отчёт)

---

## Статус

✅ **Готово к использованию**
