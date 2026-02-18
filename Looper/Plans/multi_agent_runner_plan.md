# Plan: Multi-Agent Runner Support (Codex + Kimi Code)

> **Для исполнителя**: этот план предназначен для пошагового исполнения агентом.
> Каждый этап самодостаточен, заканчивается коммитом и CR-чекпоинтом.
> **Не переходить к следующему этапу без одобрения пользователя (CR).**
> У тебя есть доступ только к этому файлу и к проекту в `C:\CorrisBot`.

---

## Контекст

Платформа CorrisBot запускает AI-агентов ("луперов"), которые мониторят inbox-директории и обрабатывают промпт-файлы через CLI-агента. Сейчас единственный поддерживаемый CLI-агент — **Codex**. Нужно добавить поддержку **Kimi Code CLI** без ломки существующей Codex-логики.

### Текущая архитектура (что менять)

```
codex_prompt_fileloop.py  ← главный скрипт, класс LoopRunner
  ├── resolve_codex_executable()   ← ищет codex.exe           (строки 351-391)
  ├── run_codex()                  ← строит команду, subprocess (строки 393-482)
  ├── process_codex_line()         ← парсит Codex JSONL        (строки 262-332)
  ├── get_thread_id_from_output()  ← thread_id из JSON         (строки 245-260)
  ├── detect_relay_block()         ← relay-блоки из agent_msg  (строки 611-711)
  ├── read_sender_state()          ← читает loop_state.json    (строки 141-167)
  ├── write_sender_state()         ← пишет loop_state.json     (строки 169-180)
  └── run_forever()                ← основной цикл             (строки 756-868)

CodexLoop.bat              ← обёртка: вызывает codex_prompt_fileloop.py
StartLoopsInWT.py          ← запуск луперов в Windows Terminal
StartLoopsInWT.bat         ← обёртка для StartLoopsInWT.py
```

### Формат JSON-вывода: сравнение

**Codex** (event-based JSONL, флаг `exec --json`):
```json
{"type":"thread.started","thread_id":"abc123"}
{"type":"item.started","item":{"type":"command_execution","id":"cmd1","command":"echo hello"}}
{"type":"item.completed","item":{"type":"command_execution","id":"cmd1","status":"completed","exit_code":0,"aggregated_output":"hello\n"}}
{"type":"item.completed","item":{"type":"reasoning","text":"thinking..."}}
{"type":"item.completed","item":{"type":"agent_message","text":"Done!"}}
{"type":"turn.completed"}
```
Каждая строка — одно событие. `turn.completed` сигнализирует конец хода.

**Kimi** (OpenAI-style JSONL, флаг `--print --output-format stream-json`):
```json
{"role":"assistant","content":[{"type":"think","think":"thinking...","encrypted":null}],"tool_calls":[{"type":"function","id":"tool_xxx","function":{"name":"Shell","arguments":"{\"command\":\"echo hello\"}"}}]}
{"role":"tool","content":[{"type":"text","text":"<system>Command executed successfully.</system>"},{"type":"text","text":"hello\r\n"}],"tool_call_id":"tool_xxx"}
{"role":"assistant","content":[{"type":"think","think":"done","encrypted":null},{"type":"text","text":"Done!"}]}
```
**Важно**: одна JSON-строка Kimi может содержать несколько событий одновременно (think + text + tool_calls). Нет аналога `turn.completed` — Kimi завершает процесс по EOF.

### CLI-флаги: маппинг

| Назначение | Codex | Kimi |
|---|---|---|
| Рабочая директория | `-C <path>` | `-w <path>` |
| JSON вывод | `exec --json` | `--print --output-format stream-json` |
| Промпт | stdin pipe | `-c "text"` |
| Auto-approve | `--dangerously-bypass-approvals-and-sandbox` | `--yolo` |
| Resume сессии | `exec resume <thread_id>` | `--session <uuid>` |

### Управление сессиями

- **Codex**: `thread_id` извлекается из JSON-события `{"type":"thread.started","thread_id":"..."}`. Для resume: `codex exec resume <thread_id>`.
- **Kimi**: Session UUID хранится на диске в `~/.kimi/sessions/{workspace_hash}/{session_uuid}/`. Для resume: `kimi --session <session_uuid>`. Session UUID **не виден** в JSON-выводе — нужно определять по файловой системе: запомнить UUID-каталоги ДО вызова, найти новый ПОСЛЕ.
- **`loop_state.json`**: и Codex и Kimi хранят свой session/thread ID в поле `"thread_id"`. Не переименовывать ключ — backward compatibility.

---

## Этап 1: Создание `agent_runners.py` (новый файл)

**Цель**: создать абстрактный интерфейс Runner и реализацию CodexRunner. Чистый новый файл, без изменения существующего кода.

**Файл**: `C:\CorrisBot\Looper\agent_runners.py`

### 1.1. Абстрактный класс `AgentRunner`

