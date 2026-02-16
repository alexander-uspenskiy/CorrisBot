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
