import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class AgentRunner(ABC):
    """Абстрактный интерфейс CLI-агента."""

    @property
    @abstractmethod
    def runner_name(self) -> str:
        """Уникальное имя runner'а для хранения состояния ('codex', 'kimi')."""
        ...

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


class CodexRunner(AgentRunner):
    @property
    def runner_name(self) -> str:
        return "codex"

    def __init__(
        self,
        codex_bin: Optional[str] = None,
        sandbox_mode: str = "danger-full-access",
        approval_policy: str = "never",
        web_search_enabled: bool = False,
        dangerously_bypass_sandbox: bool = True,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ):
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy
        self.web_search_enabled = web_search_enabled
        self.dangerously_bypass_sandbox = dangerously_bypass_sandbox
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._codex_bin_hint = codex_bin  # сохраняем hint до вызова resolve
        self._executable = self.resolve_executable()

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

    def build_command(self, prompt_text, session_id, work_dir):
        base_cmd = [self._executable, "-C", str(work_dir)]
        if self.dangerously_bypass_sandbox:
            base_cmd.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            base_cmd.extend(["-a", self.approval_policy, "-s", self.sandbox_mode])
        if not self.web_search_enabled:
            base_cmd.extend(["-c", "tools.web_search=false"])
        if self.model:
            base_cmd.extend(["-m", self.model])
        if self.reasoning_effort:
            base_cmd.extend(["-c", f"model_reasoning_effort={self.reasoning_effort}"])
        if session_id:
            cmd = base_cmd + ["exec", "resume", session_id, "--skip-git-repo-check", "--json", "-"]
        else:
            cmd = base_cmd + ["exec", "--skip-git-repo-check", "--json", "-"]
        return cmd, prompt_text  # stdin_text = prompt_text (Codex читает stdin)

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

    def extract_session_id(self, lines):
        for line in lines:
            trim = line.strip()
            if not (trim.startswith("{") and trim.endswith("}")):
                continue
            try:
                obj = json.loads(trim)
            except Exception:
                continue
            if obj.get("type") == "thread.started" and obj.get("thread_id"):
                return str(obj["thread_id"])
        return None

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

    def is_turn_completed(self, line):
        trim = line.strip()
        if not (trim.startswith("{") and trim.endswith("}")):
            return False
        try:
            obj = json.loads(trim)
        except Exception:
            return False
        return obj.get("type") == "turn.completed"

    def is_session_not_found_error(self, output):
        return bool(re.search(
            r"(?i)(session|thread).*(not found|missing|unknown)|not found.*(session|thread)",
            output,
        ))


class KimiRunner(AgentRunner):
    KIMI_SESSION_DIR = Path.home() / ".kimi" / "sessions"
    MAX_CMD_LENGTH = 8000  # Windows cmd limit ~8191 chars

    @property
    def runner_name(self) -> str:
        return "kimi"

    def __init__(self, model: Optional[str] = None):
        self._executable = self.resolve_executable()
        self.model = model
        self._last_temp_file: Optional[str] = None
        self._sessions_before: Optional[set[str]] = None

    def resolve_executable(self) -> str:
        for name in ["kimi", "kimi.exe", "kimi.cmd"]:
            found = shutil.which(name)
            if found:
                return found
        raise RuntimeError(
            "kimi command not found. Install Kimi Code CLI: pip install kimi-cli"
        )

    def build_command(self, prompt_text, session_id, work_dir):
        cmd = [
            self._executable,
            "--print", "--output-format", "stream-json",
            "--yolo",
            "-w", str(work_dir),
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if session_id:
            # Resume existing session
            cmd.extend(["--session", session_id])
        else:
            # Create new session: generate UUID to avoid auto-attaching to existing session
            import uuid
            cmd.extend(["--session", str(uuid.uuid4())])

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

    def extract_session_id(self, lines):
        return None  # Kimi session ID определяется через filesystem (post_run_hook)

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

    def is_turn_completed(self, line):
        return False  # Kimi завершает процесс по EOF, нет аналога turn.completed

    def is_session_not_found_error(self, output):
        return bool(re.search(
            r"(?i)(session|thread|unknown).*(not found|error|invalid|missing)"
            r"|not found.*(session|thread)",
            output,
        ))

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
        # Нет новых сессий — значит Kimi использовал существующую (возможно, /reset)
        # Не возвращаем ничего, чтобы не перезаписать thread_id на старое значение
        return None