```python
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class AgentRunner(ABC):
    """Абстрактный интерфейс CLI-агента."""

    @abstractmethod
    def resolve_executable(self) -> str:
        """Найти и вернуть путь к исполняемому файлу агента."""
        ...

    @abstractmethod
    def build_command(
        self,
        prompt_text: str,
        session_id: Optional[str],
        work_dir: Path,
    ) -> tuple[list[str], Optional[str]]:
        """
        Построить команду для запуска агента.
        Возвращает (cmd_list, stdin_text).
        - stdin_text=None → промпт передаётся через аргументы (Kimi: -c).
        - stdin_text=str  → промпт передаётся через stdin (Codex).
        """
        ...

    @abstractmethod
    def parse_output_line(
        self,
        line: str,
        started_commands: dict[str, bool],
    ) -> list[dict]:
        """
        Распарсить одну строку JSONL-вывода агента.
        Возвращает список событий (может быть 0, 1 или несколько).
        Одна строка Kimi JSON может содержать think + text + tool_calls,
        поэтому возвращается list, а не Optional.

        Формат каждого события — dict с ключом "event":
          "reasoning"        → {"event":"reasoning", "text": str}
          "agent_message"    → {"event":"agent_message", "text": str}
          "command_started"  → {"event":"command_started", "id": str, "command": str}
          "command_completed"→ {"event":"command_completed", "id": str, "exit_code": int, "output": str}
          "non_json_error"   → {"event":"non_json_error", "text": str}
          "non_json_warning" → {"event":"non_json_warning", "text": str}
          "error"            → {"event":"error", "text": str}
        """
        ...

    @abstractmethod
    def extract_session_id(self, lines: list[str]) -> Optional[str]:
        """Извлечь session/thread ID из вывода агента. None если нет в выводе."""
        ...

    @abstractmethod
    def extract_agent_messages(self, lines: list[str]) -> list[str]:
        """Извлечь тексты agent_message из вывода для relay-парсинга."""
        ...

    @abstractmethod
    def is_turn_completed(self, line: str) -> bool:
        """Проверить, является ли эта строка сигналом завершения хода."""
        ...

    @abstractmethod
    def is_session_not_found_error(self, output: str) -> bool:
        """Проверить, означает ли ошибка 'сессия не найдена' (для fallback на новую сессию)."""
        ...

    @property
    def supports_filesystem_session_detection(self) -> bool:
        """True если runner определяет session ID через файловую систему (а не из JSON)."""
        return False

    def pre_run_hook(self) -> None:
        """Вызывается перед запуском subprocess. Для KimiRunner: snapshot sessions."""
        pass

    def post_run_hook(self, lines: list[str]) -> Optional[str]:
        """
        Вызывается после завершения subprocess.
        Возвращает session_id если нужна дополнительная детекция (filesystem).
        Если не нужна — возвращает None (будет использован extract_session_id).
        """
        return None

    def post_run_cleanup(self) -> None:
        """Cleanup после обработки результата (например, удаление temp-файлов)."""
        pass
```

### 1.2. Класс `CodexRunner(AgentRunner)`

Перенос логики из `LoopRunner` — **копирование**, не удаление (удаление на этапе 2).

```python
class CodexRunner(AgentRunner):
    def __init__(
        self,
        codex_bin: Optional[str] = None,
        sandbox_mode: str = "danger-full-access",
        approval_policy: str = "never",
        web_search_enabled: bool = False,
        dangerously_bypass_sandbox: bool = True,
    ):
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy
        self.web_search_enabled = web_search_enabled
        self.dangerously_bypass_sandbox = dangerously_bypass_sandbox
        self._codex_bin_hint = codex_bin  # сохраняем hint до вызова resolve
        self._executable = self.resolve_executable()
```

Методы:

- **`resolve_executable()`** ← тело текущего `LoopRunner.resolve_codex_executable()` (строки 351-391). Использует `self._codex_bin_hint` вместо параметра. Сигнатура `def resolve_executable(self) -> str:` — совместима с ABC. Логика поиска: `shutil.which()`, `%APPDATA%/npm/codex.cmd`, VS Code extensions:
  ```python
  def resolve_executable(self) -> str:
      if self._codex_bin_hint:
          candidate = Path(self._codex_bin_hint).expanduser()
          if candidate.exists():
              return str(candidate.resolve())
          return self._codex_bin_hint

      candidates: list[str] = []
      for name in ["codex", "codex.cmd", "codex.exe"]:
          found = shutil.which(name)
          if found:
              candidates.append(found)

      appdata = os.environ.get("APPDATA")
      if appdata:
          npm_cmd = Path(appdata) / "npm" / "codex.cmd"
          if npm_cmd.exists():
              candidates.append(str(npm_cmd))

      vscode_ext_root = Path.home() / ".vscode" / "extensions"
      if vscode_ext_root.exists():
          vscode_bins = sorted(
              vscode_ext_root.glob("openai.chatgpt-*-win32-x64/bin/windows-x86_64/codex.exe"),
              reverse=True,
          )
          for bin_path in vscode_bins:
              candidates.append(str(bin_path))

      seen: set[str] = set()
      for candidate in candidates:
          key = candidate.lower()
          if key in seen:
              continue
          seen.add(key)
          return candidate

      raise RuntimeError(
          "codex command was not found. Set PATH or pass --codex-bin with full path."
      )
  ```

