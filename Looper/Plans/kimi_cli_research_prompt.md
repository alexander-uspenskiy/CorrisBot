# Задача: Исследование Kimi Code CLI для интеграции

Мы интегрируем Kimi Code CLI в платформу, которая сейчас работает с Codex CLI.
Нам нужно понять конкретные возможности Kimi CLI, которые мы будем использовать программно.

Проведи следующие эксперименты и запиши результаты в файл `C:\CorrisBot\Looper\Plans\kimi_cli_research_report.md`.

## Эксперименты

### 1. Session Management
Нам критически важно уметь возобновлять сессию (resume). Исследуй:

a) Запусти `kimi info sessions` (или аналогичную команду) — покажи список сессий и формат session ID.
b) Каков формат session ID? (UUID, число, строка?)
c) Как получить session ID текущей сессии программно? Есть ли он в JSON-выводе `--output-format stream-json`?
d) Проверь: при запуске `kimi --print --output-format stream-json -c "скажи слово тест"` — появляется ли session_id где-то в JSON-выводе?
e) Покажи полный JSON-вывод этого запроса для анализа.

### 2. Resume Session
a) После эксперимента 1d, попробуй возобновить ту же сессию с `--continue` или `--session <ID>`:
   `kimi --print --output-format stream-json --continue -c "что я только что сказал?"`
   или если знаешь ID:
   `kimi --print --output-format stream-json --session <ID> -c "что я только что сказал?"`
b) Покажи полный JSON-вывод.
c) Сработал ли resume — помнит ли модель предыдущий контекст?

### 3. Полный формат JSON-событий
Выполни более сложный запрос, чтобы увидеть все типы событий:
`kimi --print --output-format stream-json --yolo -w C:\CorrisBot -c "Прочитай файл C:\CorrisBot\Looper\Info.md и скажи что в нём"`
Покажи полный JSON-вывод. Нас интересуют все возможные типы JSON-объектов в stream-json формате:
- assistant messages (текст)
- think/reasoning
- tool_calls (вызовы инструментов)
- tool results
- file read events
- любые другие типы событий

### 4. Stdin pipe
Проверь, можно ли передать промпт через stdin вместо `-c`:
`echo "скажи слово пайп" | kimi --print --output-format stream-json --yolo`
Работает ли это? Покажи результат.

### 5. AGENTS.md
Проверь, читает ли Kimi файл AGENTS.md из рабочей директории при запуске.
Запусти из директории, где есть AGENTS.md (например `C:\CorrisBot\Talker`):
`kimi --print --output-format stream-json --yolo -w C:\CorrisBot\Talker -c "Какие инструкции ты видишь в AGENTS.md?"`

### 6. Флаг --work-dir
Подтверди, что `-w` устанавливает рабочую директорию корректно:
`kimi --print --output-format stream-json --yolo -w C:\CorrisBot\Looper -c "Покажи текущую рабочую директорию командой cd"`

### 7. Exit codes
Проверь, какой exit code возвращает kimi при:
a) Успешном выполнении
b) Ошибке (например, невалидный флаг)
Для проверки после каждого запуска выполни `echo Exit code: %ERRORLEVEL%`

## Формат отчёта

Запиши результаты в файл `C:\CorrisBot\Looper\Plans\kimi_cli_research_report.md` в следующем формате:

```markdown
# Kimi CLI Research Report

## 1. Session Management
### Session ID Format
(формат ID, пример)
### Session ID in JSON output
(есть/нет, где именно)
### Session list command
(команда и пример вывода)

## 2. Session Resume
### Resume works
(да/нет)
### Resume method
(--continue / --session <ID>)
### Полный JSON при resume
(вставить JSON)

## 3. JSON Event Types
### Все обнаруженные типы JSON-объектов
(таблица: тип → пример → описание)

## 4. Stdin Pipe
### Работает
(да/нет)
### Пример
(команда и результат)

## 5. AGENTS.md
### Читает из work-dir
(да/нет)
### Доказательство
(вывод)

## 6. Work Directory
### -w работает
(да/нет)

## 7. Exit Codes
### Успех
(код)
### Ошибка
(код)
```

Важно: пиши реальные результаты экспериментов, не предполагай. Если что-то не работает — так и запиши.
