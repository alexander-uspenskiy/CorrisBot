# Kimi CLI Research Report

## 1. Session Management

### Session ID Format
Не удалось определить формат session ID через доступные команды. Команда `kimi info sessions` не существует.

### Session ID in JSON output
**Нет** — session_id отсутствует в JSON-выводе `--output-format stream-json`.

Пример вывода (простой запрос):
```json
{"role":"assistant","content":[{"type":"think","think":"...","encrypted":null},{"type":"text","text":"..."}]}
```

### Session list command
Команда `kimi info sessions` **не существует**. Доступные команды в `kimi info` ограничены:
```
Usage: kimi info [OPTIONS] COMMAND [ARGS]...  
Show version and protocol information.
Options: --json, --help
```

Список сессий через CLI получить не удалось.

---

## 2. Session Resume

### Resume works
**Да** — resume работает через флаг `--continue` (`-C`).

### Resume method
Доступные методы:
- `--continue` / `-C` — продолжить предыдущую сессию для рабочей директории
- `--session <ID>` / `-S <ID>` — указать конкретный session ID для возобновления

### Полный JSON при resume
Запрос:
```bash
kimi --print --output-format stream-json --continue -c "что я только что сказал?"
```

Ответ (модель помнила предыдущий контекст):
```json
{"role":"assistant","content":[{"type":"think","think":"...предыдущий запрос: \"Прочитай файл C:\\CorrisBot\\Looper\\Info.md и скажи что в нём\"...","encrypted":null},{"type":"text","text":"Вы сказали: \"Прочитай файл C:\\CorrisBot\\Looper\\Info.md и скажи что в нём\""}]}
```

**Результат**: Модель успешно вспомнила предыдущий запрос о чтении файла Info.md.

---

## 3. JSON Event Types

### Все обнаруженные типы JSON-объектов

| Тип | Пример | Описание |
|-----|--------|----------|
| `assistant` с `think` + `text` | `{"role":"assistant","content":[{"type":"think",...},{"type":"text",...}]}` | Основной ответ модели с reasoning и текстом |
| `assistant` с `tool_calls` | `{"role":"assistant","content":[...],"tool_calls":[{"type":"function","id":"...","function":{"name":"ReadFile","arguments":"..."}}]}` | Вызов инструмента (например, ReadFile) |
| `tool` | `{"role":"tool","content":[{"type":"text","text":"..."}],"tool_call_id":"..."}` | Результат выполнения инструмента |

### Полный JSON с tool calls (эксперимент 3)
Запрос:
```bash
kimi --print --output-format stream-json --yolo -w C:\CorrisBot -c "Прочитай файл C:\CorrisBot\Looper\Info.md и скажи что в нём"
```

Полный вывод (события разделены переносами строк):
```json
{"role":"assistant","content":[{"type":"think","think":"Пользователь просит прочитать файл...","encrypted":null}],"tool_calls":[{"type":"function","id":"tool_9YBmp4QgCQhbbZQtp3f5jLFp","function":{"name":"ReadFile","arguments":"{\"path\": \"C:\\\\CorrisBot\\\\Looper\\\\Info.md\"}"}}]}
{"role":"tool","content":[{"type":"text","text":"<system>13 lines read from file starting from line 1. End of file reached.</system>"},{"type":"text","text":"     1\tLoop agent code (Git)\n     2\t..."}],"tool_call_id":"tool_9YBmp4QgCQhbbZQtp3f5jLFp"}
{"role":"assistant","content":[{"type":"think","think":"Файл успешно прочитан...","encrypted":null},{"type":"text","text":"В файле `C:\\CorrisBot\\Looper\\Info.md` содержится информация..."}]}
```

---

## 4. Stdin Pipe

### Работает
**Нет** — stdin pipe вызывает ошибку кодировки.

### Пример
Команда:
```bash
echo "скажи слово пайп" | kimi --print --output-format stream-json --yolo
```

Результат:
```
Unknown error: 'charmap' codec can't encode characters in position 127-130: character maps to <undefined>
```

**Вывод**: Передача текста через stdin не работает из-за проблем с кодировкой (UTF-8 → Windows-1251).

---

## 5. AGENTS.md

### Читает из work-dir
**Да** — Kimi читает AGENTS.md из рабочей директории, указанной через `-w`.

### Доказательство
Запрос:
```bash
kimi --print --output-format stream-json --yolo -w C:\CorrisBot\Talker -c "Какие инструкции ты видишь в AGENTS.md?"
```

Ответ (фрагмент):
```
В `AGENTS.md` содержатся следующие инструкции:

## 1. Looper Base Rules
- Работа с проектами должна быть чёткой...

## 2. Communication Channels
- Промпты помещаются в папку `Prompts/Inbox/<SenderID>/`...

## 3. ROLE TALKER
- Talker — посредник между пользователем и системой...

## 4. SKILL GATEWAY IO
- Обработка входящих сообщений...
...
```

Модель успешно прочитала и обобщила содержимое AGENTS.md из указанной директории.

---

## 6. Work Directory

### -w работает
**Да** — флаг `-w` корректно устанавливает рабочую директорию.

### Доказательство
Запрос:
```bash
kimi --print --output-format stream-json --yolo -w C:\CorrisBot\Looper -c "Покажи текущую рабочую директорию"
```

Выполнение через Shell:
```json
{"role":"assistant","content":[...],"tool_calls":[{"type":"function","id":"...","function":{"name":"Shell","arguments":"{\"command\": \"Get-Location\"}"}}]}
{"role":"tool","content":[{"type":"text","text":"Path\\r\\n----\\r\\nC:\\\\CorrisBot\\\\Looper"}],"tool_call_id":"..."}
```

Результат: `C:\CorrisBot\Looper` — соответствует указанной через `-w` директории.

---

## 7. Exit Codes

### Успех
**0**

Пример:
```powershell
kimi --print --output-format stream-json -c "test" 2>&1 ; Write-Host "Exit code: $LASTEXITCODE"
# Exit code: 0
```

### Ошибка
**2**

Пример:
```powershell
kimi --invalid-flag 2>&1 ; Write-Host "Exit code: $LASTEXITCODE"
# Exit code: 2
# Ошибка: No such option: --invalid-flag
```

---

## Дополнительные находки

### Флаги сессий (из `kimi -h`)
```
| --session  | -S | TEXT | Session ID to resume for the working directory. Default: new session. |
| --continue | -C |      | Continue the previous session for the working directory.              |
```

### Ограничения
1. Нет прямого способа получить список сессий через CLI
2. Session ID не виден в JSON-выводе (возможно, хранится внутри CLI)
3. Stdin pipe не работает с кириллицей
4. Вывод содержит кракозябры вместо кириллицы в некоторых случаях (проблема кодировки терминала)

### Рекомендации для интеграции
1. Использовать `-c "prompt"` вместо stdin
2. Для resume использовать `--continue` (проще, чем отслеживать session ID)
3. Для парсинга JSON использовать stream-json формат — он содержит все события
4. Проверять `$LASTEXITCODE` в PowerShell (не `%ERRORLEVEL%`)