- **`build_command(prompt_text, session_id, work_dir)`** ← логика построения команды из `run_codex()` (строки 394-417):
  ```python
  def build_command(self, prompt_text, session_id, work_dir):
      base_cmd = [self._executable, "-C", str(work_dir)]
      if self.dangerously_bypass_sandbox:
          base_cmd.append("--dangerously-bypass-approvals-and-sandbox")
      else:
          base_cmd.extend(["-a", self.approval_policy, "-s", self.sandbox_mode])
      if not self.web_search_enabled:
          base_cmd.extend(["-c", "tools.web_search=false"])
      if session_id:
          cmd = base_cmd + ["exec", "resume", session_id, "--skip-git-repo-check", "--json", "-"]
      else:
          cmd = base_cmd + ["exec", "--skip-git-repo-check", "--json", "-"]
      return cmd, prompt_text  # stdin_text = prompt_text (Codex читает stdin)
  ```

- **`parse_output_line(line, started_commands)`** ← логика из `process_codex_line()` (строки 262-332). Возвращает `list[dict]` (обычно `[event]` или `[]`).

  **ВАЖНО**: текущий `process_codex_line()` также логирует non-JSON строки с error/warning (строки 267-272). Эту логику тоже нужно перенести — возвращать `non_json_error`/`non_json_warning` events:

  ```python
  def parse_output_line(self, line, started_commands):
      trim = line.strip()
      if not trim:
          return []

      # Non-JSON строки: проверить на error/warning
      if not (trim.startswith("{") and trim.endswith("}")):
          if re.search(r"\b(error|exception|failed|fatal)\b", trim, flags=re.IGNORECASE):
              return [{"event": "non_json_error", "text": trim}]
          elif re.search(r"\bwarn\b", trim, flags=re.IGNORECASE):
              return [{"event": "non_json_warning", "text": trim}]
          return []

      try:
          obj = json.loads(trim)
      except Exception:
          return []

      if obj.get("type") == "item.completed" and obj.get("item"):
          item = obj["item"]
          item_type = item.get("type")

          if item_type == "reasoning" and item.get("text"):
              return [{"event": "reasoning", "text": item["text"]}]

          if item_type == "agent_message" and item.get("text"):
              return [{"event": "agent_message", "text": item["text"]}]

          if item_type == "command_execution":
              item_id = str(item.get("id") or "")
              cmd = str(item.get("command") or "")
              status = str(item.get("status") or "")
              code = item.get("exit_code")
              aggregated_output = item.get("aggregated_output", "")
              return [{"event": "command_completed", "id": item_id, "command": cmd,
                        "status": status, "exit_code": code, "output": aggregated_output,
                        "was_started": item_id in started_commands}]

      if obj.get("type") == "item.started" and obj.get("item", {}).get("type") == "command_execution":
          item = obj["item"]
          item_id = str(item.get("id") or "")
          cmd = str(item.get("command") or "")
          if item_id:
              started_commands[item_id] = True
          return [{"event": "command_started", "id": item_id, "command": cmd}]

      if re.search(r"(error|failed)", str(obj.get("type") or ""), flags=re.IGNORECASE):
          return [{"event": "error", "text": trim}]

      return []
  ```

- **`extract_session_id(lines)`** ← тело `get_thread_id_from_output()` (строки 245-260). Ищет `{"type":"thread.started","thread_id":"..."}`.

- **`extract_agent_messages(lines)`** ← извлечение `agent_message.text` из Codex JSON строк:
  ```python
  def extract_agent_messages(self, lines):
      texts = []
      for line in lines:
          stripped = line.strip()
          if not (stripped.startswith("{") and stripped.endswith("}")):
              continue
          try:
              obj = json.loads(stripped)
          except Exception:
              continue
          if (obj.get("type") == "item.completed"
              and isinstance(obj.get("item"), dict)
              and obj["item"].get("type") == "agent_message"
              and obj["item"].get("text")):
              texts.append(str(obj["item"]["text"]))
      return texts
  ```

- **`is_turn_completed(line)`** ← проверяет `obj.get("type") == "turn.completed"`.

- **`is_session_not_found_error(output)`** ← текущий regex из `run_forever()`:
  ```python
  def is_session_not_found_error(self, output):
      return bool(re.search(
          r"(?i)(session|thread).*(not found|missing|unknown)|not found.*(session|thread)",
          output,
      ))
  ```

### Верификация этапа 1

```bash
cd C:\CorrisBot\Looper
py -3 -c "from agent_runners import AgentRunner, CodexRunner; r = CodexRunner(); print('OK:', r._executable)"
```
Должен найти codex.exe и напечатать путь.

### Коммит

```
git add Looper/agent_runners.py
git commit -m "feat: add AgentRunner abstraction and CodexRunner implementation"
```

