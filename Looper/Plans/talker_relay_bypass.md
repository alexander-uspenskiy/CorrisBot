# Задача: Relay Bypass для Talker Looper

## Контекст проблемы

Talker looper мониторит все подкаталоги `Prompts/Inbox/`, включая `tg_corriscant` (gateway-канал пользователя).
Когда внутренний агент (Orc, Executor) присылает сообщение → Talker создаёт relay-файл в `tg_corriscant/Prompt_*.md` → тот же looper подхватывает его → Codex LLM пересказывает вместо verbatim relay. Это расходует лишний LLM-вызов и искажает содержимое.

## Требуемые изменения

### Часть 1: Правила Talker Role

> **ВАЖНО**: Файл `AGENTS.md` — это **автоматически собираемый** файл. Он генерируется скриптом `C:\CorrisBot\Looper\assemble_agents.py` из шаблона `C:\CorrisBot\Talker\AGENTS_TEMPLATE.md`, который содержит `Read:` ссылки на другие файлы. **НЕ РЕДАКТИРУЙ `AGENTS.md` напрямую** — он будет перезаписан при следующей сборке.
>
> Цепочка сборки:
> ```
> AGENTS_TEMPLATE.md
>   → Read: C:\CorrisBot\Looper\ROLE_LOOPER_BASE.md
>   → Read: C:\CorrisBot\Talker\ROLE_TALKER.md
>   → assemble_agents.py → AGENTS.md
> ```
>
> Правило relay живёт в `ROLE_TALKER.md`. Менять нужно **только** его.

#### 1.1 Файл: `C:\CorrisBot\Talker\ROLE_TALKER.md`

Найти блок правил relay для внутренних сообщений (строки 86-91, начинается с `- Правило relay для входящих внутренних сообщений`). **Заменить** его новой версией:

```markdown
- Правило relay для входящих внутренних сообщений (sender вида `Orc_*`, `Executor_*` — любой sender, НЕ начинающийся с `tg_`):
  - это безусловный канал "внутренний агент → пользователь через Talker";
  - **КРИТИЧНО**: ты НЕ должен создавать файлы вручную в inbox пользователя (`tg_*`). Ретрансляция выполняется автоматически скриптом looper после твоей обработки;
  - формат ответа для автоматической ретрансляции: в своём Result-файле используй YAML-блок relay:

    ```
    ---
    type: relay
    target: <UserSenderID>
    from: <sender_id текущего промпта>
    ---
    [Orc_<ProjectTag>]: <оригинальный текст сообщения verbatim>
    ```

  - `target` = UserSenderID из активной проектной сессии (обычно `tg_corriscant`);
  - `from` = sender_id входящего промпта (например, `Orc_CorrisBot_TestProject_5`);
  - содержимое после YAML-блока передаётся пользователю **verbatim**, не пересказывай и не добавляй рекомендации;
  - обязательно указывай источник в начале текста: `[Orc_<ProjectTag>]: ...`;
  - после YAML-блока с relay Talker может добавить свой ответ отправителю обычным текстом (вне YAML-блока) — этот текст пойдёт только в Result исходного sender-а и НЕ будет ретранслирован.
```

> **ВАЖНО**: при редактировании сохранять оригинальную кодировку файла (UTF-8). Не менять другие части файла.

#### 1.2 Пересборка AGENTS.md

После редактирования `ROLE_TALKER.md` необходимо пересобрать `AGENTS.md`:

```powershell
python C:\CorrisBot\Looper\assemble_agents.py C:\CorrisBot\Talker\AGENTS_TEMPLATE.md C:\CorrisBot\Talker\AGENTS.md
```

Убедиться, что в выводе нет ошибок и появилось `[OK] Assembled ...`.

---

### Часть 2: Script-level relay bypass в `codex_prompt_fileloop.py`

Файл: `C:\CorrisBot\Looper\codex_prompt_fileloop.py`

#### 2.1 Добавить метод `detect_relay_block` в класс `LoopRunner`

Разместить перед методом `run_forever` (строка ~611).

Логика метода:
- Принимает `result_path: Path` (путь к файлу Result, который только что создан Codex).
- Читает содержимое файла.
- Ищет YAML-блок relay: текст между `---` маркерами, содержащий `type: relay`.
- Если найден:
  - Извлекает значение `target` (имя папки-получателя, напр. `tg_corriscant`).
  - Извлекает содержимое ПОСЛЕ закрывающего `---` (это relay-контент для пользователя).
  - Возвращает `(target, relay_content)`.
- Если не найден: возвращает `None`.

**Требования к парсингу YAML-блока:**
- YAML-блок может находиться в любом месте Result-файла (не обязательно в начале — перед ним будет стандартный заголовок `# Codex Result for...` и JSON-строки от Codex).
- Искать паттерн: строка `---`, затем строки с `type: relay`, `target: ...`, `from: ...`, затем закрывающая строка `---`.
- Между `---` маркерами могут быть только строки формата `key: value` или пустые строки.
- Контент для relay — всё что идёт после закрывающего `---` до конца agent_message или до конца файла.
- Использовать regex или построчный парсинг — **НЕ** добавлять зависимость на `pyyaml`.

**Важный нюанс**: Result-файл содержит JSON-строки от Codex (события `item.completed`, `turn.completed` и т.д.). YAML-блок relay будет внутри текста `agent_message`. Поэтому:
- Сначала извлечь все `agent_message` тексты из JSON-строк Result-файла.
- Затем искать YAML-блок relay в объединённом тексте agent_message.