**⏸ CR CHECKPOINT: показать пользователю `agent_runners.py` для ревью.**

---

## Этап 2: Рефакторинг `codex_prompt_fileloop.py` — подключение Runner

**Цель**: заменить hardcoded Codex-логику в `LoopRunner` на делегирование к `AgentRunner`. После этого этапа Codex-функциональность должна работать **идентично** (regression test).

**Файл**: `C:\CorrisBot\Looper\codex_prompt_fileloop.py`

### 2.1. Импорт

Добавить в начало файла:
```python
from agent_runners import AgentRunner, CodexRunner
```

### 2.2. `__init__` (строки 56-78)

**Было**:
```python
def __init__(self, worker_dir, inbox_root, sandbox_mode, approval_policy,
             web_search_enabled, dangerously_bypass_sandbox, codex_bin):
```
**Стало**:
```python
def __init__(self, worker_dir: Path, inbox_root: Path, runner: AgentRunner) -> None:
    self.worker_dir = worker_dir
    self.inbox_root = inbox_root
    self.runner = runner
    self.inbox_root.mkdir(parents=True, exist_ok=True)
    self.legacy_inbox_state_path = self.inbox_root / "loop_state.json"
    self.console_log_path = self.inbox_root / "Console.log"
    self.ansi_enabled = self._try_enable_ansi()
    self.warned_invalid_prompt_paths: set[str] = set()
    self.warned_invalid_watermark_senders: set[str] = set()
```
Удалить поля: `sandbox_mode`, `approval_policy`, `web_search_enabled`, `dangerously_bypass_sandbox`, `codex_bin`, `codex_executable`.

### 2.3. `run_codex()` → `run_agent()` (строки 393-482)

Переименовать метод. **Изменить return-тип** на `tuple[list[str], int, Optional[str]]` — третий элемент = detected session_id.

Изменения внутри:

**Построение команды** (заменить строки 394-417):
```python
cmd, stdin_text = self.runner.build_command(prompt_text, thread_id, self.worker_dir)
```

**Pre-run hook** (перед subprocess.Popen):
```python
self.runner.pre_run_hook()
```

**subprocess.Popen** (строки 419-430) — условный stdin:
```python
stdin_mode = subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL
proc = subprocess.Popen(
    cmd, text=True,
    stdin=stdin_mode,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=self.worker_dir,
    encoding="utf-8", errors="replace", bufsize=1,
)
```

**stdin write** (строки 438-447) — условно:
```python
if stdin_text is not None and proc.stdin:
    try:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        try:
            proc.stdin.close()
        except Exception:
            pass
```

**Парсинг строк** (строка 455) — заменить `self.process_codex_line(line, started_commands)` на:
```python
events = self.runner.parse_output_line(line, started_commands)
for event in events:
    ev = event["event"]
    if ev == "reasoning":
        self.write_console_line(f"[reasoning] {event['text']}", "darkgray")
    elif ev == "agent_message":
        self.write_console_line(f"[{self.worker_dir.name}] {event['text']}", "green")
    elif ev == "command_started":
        self.write_console_line(f"[command] {event['command']} (in_progress)", "darkgray")
    elif ev == "command_completed":
        cmd_text = event.get("command", "")
        status = event.get("status", "")
        code = event.get("exit_code")
        was_started = event.get("was_started", False)
        if was_started:
            if status == "completed":
                self.write_console_line(f"[command] (exit={code})", "darkgray")
            elif status == "failed":
                self.write_console_line(f"[command] (failed, exit={code})", "darkgray")
            elif status:
                self.write_console_line(f"[command] ({status})", "darkgray")
            else:
                self.write_console_line("[command]", "darkgray")
        else:
            if status == "completed":
                self.write_console_line(f"[command] {cmd_text} (exit={code})", "darkgray")
            elif status == "failed":
                self.write_console_line(f"[command] {cmd_text} (failed, exit={code})", "darkgray")
            elif status:
                self.write_console_line(f"[command] {cmd_text} ({status})", "darkgray")
            else:
                self.write_console_line(f"[command] {cmd_text}", "darkgray")
        output = event.get("output")
        if output:
            self.write_console_line(f"[command-output] {output}", "darkgray")
    elif ev == "non_json_error":
        self.write_console_line(event["text"], "red")
    elif ev == "non_json_warning":
        self.write_console_line(event["text"], "darkgray")
    elif ev == "error":
        self.write_console_line(f"[error] {event['text']}", "red")
```

**turn.completed check** (строки 456-462) — заменить на:
```python
if self.runner.is_turn_completed(line):
    saw_turn_completed = True
    break
```

**Оставить без изменений**: логику taskkill (строки 463-474) — для Kimi `is_turn_completed()` всегда False, поэтому taskkill не сработает, и процесс дождёт EOF.

**Error message** (строка 432): `"codex executable not found"` → `"agent executable not found"`.

**Session detection** (в конце метода, перед return). Вся детекция сессии теперь внутри `run_agent()`:
```python
# Определяем session_id из вывода (Codex) или filesystem (Kimi)
detected_session_id = self.runner.extract_session_id(lines)
if detected_session_id is None:
    detected_session_id = self.runner.post_run_hook(lines)

# Cleanup (e.g., temp files for Kimi)
self.runner.post_run_cleanup()

return lines, return_code, detected_session_id
```

### 2.4. `get_thread_id_from_output()` (строки 245-260) → **удалить**

Логика перенесена в `CodexRunner.extract_session_id()`. Больше не нужна — детекция session_id теперь возвращается из `run_agent()`.

### 2.5. `detect_relay_block()` (строки 611-711)

Заменить **только Step 1** (строки 639-655 — прямой парсинг Codex `item.completed`/`agent_message`):

**Было**:
```python
agent_texts: list[str] = []
for file_line in raw_content.splitlines():
    stripped = file_line.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        continue
    try:
        obj = json.loads(stripped)
    except Exception:
        continue
    if (
        obj.get("type") == "item.completed"
        and isinstance(obj.get("item"), dict)
        and obj["item"].get("type") == "agent_message"
        and obj["item"].get("text")
    ):
        agent_texts.append(str(obj["item"]["text"]))
```

**Стало**:
```python
file_lines = raw_content.splitlines()
agent_texts = self.runner.extract_agent_messages(file_lines)
```

Step 2 (YAML relay block parsing, строки 660-711) — **без изменений**.

### 2.6. `run_forever()` (строки 826-868)

Замены:

**Вызов run_agent** (строка 828):
```python
# Было:
lines, exit_code = self.run_codex(prompt_text, thread_id if used_resume else None, result_path)
# Стало:
lines, exit_code, detected_session_id = self.run_agent(prompt_text, thread_id if used_resume else None, result_path)
```

**Resume fallback** (строки 830-843):
```python
if exit_code != 0 and used_resume:
    resume_err = "\n".join(lines)
    if self.runner.is_session_not_found_error(resume_err):
        self.append_text(
            result_path,
            "\nResume failed because session was not found. Starting a new session for this prompt.\n",
        )
        thread_id = None
        self.append_text(result_path, "\n--- Fallback: new session attempt ---\n\n")
        lines, exit_code, detected_session_id = self.run_agent(prompt_text, None, result_path)
```

**Exit code check** (строки 845-847):
```python
if exit_code != 0:
    self.append_text(result_path, f"\nCommand failed with exit code: {exit_code}\n")
    raise RuntimeError(f"agent command failed with exit code {exit_code}")
```

**Session ID update** (строки 849-855) — заменить на:
```python
# "thread_id" field stores agent-specific session ID:
# Codex: thread_id string, Kimi: session UUID.
if detected_session_id:
    thread_id = detected_session_id

if not (thread_id and thread_id.strip()):
    if self.runner.supports_filesystem_session_detection:
        # Kimi: filesystem session detection is best-effort, не критично
        self.write_console_line("[warning] Could not detect Kimi session ID from filesystem.", "darkgray")
    else:
        self.append_text(result_path, "\nCould not detect session_id from agent output.\n")
        raise RuntimeError("session_id was not detected; refusing to continue without explicit session id.")
```

### 2.7. Удалить старые методы

- `resolve_codex_executable()` (строки 351-391) — удалить (перенесён в `CodexRunner`)
- `process_codex_line()` (строки 262-332) — удалить (перенесён в `CodexRunner.parse_output_line`)
- `get_thread_id_from_output()` (строки 245-260) — удалить (заменён на return из `run_agent`)

### 2.8. `parse_args()` (строки 871-917)

Добавить аргумент:
```python
parser.add_argument(
    "--runner",
    default="codex",
    choices=["codex", "kimi"],
    help="CLI agent backend to use (default: codex).",
)
```
Codex-специфичные аргументы (`--sandbox`, `--approval`, `--codex-bin` и т.д.) **оставить** — они нужны для CodexRunner и игнорируются при `--runner kimi`.

### 2.9. `main()` (строки 920-950)

Заменить создание `LoopRunner`:
```python
if args.runner == "codex":
    runner = CodexRunner(
        codex_bin=args.codex_bin,
        sandbox_mode=args.sandbox,
        approval_policy=args.approval,
        web_search_enabled=args.allow_web_search,
        dangerously_bypass_sandbox=args.dangerously_bypass_sandbox,
    )
elif args.runner == "kimi":
    # KimiRunner добавляется на Этапе 3. До реализации --runner kimi даст ImportError.
    from agent_runners import KimiRunner
    runner = KimiRunner()
else:
    raise RuntimeError(f"Unknown runner: {args.runner}")

loop_runner = LoopRunner(
    worker_dir=agent_dir,
    inbox_root=inbox_root,
    runner=runner,
)
```

### Верификация этапа 2