Альтернативный подход (проще): искать YAML-блок relay в **сыром** тексте Result-файла построчно. Поскольку YAML-маркер `---` и `type: relay` — уникальные паттерны, ложных срабатываний не будет.

#### 2.2 Добавить метод `handle_relay_delivery`

Логика:
- Принимает `target: str` (имя папки-получателя) и `relay_content: str` (текст для ретрансляции).
- Формирует путь: `self.inbox_root / target`.
- Создаёт каталог, если не существует.
- Генерирует имя файла `Prompt_<timestamp>_relay_Result.md` используя текущее время (формат: `YYYY_MM_DD_HH_MM_SS_mmm`). Суффикс `_relay` нужен, чтобы отличать relay-Result от обычных Result.
- Записывает в файл:
  ```
  # Relay Result

  <relay_content>

  Finished: <timestamp>
  ```
- Записывает в Console.log: `[relay] Delivered to <target>: <имя файла>`.

**КРИТИЧНО**: Файл создаётся как `Prompt_*_Result.md` (не `Prompt_*.md`). Это гарантирует:
- Gateway (`tg_codex_gateway.py`) его подхватит — он ищет файлы `Prompt_*_Result.md` в inbox-каталогах.
- Looper его **НЕ** подхватит — looper обрабатывает только `Prompt_*.md` (без `_Result`), см. `pick_sender_candidate` строка 550: `if file_name.endswith("_Result.md"): continue`.

**Соответствие формату имени файла для Gateway:**
Gateway использует regex для извлечения marker из имени файла (см. `_extract_result_marker` в `tg_codex_gateway.py`, строка 460-466):
```python
if not (file_name.startswith("Prompt_") and file_name.endswith("_Result.md")):
    return None
marker = file_name[len("Prompt_"):-len("_Result.md")]
```
Далее marker проверяется через `_parse_prompt_sort_key(marker)`, который использует regex:
```
r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
```
Суффикс `_relay` (буквенно-цифровой) попадает в группу `suffix` и будет корректно распознан.

Итого имя файла: `Prompt_2026_02_16_13_00_00_123_relay_Result.md` — Gateway распарсит marker как `2026_02_16_13_00_00_123_relay`, suffix=`relay`, всё корректно.

#### 2.3 Модифицировать `run_forever`

В основном цикле `run_forever`, **после** успешного завершения `run_codex` и обновления `thread_id` (строка ~706), но **до** записи `Finished` (строка ~712), добавить вызов:

```python
# --- Relay bypass: auto-deliver relay content to target inbox ---
relay_result = self.detect_relay_block(result_path)
if relay_result is not None:
    relay_target, relay_content = relay_result
    self.handle_relay_delivery(relay_target, relay_content)
```

Это место в коде — строки 704-712 текущей версии:
```python
            detected_thread_id = self.get_thread_id_from_output(lines)
            if detected_thread_id:
                thread_id = detected_thread_id

            # ... (thread_id check) ...

            self.append_text(result_path, f"\nFinished: {now_str()}\n")
```

Вставить проверку relay **после** блока `detected_thread_id`, **перед** `append_text(... "Finished" ...)`.

---

## Чего НЕ менять

- Файл `AGENTS.md` — он автоматически собирается из шаблона, см. часть 1.2.
- Файл `tg_codex_gateway.py` — Gateway не нуждается в изменениях, он уже корректно обрабатывает `Prompt_*_Result.md` файлы.
- Метод `build_loop_prompt` — не трогать.
- Метод `pick_sender_candidate` — он уже пропускает `_Result.md` файлы (строка 550).

---

## Проверка после реализации

1. Убедиться, что `codex_prompt_fileloop.py` запускается без ошибок:
   ```
   python C:\CorrisBot\Looper\codex_prompt_fileloop.py --help
   ```
2. Проверить, что regex marker `2026_02_16_13_00_00_123_relay` успешно парсится:
   ```python
   import re
   PROMPT_TIMESTAMP_RE = re.compile(
       r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_"
       r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
       r"(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
   )
   assert PROMPT_TIMESTAMP_RE.fullmatch("2026_02_16_13_00_00_123_relay") is not None
   ```
3. Пересобрать AGENTS.md и убедиться в успехе:
   ```
   python C:\CorrisBot\Looper\assemble_agents.py C:\CorrisBot\Talker\AGENTS_TEMPLATE.md C:\CorrisBot\Talker\AGENTS.md
   ```
4. Проверить, что в пересобранном `AGENTS.md` новое правило relay присутствует и синтаксически корректно.
5. Убедиться, что кодировка `ROLE_TALKER.md` сохранена (UTF-8).

---

## Справочная информация

- Полный файл `codex_prompt_fileloop.py`: `C:\CorrisBot\Looper\codex_prompt_fileloop.py` (805 строк) — **основной файл для изменений**.
- `ROLE_TALKER.md`: `C:\CorrisBot\Talker\ROLE_TALKER.md` (106 строк) — **источник правил relay, единственный .md для редактирования**.
- `AGENTS_TEMPLATE.md`: `C:\CorrisBot\Talker\AGENTS_TEMPLATE.md` (15 строк) — шаблон сборки, содержит `Read:` ссылки. **Не менять**.
- `assemble_agents.py`: `C:\CorrisBot\Looper\assemble_agents.py` (151 строка) — скрипт сборки AGENTS.md. **Не менять, только запустить после правки ROLE_TALKER.md**.
- `AGENTS.md`: `C:\CorrisBot\Talker\AGENTS.md` — **автосборка, не редактировать напрямую**.
- Gateway: `C:\CorrisBot\Gateways\Telegram\tg_codex_gateway.py` (1805 строк) — **не менять**.