1. `py -3 codex_prompt_fileloop.py --help` — должен показывать `--runner`.
2. `py -3 -c "from codex_prompt_fileloop import LoopRunner"` — без ошибок.
3. **Regression test**: запустить `CodexLoop.bat C:\CorrisBot\Talker`, отправить сообщение через Telegram, убедиться что Talker отвечает нормально.

### Коммит

```
git add Looper/codex_prompt_fileloop.py Looper/agent_runners.py
git commit -m "refactor: delegate agent-specific logic to AgentRunner in LoopRunner"
```

**⏸ CR CHECKPOINT: показать diff `codex_prompt_fileloop.py`.**
**ОБЯЗАТЕЛЬНО: regression test через CodexLoop.bat (Codex должен работать как раньше).**

---

## Этап 3: Реализация `KimiRunner`

**Цель**: добавить поддержку Kimi Code CLI.

**Файлы**: `C:\CorrisBot\Looper\agent_runners.py`

### 3.1. Класс `KimiRunner(AgentRunner)` в `agent_runners.py`

```python
class KimiRunner(AgentRunner):
    KIMI_SESSION_DIR = Path.home() / ".kimi" / "sessions"
    MAX_CMD_LENGTH = 8000  # Windows cmd limit ~8191 chars

    def __init__(self):
        self._executable = self.resolve_executable()
        self._last_temp_file: Optional[str] = None
        self._sessions_before: Optional[set[str]] = None
```

#### `resolve_executable()`

Искать `kimi`, `kimi.exe`, `kimi.cmd` через `shutil.which()`:
```python
def resolve_executable(self) -> str:
    for name in ["kimi", "kimi.exe", "kimi.cmd"]:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(
        "kimi command not found. Install Kimi Code CLI: pip install kimi-cli"
    )
```

#### `build_command(prompt_text, session_id, work_dir)`

```python
def build_command(self, prompt_text, session_id, work_dir):
    cmd = [
        self._executable,
        "--print", "--output-format", "stream-json",
        "--yolo",
        "-w", str(work_dir),
    ]
    if session_id:
        cmd.extend(["--session", session_id])

    # Длинные промпты не влезают в -c (лимит Windows).
    # Записываем во временный файл.
    if len(prompt_text) > self.MAX_CMD_LENGTH:
        import tempfile
        tmp_dir = work_dir / "Temp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            encoding="utf-8", dir=str(tmp_dir),
        )
        tmp.write(prompt_text)
        tmp.close()
        self._last_temp_file = tmp.name
        prompt_arg = f"Read file {tmp.name} and follow all instructions in it exactly."
    else:
        self._last_temp_file = None
        prompt_arg = prompt_text

    cmd.extend(["-c", prompt_arg])
    return cmd, None  # stdin_text=None (Kimi не использует stdin)
```

#### `parse_output_line(line, started_commands)`

Парсит Kimi JSONL. Одна строка может содержать несколько событий.

```python
def parse_output_line(self, line, started_commands):
    trim = line.strip()
    if not trim:
        return []

    if not (trim.startswith("{") and trim.endswith("}")):
        if re.search(r"\b(error|exception|failed|fatal)\b", trim, flags=re.IGNORECASE):
            return [{"event": "non_json_error", "text": trim}]
        elif re.search(r"\bwarn\b", trim, flags=re.IGNORECASE):
            return [{"event": "non_json_warning", "text": trim}]
        return []

    try:
        obj = json.loads(trim)
    except Exception:
        return []

    events = []
    role = obj.get("role")

    if role == "assistant":
        # Парсим content array
        for item in (obj.get("content") or []):
            if item.get("type") == "think" and item.get("think"):
                events.append({"event": "reasoning", "text": item["think"]})
            elif item.get("type") == "text" and item.get("text"):
                events.append({"event": "agent_message", "text": item["text"]})

        # Парсим tool_calls
        for tc in (obj.get("tool_calls") or []):
            func = tc.get("function", {})
            tool_id = tc.get("id", "")
            cmd_name = func.get("name", "")
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except Exception:
                args = {}
            command = args.get("command", cmd_name)
            started_commands[tool_id] = True
            events.append({"event": "command_started", "id": tool_id, "command": command})

    elif role == "tool":
        tool_call_id = obj.get("tool_call_id", "")
        content_parts = obj.get("content") or []
        if isinstance(content_parts, str):
            content_parts = [{"type": "text", "text": content_parts}]
        full_text = " ".join(
            p.get("text", "") for p in content_parts if isinstance(p, dict)
        )
        # Определяем exit_code из <system> тега
        if "<system>Command executed successfully</system>" in full_text:
            exit_code = 0
        elif "<system>" in full_text and "failed" in full_text.lower():
            exit_code = 1
        else:
            exit_code = 0
        # NB: В отличие от CodexRunner, здесь нет полей "command", "status",
        # "was_started" — у Kimi role:tool не содержит эту информацию.
        # Потребитель в run_agent() использует .get() с defaults, поэтому безопасно.
        events.append({
            "event": "command_completed",
            "id": tool_call_id,
            "exit_code": exit_code,
            "output": full_text,
        })

    return events
```

#### `extract_session_id(lines)`

Kimi **не выдаёт** session ID в JSON-выводе:
```python
def extract_session_id(self, lines):
    return None  # Kimi session ID определяется через filesystem (post_run_hook)
```

#### `extract_agent_messages(lines)`

```python
def extract_agent_messages(self, lines):
    texts = []
    for line in lines:
        stripped = line.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            continue
        try:
            obj = json.loads(stripped)
        except Exception:
            continue
        if obj.get("role") == "assistant":
            for item in (obj.get("content") or []):
                if item.get("type") == "text" and item.get("text"):
                    texts.append(item["text"])
    return texts
```

#### `is_turn_completed(line)`

```python
def is_turn_completed(self, line):
    return False  # Kimi завершает процесс по EOF, нет аналога turn.completed
```

#### `is_session_not_found_error(output)`

```python
def is_session_not_found_error(self, output):
    return bool(re.search(
        r"(?i)(session|thread|unknown).*(not found|error|invalid|missing)"
        r"|not found.*(session|thread)",
        output,
    ))
```

#### Filesystem session detection (hooks)

```python
@property
def supports_filesystem_session_detection(self) -> bool:
    return True

def pre_run_hook(self) -> None:
    """Запомнить текущие session UUID для последующей детекции нового."""
    self._sessions_before = self._snapshot_sessions()

def post_run_hook(self, lines: list[str]) -> Optional[str]:
    """Найти новый session UUID через diff файловой системы."""
    if self._sessions_before is None:
        return None
    return self._detect_session_id(self._sessions_before)

def post_run_cleanup(self) -> None:
    """Удалить временный файл промпта (если был создан)."""
    if self._last_temp_file:
        try:
            os.unlink(self._last_temp_file)
        except OSError:
            pass
        self._last_temp_file = None

def _snapshot_sessions(self) -> set[str]:
    """Собрать все session UUID из всех workspace хешей."""
    result = set()
    if not self.KIMI_SESSION_DIR.exists():
        return result
    for hash_dir in self.KIMI_SESSION_DIR.iterdir():
        if hash_dir.is_dir():
            for session_dir in hash_dir.iterdir():
                if session_dir.is_dir():
                    result.add(session_dir.name)
    return result

def _detect_session_id(self, sessions_before: set[str]) -> Optional[str]:
    """Найти новый session UUID, появившийся после вызова kimi."""
    sessions_after = self._snapshot_sessions()
    new_sessions = sessions_after - sessions_before
    if len(new_sessions) == 1:
        return new_sessions.pop()
    if len(new_sessions) > 1:
        # Несколько новых — вернуть самый свежий по mtime
        best = None
        best_mtime = 0.0
        for sid in new_sessions:
            for hash_dir in self.KIMI_SESSION_DIR.iterdir():
                candidate = hash_dir / sid
                if candidate.exists():
                    mtime = candidate.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best = sid
        return best
    # Нет новых сессий — возможно resume существующей.
    # Найти самую свежую по mtime context.jsonl
    best = None
    best_mtime = 0.0
    for hash_dir in self.KIMI_SESSION_DIR.iterdir():
        if not hash_dir.is_dir():
            continue
        for session_dir in hash_dir.iterdir():
            ctx = session_dir / "context.jsonl"
            if ctx.exists():
                mtime = ctx.stat().st_mtime
                if mtime > best_mtime:
                    best_mtime = mtime
                    best = session_dir.name
    return best
```

### Верификация этапа 3

```bash
py -3 -c "from agent_runners import KimiRunner; r = KimiRunner(); print('OK:', r._executable)"
```

Smoke test:
```bash
py -3 codex_prompt_fileloop.py --runner kimi --project-root C:\CorrisBot\Talker --agent-path .
```
Положить тестовый промпт-файл `Prompt_2026_02_16_23_00_00_000.md` с содержимым `скажи "привет"` в `Talker\Prompts\Inbox\TestSender\`. Лупер должен:
1. Подхватить промпт
2. Запустить Kimi
3. Записать result
4. Определить session UUID через filesystem
5. Следующий промпт — resume через `--session <UUID>`

### Коммит

```
git add Looper/agent_runners.py
git commit -m "feat: add KimiRunner implementation for Kimi Code CLI support"
```

**⏸ CR CHECKPOINT: показать `agent_runners.py` (KimiRunner).**

---

## Этап 4: Обновление startup-цепочки

**Цель**: добавить `KimiLoop.bat` и поддержку runner-selection в `StartLoopsInWT.py`.

### 4.1. Создать `KimiLoop.bat`

**Файл**: `C:\CorrisBot\Looper\KimiLoop.bat`

```bat
@echo off
cd /d C:\CorrisBot\Looper
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_root^> [agent_path]
  echo Example: %~nx0 C:\CorrisBot\Talker
  pause
  exit /b 1
)

set "AGENT_PATH=%~2"
if "%AGENT_PATH%"=="" set "AGENT_PATH=."

py -3 .\codex_prompt_fileloop.py --project-root "%~1" --agent-path "%AGENT_PATH%" --runner kimi
pause
```

### 4.2. Обновить `CodexLoop.bat`

**Файл**: `C:\CorrisBot\Looper\CodexLoop.bat`

Текущее содержимое (строка 18):
```bat
py -3 .\codex_prompt_fileloop.py --project-root "%~1" --agent-path "%AGENT_PATH%" --dangerously-bypass-sandbox
```

Добавить `--runner codex` явно:
```bat
py -3 .\codex_prompt_fileloop.py --project-root "%~1" --agent-path "%AGENT_PATH%" --runner codex --dangerously-bypass-sandbox
```

### 4.3. Обновить `StartLoopsInWT.py`

**Файл**: `C:\CorrisBot\Looper\StartLoopsInWT.py`

Изменения:
1. Найти место, где строится путь к bat-файлу для запуска лупера (ищи `CodexLoop.bat` в файле).
2. Добавить чтение опционального поля `"runner"` из конфига агента в `loops.wt.json`.
3. Условно выбирать bat-файл:
   ```python
   runner_type = agent_config.get("runner", "codex")
   if runner_type == "kimi":
       loop_bat = SCRIPT_DIR / "KimiLoop.bat"
   else:
       loop_bat = SCRIPT_DIR / "CodexLoop.bat"
   ```
4. В детекции запущенных процессов: убедиться что ищется `codex_prompt_fileloop.py` (без привязки к конкретному runner).

**Формат конфигурации** — в `loops.wt.json` каждый агент может иметь опциональное поле `"runner"`:
```json
{
  "agents": [
    {"path": ".", "runner": "codex"},
    {"path": "Workers/Worker_001", "runner": "kimi"}
  ]
}
```
Если `runner` не указан — default `"codex"`.

### Верификация этапа 4

1. `KimiLoop.bat C:\CorrisBot\Talker` — запуск Kimi-лупера.
2. `CodexLoop.bat C:\CorrisBot\Talker` — regression, работает как раньше.

### Коммит

```
git add Looper/KimiLoop.bat Looper/CodexLoop.bat Looper/StartLoopsInWT.py
git commit -m "feat: add KimiLoop.bat and runner selection in startup chain"
```

**⏸ CR CHECKPOINT: показать все изменения.**

---

## Этап 5: Обновление документации

**Цель**: обновить инструкции.

### 5.1. `SKILL_AGENT_RUNNER.md`

**Файл**: `C:\CorrisBot\Looper\SKILL_AGENT_RUNNER.md`

Добавить раздел:
```markdown
### Выбор CLI-агента (runner)

По умолчанию используется Codex CLI. Для запуска лупера с Kimi Code CLI:

**Вручную:**
`Looper\KimiLoop.bat "<ProjectPath>" "Workers/Worker_002"`

**Через Windows Terminal (`loops.wt.json`):**
Добавить поле `"runner": "kimi"` для нужного агента в массиве `agents`.

**Поддерживаемые runners:**
- `codex` — OpenAI Codex CLI (по умолчанию)
- `kimi` — Kimi Code CLI (Moonshot AI)
```

### 5.2. `Info.md`

**Файл**: `C:\CorrisBot\Looper\Info.md`

Добавить строку: `Supports multiple CLI agents: Codex CLI, Kimi Code CLI.`

### Коммит

```
git add Looper/SKILL_AGENT_RUNNER.md Looper/Info.md
git commit -m "docs: update agent runner docs with multi-agent support"
```

**⏸ ФИНАЛЬНЫЙ CR: полный ревью всех commit'ов.**

---

## Чеклист

- [ ] Этап 1: `agent_runners.py` с `AgentRunner` ABC + `CodexRunner` → commit → CR
- [ ] Этап 2: рефакторинг `codex_prompt_fileloop.py` → commit → CR + **regression test**
- [ ] Этап 3: `KimiRunner` + filesystem session detection → commit → CR + **smoke test**
- [ ] Этап 4: `KimiLoop.bat` + `StartLoopsInWT.py` → commit → CR
- [ ] Этап 5: документация → commit → финальный CR

## Ограничения и известные риски

1. **Кодировка Windows**: Kimi CLI может выдавать кракозябры вместо кириллицы. Mitigation: `chcp 65001` + `PYTHONIOENCODING=utf-8` в `KimiLoop.bat`.
2. **Session ID filesystem detection**: может дать ложный результат при параллельных запусках Kimi. Mitigation: snapshot ДО вызова, diff ПОСЛЕ.
3. **Длинные промпты**: `-c "text"` ограничен ~8191 символами на Windows. При превышении — автоматически используется temp file.
4. **Kimi resume error format**: точное сообщение об ошибке при невалидном `--session <uuid>` пока неизвестно. `is_session_not_found_error()` использует broad regex. Уточнить экспериментально при первом тесте.
5. **Workspace hash**: алгоритм хеширования `~/.kimi/sessions/{hash}/` неизвестен. `_snapshot_sessions()` обходит это, сканируя все каталоги.
