import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_runners import AgentRunner, CodexRunner
from agent_config_resolver import ResolverError, resolve_agent_config

ANSI_COLORS = {
    "gray": "\x1b[37m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "darkgray": "\x1b[90m",
    "darkyellow": "\x1b[33;2m",
}
ANSI_RESET = "\x1b[0m"
DEBUG_LOG_TIMESTAMPS = False
PROMPT_TIMESTAMP_RE = re.compile(
    r"^(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})_"
    r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})_"
    r"(?P<millis>\d{3})(?:_(?P<suffix>[A-Za-z0-9]+))?$"
)
PromptSortKey = tuple[int, int, int, int, int, int, int, str]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_str_ms() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def with_debug_timestamps(text: str) -> str:
    if not DEBUG_LOG_TIMESTAMPS:
        return text
    parts = text.splitlines(keepends=True)
    if not parts:
        return text

    stamped: list[str] = []
    for part in parts:
        content = part.rstrip("\r\n")
        newline = part[len(content):]
        stamped.append(f"[{now_str_ms()}] {content}{newline}")
    return "".join(stamped)


class LoopRunner:
    def __init__(
        self,
        worker_dir: Path,
        inbox_root: Path,
        runner: AgentRunner,
        is_talker_context: bool = False,
        cli_reasoning_effort_pinned: bool = False,
    ) -> None:
        self.worker_dir = worker_dir
        self.inbox_root = inbox_root
        self.runner = runner
        self.launch_runner_name = runner.runner_name
        self.launch_model = getattr(runner, "model", None)
        self.inbox_root.mkdir(parents=True, exist_ok=True)
        self.legacy_inbox_state_path = self.inbox_root / "loop_state.json"
        self.routing_state_path = self.inbox_root / "routing_state.json"
        self.console_log_path = self.inbox_root / "Console.log"
        self.is_talker_context = is_talker_context
        self.cli_reasoning_effort_pinned = cli_reasoning_effort_pinned
        self.ansi_enabled = self._try_enable_ansi()
        self.warned_invalid_prompt_paths: set[str] = set()
        self.warned_invalid_watermark_senders: set[str] = set()
        self.runtime_warned_once_keys: set[str] = set()
        self.last_reasoning_reload_error: Optional[str] = None
        self.relayed_report_ids: set[str] = set()

    @staticmethod
    def _try_enable_ansi() -> bool:
        if os.name != "nt":
            return True
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
                return False
            vt_mode = mode.value | 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if kernel32.SetConsoleMode(handle, vt_mode) == 0:
                return False
            return True
        except Exception:
            return False

    def write_console_line(self, text: str, color: str = "gray") -> None:
        rendered_text = with_debug_timestamps(text)

        if self.ansi_enabled and color in ANSI_COLORS:
            print(f"{ANSI_COLORS[color]}{rendered_text}{ANSI_RESET}", flush=True)
        else:
            print(rendered_text, flush=True)
        line = with_debug_timestamps(f"{text}\n")
        if not DEBUG_LOG_TIMESTAMPS:
            line = f"[{now_str()}] {text}\n"
        with self.console_log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def get_sender_dirs(self) -> list[Path]:
        if not self.inbox_root.exists():
            return []
        return sorted(p for p in self.inbox_root.iterdir() if p.is_dir())

    def warn_runtime_once(self, key: str, text: str, color: str = "darkyellow") -> None:
        if key in self.runtime_warned_once_keys:
            return
        self.runtime_warned_once_keys.add(key)
        self.write_console_line(text, color)

    def read_configured_runner(self) -> Optional[str]:
        runner_path = self.worker_dir / "agent_runner.json"
        if not runner_path.is_file():
            return None
        try:
            payload = json.loads(runner_path.read_text(encoding="utf-8"))
        except Exception:
            self.warn_runtime_once(
                "agent_runner_invalid_json",
                f"[warning] agent_runner.json is invalid; runner change cannot be checked: {runner_path}",
            )
            return None
        if not isinstance(payload, dict):
            self.warn_runtime_once(
                "agent_runner_not_object",
                f"[warning] agent_runner.json must contain a JSON object: {runner_path}",
            )
            return None
        value = payload.get("runner")
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        return None

    def refresh_runtime_apply_rules(self) -> None:
        configured_runner = self.read_configured_runner()
        if configured_runner and configured_runner != self.launch_runner_name:
            self.warn_runtime_once(
                f"runner_changed_{configured_runner}",
                (
                    "[warning] runner change applies next launch "
                    f"(current={self.launch_runner_name}, configured={configured_runner})"
                ),
            )

        if self.launch_runner_name != "codex":
            return

        if self.cli_reasoning_effort_pinned:
            self.warn_runtime_once(
                "reasoning_pinned_cli",
                "[warning] CLI --reasoning-effort is pinned for this process; profile hot-reload is ignored.",
            )
            return

        try:
            resolved = resolve_agent_config(
                agent_dir=self.worker_dir,
                cli_runner=self.launch_runner_name,
                cli_model=self.launch_model,
            )
        except ResolverError as exc:
            if self.last_reasoning_reload_error != exc.code:
                self.write_console_line(
                    f"[warning] reasoning hot-reload skipped: {exc.code}",
                    "darkyellow",
                )
                self.last_reasoning_reload_error = exc.code
            return

        self.last_reasoning_reload_error = None
        effective_reasoning = str(resolved["effective"]["reasoning"] or "").strip()
        new_reasoning = effective_reasoning or None
        current_reasoning = getattr(self.runner, "reasoning_effort", None)
        if current_reasoning == new_reasoning:
            return
        setattr(self.runner, "reasoning_effort", new_reasoning)
        source_reasoning = str(resolved["source"]["reasoning"])
        rendered_reasoning = effective_reasoning or ""
        self.write_console_line(
            f"[runtime] codex reasoning_effort updated to '{rendered_reasoning}' (source={source_reasoning})",
            "darkgray",
        )

    @staticmethod
    def parse_prompt_marker(marker: str) -> Optional[PromptSortKey]:
        marker = marker.strip()
        if not marker:
            return None

        match = PROMPT_TIMESTAMP_RE.fullmatch(marker)
        if not match:
            return None

        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second"))
        millis = int(match.group("millis"))
        suffix = match.group("suffix") or ""

        try:
            datetime(year, month, day, hour, minute, second, millis * 1000)
        except ValueError:
            return None

        return year, month, day, hour, minute, second, millis, suffix

    def read_sender_state(self, sender_dir: Path) -> tuple[Optional[str], str, str]:
        state_path = sender_dir / "loop_state.json"
        if not state_path.exists():
            return None, "", ""

        try:
            raw = state_path.read_text(encoding="utf-8")
            obj = json.loads(raw)
            # Per-runner session key: "thread_id_codex" или "thread_id_kimi"
            runner_key = f"thread_id_{self.runner.runner_name}"
            thread_id = obj.get(runner_key)
            # Миграция: если per-runner ключа нет, но есть старый "thread_id" —
            # считать его за codex (backward compatibility)
            if thread_id is None and self.runner.runner_name == "codex":
                thread_id = obj.get("thread_id")
            last_processed_marker = str(
                obj.get("last_processed_marker") or obj.get("last_processed_timestamp") or ""
            ).strip()
            updated_at = str(obj.get("updated_at") or "")
            return thread_id, last_processed_marker, updated_at
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_path = sender_dir / f"loop_state.corrupt.{stamp}.json"
            try:
                state_path.replace(corrupt_path)
            except Exception:
                pass
            self.write_console_line(
                f"[warning] Sender state is invalid JSON. Moved to '{corrupt_path}'. Starting sender state from empty."
                ,
                "darkgray",
            )
            return None, "", ""

    def write_sender_state(
        self, sender_dir: Path, thread_id: Optional[str], last_processed_marker: str
    ) -> None:
        state_path = sender_dir / "loop_state.json"
        runner_key = f"thread_id_{self.runner.runner_name}"

        # Прочитать существующий state, чтобы сохранить thread_id другого runner'а
        existing = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Обновить только свой ключ, сохранив чужие
        payload = dict(existing)
        payload[runner_key] = thread_id
        payload["last_processed_marker"] = last_processed_marker
        payload["updated_at"] = now_str()

        tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(state_path)

    def read_legacy_inbox_state(self) -> tuple[Optional[str], dict[str, str]]:
        if not self.legacy_inbox_state_path.exists():
            return None, {}

        try:
            raw = self.legacy_inbox_state_path.read_text(encoding="utf-8")
            obj = json.loads(raw)
            # Per-runner session key с fallback для backward compatibility
            runner_key = f"thread_id_{self.runner.runner_name}"
            thread_id = obj.get(runner_key)
            if thread_id is None and self.runner.runner_name == "codex":
                thread_id = obj.get("thread_id")
            sender_last_processed_marker: dict[str, str] = {}
            if isinstance(obj.get("sender_last_processed_marker"), dict):
                for sender, marker in obj["sender_last_processed_marker"].items():
                    normalized = str(marker or "").strip()
                    if normalized:
                        sender_last_processed_marker[str(sender)] = normalized

            return thread_id, sender_last_processed_marker
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_path = self.inbox_root / f"loop_state.corrupt.{stamp}.json"
            try:
                self.legacy_inbox_state_path.replace(corrupt_path)
            except Exception:
                pass
            self.write_console_line(
                f"[warning] Legacy inbox state is invalid JSON. Moved to '{corrupt_path}'. Ignoring it."
                ,
                "darkgray",
            )
            return None, {}

    def read_routing_state(self) -> tuple[str, str, str]:
        if not self.routing_state_path.exists():
            return "", "", ""

        try:
            raw = self.routing_state_path.read_text(encoding="utf-8")
            obj = json.loads(raw)
            user_sender_id = str(obj.get("user_sender_id") or "").strip()
            updated_at = str(obj.get("updated_at") or "")
            updated_by = str(obj.get("updated_by") or "")
            return user_sender_id, updated_at, updated_by
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt_path = self.inbox_root / f"routing_state.corrupt.{stamp}.json"
            try:
                self.routing_state_path.replace(corrupt_path)
            except Exception:
                pass
            self.write_console_line(
                f"[warning] Routing state is invalid JSON. Moved to '{corrupt_path}'. Starting with empty routing state.",
                "darkgray",
            )
            return "", "", ""

    def write_routing_state(self, user_sender_id: str, updated_by: str) -> None:
        normalized_updated_by = updated_by.strip()
        if normalized_updated_by not in {"bootstrap", "operator_command", "reset"}:
            raise ValueError(f"invalid updated_by for routing state: {updated_by!r}")
        payload = {
            "user_sender_id": user_sender_id.strip(),
            "updated_at": now_str(),
            "updated_by": normalized_updated_by,
        }
        tmp_path = self.routing_state_path.with_suffix(self.routing_state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.routing_state_path)

    def wait_for_file_ready(self, file_path: Path) -> None:
        stable_rounds = 0
        last_size = -1

        while stable_rounds < 2:
            time.sleep(0.25)

            if not file_path.exists():
                stable_rounds = 0
                last_size = -1
                continue

            try:
                current_size = file_path.stat().st_size
            except Exception:
                stable_rounds = 0
                last_size = -1
                continue

            can_read = False
            try:
                with file_path.open("rb"):
                    can_read = True
            except Exception:
                can_read = False

            if can_read and current_size == last_size:
                stable_rounds += 1
            else:
                stable_rounds = 0

            last_size = current_size

    @classmethod
    def build_loop_prompt(
        cls,
        user_prompt: str,
        sender_id: str,
        user_sender_id: str,
        is_talker_context: bool,
    ) -> str:
        import route_contract_utils
        
        is_operational = False
        has_routing_contract_block = bool(route_contract_utils._scan_markdown_block(user_prompt, "Routing-Contract:"))
        if has_routing_contract_block and not sender_id.startswith("tg_"):
            try:
                route_contract_utils.extract_route_meta_fields(user_prompt)
                is_operational = True
            except Exception:
                pass

        routing_contract: dict[str, str] | None = None
        if is_operational:
            routing_contract = route_contract_utils.extract_routing_contract_fields(user_prompt)
            user_prompt = route_contract_utils.remove_markdown_block(user_prompt, "Routing-Contract:")

        # Core looper policy rules are centralized in each agent's AGENTS.md Read chain.
        # Keep only runtime execution
        # constraints in this injected prompt to avoid duplicate sources of truth.
        routing_rules = ""
        routing_context = ""
        if is_talker_context:
            fixed_user_sender = user_sender_id or "(not set)"
            routing_rules = (
                "- Talker relay contract: use `Fixed User Sender ID` as relay target exactly.\n"
                "- If `Fixed User Sender ID` is unknown, report routing protocol error explicitly; never guess.\n"
            )
            routing_context = f"Fixed User Sender ID: {fixed_user_sender}\n\n"
            
        safe_projection = ""
        if is_operational and routing_contract is not None:
            proj_lines = [
                f"- RouteSessionID: {routing_contract.get('RouteSessionID', '')}",
                f"- ProjectTag: {routing_contract.get('ProjectTag', '')}",
            ]
            if not is_talker_context:
                # Deterministic role inference without path-name heuristics:
                # prompts sent by Orchestrator to workers use SenderID == OrchestratorSenderID.
                # In all other non-Talker operational contexts, path roots are needed by orchestrator logic.
                if sender_id != routing_contract.get("OrchestratorSenderID", ""):
                    proj_lines.append(f"- AgentsRoot: {routing_contract.get('AgentsRoot', '')}")
            safe_projection = "Transport Context (Read-Only):\n" + "\n".join(proj_lines) + "\n\n"
            
        # Keep runtime injection minimal — all policy rules live in AGENTS.md.
        # Only inject per-iteration dynamic values here.
        rules = (
            "Process exactly one incoming prompt. Follow AGENTS.md rules strictly.\n"
            f"{routing_rules}"
            f"Sender ID: {sender_id}\n\n"
            f"{routing_context}"
            f"{safe_projection}"
            "Incoming prompt:\n"
        )
        return f"{rules}\n{user_prompt}"

    def run_agent(self, prompt_text: str, thread_id: Optional[str], result_path: Path) -> tuple[list[str], int, Optional[str]]:
        cmd, stdin_text = self.runner.build_command(prompt_text, thread_id, self.worker_dir)

        self.runner.pre_run_hook()

        try:
            stdin_mode = subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL
            proc = subprocess.Popen(
                cmd,
                text=True,
                stdin=stdin_mode,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.worker_dir,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"agent executable not found: {cmd[0]}") from exc

        lines: list[str] = []
        started_commands: dict[str, bool] = {}
        saw_turn_completed = False
        has_valid_json_action = False
        with result_path.open("a", encoding="utf-8") as result_file:
            if stdin_text is not None and proc.stdin:
                try:
                    proc.stdin.write(stdin_text)
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    # Process may exit before accepting stdin; continue collecting stdout/stderr.
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
            if proc.stdout:
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\r\n")
                    lines.append(line)
                    result_file.write(with_debug_timestamps(raw_line))
                    # Keep Result.md observable for external stream readers (gateway).
                    result_file.flush()
                    events = self.runner.parse_output_line(line, started_commands)
                    for event in events:
                        ev = event["event"]
                        if ev in ("reasoning", "agent_message", "command_started", "command_completed"):
                            has_valid_json_action = True
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
                    if self.runner.is_turn_completed(line):
                        saw_turn_completed = True
                        break
            if saw_turn_completed and proc.poll() is None:
                # Turn is already complete; stop codex wrapper process tree so the loop can continue.
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass

            if saw_turn_completed:
                # After turn completion we treat this iteration as successful even if forced stop returned non-zero.
                polled = proc.poll()
                return_code = 0 if polled is None else (0 if polled != 0 else polled)
            else:
                return_code = proc.wait()

            if return_code == 0 and not has_valid_json_action:
                self.write_console_line("[error] Process exited with 0 but no valid JSON actions/messages were produced.", "red")
                non_json_lines = [l for l in lines if not (l.strip().startswith("{") and l.strip().endswith("}"))]
                
                error_body = "[System Fail-Closed]\nThe CLI agent process exited successfully (0) but failed to generate any valid JSON payload (e.g. agent message or tool command)."
                if non_json_lines:
                    self.write_console_line("Raw output:\n" + "\n".join(non_json_lines), "darkgray")
                    error_body += "\n\nRaw CLI Output:\n" + "\n".join(non_json_lines)
                
                # Emit to Result.md so the Telegram Gateway can relay this message to the user!
                self.append_gateway_agent_message(result_path, error_body)
                
                return_code = 1

        # Determine session_id from output (Codex) or filesystem (Kimi)
        detected_session_id = self.runner.extract_session_id(lines)
        if detected_session_id is None:
            detected_session_id = self.runner.post_run_hook(lines)

        # Cleanup (e.g., temp files for Kimi)
        self.runner.post_run_cleanup()

        return lines, return_code, detected_session_id

    def append_result_header(self, result_path: Path, prompt_name: str) -> None:
        # Runner metadata for gateway to select correct parser
        header = (
            f"<!-- runner: {self.runner.runner_name} -->\n"
            f"# Codex Result for {prompt_name}\n\n"
            f"Started: {now_str()}\n\n"
        )
        result_path.write_text(header, encoding="utf-8")

    def append_lines(self, path: Path, lines: list[str]) -> None:
        if not lines:
            return
        with path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(with_debug_timestamps(f"{line}\n"))

    def append_text(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(with_debug_timestamps(text))

    def append_gateway_agent_message(self, path: Path, text: str) -> None:
        """Append one runner-compatible agent_message JSON line for gateway delivery."""
        payload_text = text.strip()
        if not payload_text:
            return

        if self.runner.runner_name == "codex":
            payload = {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": payload_text,
                },
            }
        elif self.runner.runner_name == "kimi":
            payload = {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": payload_text,
                    }
                ],
            }
        else:
            return

        self.append_text(path, json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def get_first_nonempty_line(user_prompt_text: str) -> Optional[str]:
        for raw_line in user_prompt_text.splitlines():
            # Tolerate UTF-8 BOM from some writers without modifying prompt text for LLM.
            line = raw_line.lstrip("\ufeff").strip()
            if not line:
                continue
            return line
        return None

    @classmethod
    def parse_stop_command(cls, user_prompt_text: str) -> Optional[str]:
        line = cls.get_first_nonempty_line(user_prompt_text)
        if line is None:
            return None
        normalized = " ".join(line.lower().split())
        if normalized in {"/looper stop", "/loop stop"}:
            return "stop"
        return None

    @classmethod
    def parse_routing_command(cls, user_prompt_text: str) -> Optional[tuple[str, str]]:
        line = cls.get_first_nonempty_line(user_prompt_text)
        if line is None:
            return None

        normalized = " ".join(line.split())
        lowered = normalized.lower()
        if lowered == "/routing show":
            return "show", ""
        if lowered == "/routing clear":
            return "clear", ""

        match = re.fullmatch(r"/routing\s+set-user(?:\s+(.*))?", normalized, flags=re.IGNORECASE)
        if match:
            return "set_user", (match.group(1) or "").strip()
        return None

    def handle_routing_command(
        self,
        command_name: str,
        command_arg: str,
        result_path: Path,
        user_sender_id: str,
        routing_updated_at: str,
        routing_updated_by: str,
    ) -> tuple[str, str, str]:
        if command_name == "show":
            message_text = (
                "Routing state\n"
                f"- user_sender_id: {user_sender_id or '(unset)'}\n"
                f"- updated_at: {routing_updated_at or '(never)'}\n"
                f"- updated_by: {routing_updated_by or '(unknown)'}"
            )
            self.append_text(
                result_path,
                message_text + "\n",
            )
            self.append_gateway_agent_message(result_path, message_text)
            self.write_console_line(
                f"[routing] show user_sender_id='{user_sender_id or ''}' updated_by='{routing_updated_by or ''}'",
                "darkyellow",
            )
            return user_sender_id, routing_updated_at, routing_updated_by

        if command_name == "clear":
            self.write_routing_state("", "operator_command")
            message_text = "Routing state updated\n- user_sender_id: (unset)\n- updated_by: operator_command"
            self.append_text(
                result_path,
                message_text + "\n",
            )
            self.append_gateway_agent_message(result_path, message_text)
            self.write_console_line("[routing] user_sender_id cleared by operator command", "yellow")
            return "", now_str(), "operator_command"

        if command_name == "set_user":
            if not command_arg or not self._is_valid_target_name(command_arg):
                message_text = f"[routing] protocol error: invalid user_sender_id '{command_arg}'."
                self.append_text(
                    result_path,
                    message_text + "\n",
                )
                self.append_gateway_agent_message(result_path, message_text)
                self.write_console_line(
                    f"[routing] protocol error: invalid user_sender_id '{command_arg}'",
                    "red",
                )
                return user_sender_id, routing_updated_at, routing_updated_by

            self.write_routing_state(command_arg, "operator_command")
            message_text = (
                "Routing state updated\n"
                f"- user_sender_id: {command_arg}\n"
                "- updated_by: operator_command"
            )
            self.append_text(
                result_path,
                message_text + "\n",
            )
            self.append_gateway_agent_message(result_path, message_text)
            self.write_console_line(
                f"[routing] user_sender_id set to '{command_arg}' by operator command",
                "yellow",
            )
            return command_arg, now_str(), "operator_command"

        message_text = f"[routing] protocol error: unsupported command '{command_name}'."
        self.append_text(result_path, message_text + "\n")
        self.append_gateway_agent_message(result_path, message_text)
        self.write_console_line(f"[routing] protocol error: unsupported command '{command_name}'", "red")
        return user_sender_id, routing_updated_at, routing_updated_by

    def warn_invalid_prompt_once(self, prompt_path: Path) -> None:
        warning_key = str(prompt_path).lower()
        if warning_key in self.warned_invalid_prompt_paths:
            return
        self.warned_invalid_prompt_paths.add(warning_key)
        self.write_console_line(
            f"[warning] Skipping prompt with invalid timestamp format: {prompt_path}",
            "darkyellow",
        )

    def pick_sender_candidate(
        self, sender_dir: Path, last_processed_marker: str
    ) -> Optional[tuple[PromptSortKey, Path, str]]:
        last_processed_key: Optional[PromptSortKey] = None
        if last_processed_marker:
            last_processed_key = self.parse_prompt_marker(last_processed_marker)
            if last_processed_key is None:
                sender_key = sender_dir.name.lower()
                if sender_key not in self.warned_invalid_watermark_senders:
                    self.warned_invalid_watermark_senders.add(sender_key)
                    self.write_console_line(
                        f"[warning] Sender state watermark is invalid for '{sender_dir.name}': "
                        f"'{last_processed_marker}'. Treating as empty watermark.",
                        "darkyellow",
                    )
                last_processed_key = None

        candidates: list[tuple[PromptSortKey, Path, str]] = []
        for child in sender_dir.iterdir():
            if not child.is_file():
                continue

            file_name = child.name
            if not (file_name.startswith("Prompt_") and file_name.endswith(".md")):
                continue
            if file_name.endswith("_Result.md"):
                continue

            marker = file_name[len("Prompt_"):-3]
            marker_key = self.parse_prompt_marker(marker)
            if marker_key is None:
                self.warn_invalid_prompt_once(child)
                continue

            if last_processed_key is not None and marker_key <= last_processed_key:
                continue

            candidates.append((marker_key, child, marker))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
        return candidates[0]

    def pick_next_prompt(
        self, sender_last_processed_marker: dict[str, str]
    ) -> Optional[tuple[str, Path, Path, str]]:
        candidates: list[tuple[PromptSortKey, str, Path, Path, str]] = []
        for sender_dir in self.get_sender_dirs():
            sender_id = sender_dir.name
            if sender_id not in sender_last_processed_marker:
                _, last_marker, _ = self.read_sender_state(sender_dir)
                sender_last_processed_marker[sender_id] = last_marker

            sender_candidate = self.pick_sender_candidate(
                sender_dir, sender_last_processed_marker.get(sender_id, "")
            )
            if sender_candidate is None:
                continue

            marker_key, prompt_path, marker = sender_candidate
            candidates.append((marker_key, sender_id, sender_dir, prompt_path, marker))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        _, sender_id, sender_dir, prompt_path, marker = candidates[0]
        return sender_id, sender_dir, prompt_path, marker

    def get_waiting_sender_messages(self, sender_last_processed_marker: dict[str, str]) -> list[str]:
        messages: list[str] = []
        for sender_dir in self.get_sender_dirs():
            sender_id = sender_dir.name
            if sender_id not in sender_last_processed_marker:
                _, last_marker, _ = self.read_sender_state(sender_dir)
                sender_last_processed_marker[sender_id] = last_marker

            marker = sender_last_processed_marker.get(sender_id, "").strip()
            if marker:
                messages.append(f"Waiting: {sender_dir} (after {marker})")
            else:
                messages.append(f"Waiting: {sender_dir}")
        return messages

    def detect_relay_block(self, result_path: Path) -> Optional[tuple[str, str]]:
        """Detect YAML relay block in a Result file and extract target + content.

        Result files are sequences of JSON lines from Codex.  The YAML relay
        block lives inside the ``"text"`` field of ``agent_message`` JSON
        events, **not** as standalone file lines.  We therefore:

        1. Parse each file line as JSON.
        2. Collect ``agent_message`` texts.
        3. Split collected text into lines and search for the relay block.

        YAML block format (inside agent_message text)::

            ---
            type: relay
            target: <UserSenderID>
            from: <sender_id>
            ---
            [Relay content here]

        Returns ``(target, relay_content)`` if a relay block is found,
        ``None`` otherwise.
        """
        try:
            raw_content = result_path.read_text(encoding="utf-8")
        except Exception:
            return None

        # --- Step 1: extract agent_message texts from JSON lines ----------
        file_lines = raw_content.splitlines()
        agent_texts = self.runner.extract_agent_messages(file_lines)

        if not agent_texts:
            return None

        # --- Step 2: search for YAML relay block in agent_message text ----
        # Combine all agent_message fragments (usually one, but be safe).
        combined = "\n".join(agent_texts)
        lines = combined.splitlines()

        in_block = False
        block_lines: list[str] = []
        metadata: dict[str, str] = {}
        closing_idx = -1

        for i, line in enumerate(lines):
            if line.strip() == "---":
                if not in_block:
                    in_block = True
                    block_lines = []
                    metadata = {}
                    continue
                else:
                    # Closing --- — validate collected metadata.
                    is_relay = False
                    for bl in block_lines:
                        key_line = bl.strip()
                        if key_line.startswith("type:"):
                            if key_line.split(":", 1)[1].strip() == "relay":
                                is_relay = True
                        elif key_line.startswith("target:"):
                            metadata["target"] = key_line.split(":", 1)[1].strip()
                        elif key_line.startswith("from:"):
                            metadata["from"] = key_line.split(":", 1)[1].strip()

                    if is_relay and "target" in metadata:
                        closing_idx = i
                        break
                    # Not a valid relay block — reset and keep searching.
                    in_block = False
                    block_lines = []
                    metadata = {}
                    continue

            if in_block:
                block_lines.append(line)

        if closing_idx == -1 or "target" not in metadata:
            return None

        # Relay content: everything after closing --- in combined text.
        relay_content_lines = lines[closing_idx + 1:]
        # Trim leading blank lines.
        while relay_content_lines and not relay_content_lines[0].strip():
            relay_content_lines.pop(0)

        return metadata["target"], "\n".join(relay_content_lines)
    
    def _is_valid_target_name(self, target: str) -> bool:
        """Validate target folder name - must be a simple name, not a path."""
        if not target or target.strip() != target:
            return False
        # Disallow path traversal and directory separators
        if ".." in target or "/" in target or "\\" in target:
            return False
        # Must not be empty or only whitespace after stripping
        if not target.strip():
            return False
        return True

    def validate_relay_target(
        self,
        target: str,
        user_sender_id: str,
    ) -> Optional[str]:
        """Validate relay target and enforce Talker routing contract."""
        normalized = target.strip()
        if not self._is_valid_target_name(normalized):
            self.write_console_line(f"[relay] protocol error: invalid target name '{target}'.", "red")
            return None

        if not self.is_talker_context:
            return normalized

        if not user_sender_id:
            self.write_console_line(
                "[relay] protocol error: user_sender_id is unset. Relay delivery blocked.",
                "red",
            )
            return None
        if normalized != user_sender_id:
            self.write_console_line(
                f"[relay] protocol error: target mismatch. got='{normalized}', expected='{user_sender_id}'. Relay delivery blocked.",
                "red",
            )
            return None
        return normalized
    
    def handle_relay_delivery(
        self,
        target: str,
        relay_content: str,
        user_sender_id: str,
    ) -> None:
        """Create relay Result file in target inbox.
        
        Creates a file named Prompt_<timestamp>_relay_Result.md in the target inbox.
        The _relay suffix allows Gateway to identify it while Looper ignores it
        (Looper skips files ending with _Result.md).
        """
        validated_target = self.validate_relay_target(target, user_sender_id)
        if not validated_target:
            return
            
        has_message_meta_header = any(
            line.strip() == "Message-Meta:" for line in relay_content.splitlines()
        )
        try:
            from route_contract_utils import extract_message_meta_fields
            msg_meta = extract_message_meta_fields(relay_content)
        except Exception as exc:
            if has_message_meta_header:
                self.write_console_line(
                    f"[relay] blocked: invalid Message-Meta. ({exc})",
                    "red",
                )
                return
            self.write_console_line(
                f"[relay] Message-Meta not found, applying legacy compatibility mode. ({exc})",
                "darkgray",
            )
            msg_meta = {}
            
        msg_class = msg_meta.get("MessageClass", "")
        if msg_class == "trace":
            is_trace_enabled = os.environ.get("TRACE_RELAY_ENABLED", "false").lower() == "true"
            if not is_trace_enabled:
                self.write_console_line(f"[relay] blocked: trace relay is disabled (Message-Meta.ReportID={msg_meta.get('ReportID')})", "darkgray")
                return

        report_id = msg_meta.get("ReportID", "")
        if report_id:
            if report_id in self.relayed_report_ids:
                self.write_console_line(f"[relay] blocked: duplicate ReportID '{report_id}' detected.", "darkgray")
                return
            self.relayed_report_ids.add(report_id)
        
        target_inbox = self.inbox_root / validated_target
        target_inbox.mkdir(parents=True, exist_ok=True)
        
        # Generate filename: Prompt_<timestamp>_relay_Result.md
        # Use consistent timestamp format matching other parts of the codebase
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S_%f")[:-3]  # milliseconds
        filename = f"Prompt_{timestamp}_relay_Result.md"
        relay_path = target_inbox / filename
        
        # Write relay content with error handling
        try:
            relay_path.write_text(
                (
                    f"<!-- runner: {self.runner.runner_name} -->\n"
                    "# Relay Result\n\n"
                    f"Started: {now_str()}\n\n"
                ),
                encoding="utf-8",
            )
            self.append_gateway_agent_message(relay_path, relay_content)
            self.append_text(relay_path, f"\nFinished: {now_str()}\n")
            self.write_console_line(f"[relay] Delivered to {validated_target}: {filename}")
        except OSError as e:
            self.write_console_line(f"[relay] ERROR: Failed to write relay file to {validated_target}: {e}", "red")
    
    def run_forever(self) -> None:
        self.write_console_line(f"Watching inbox root: {self.inbox_root}")
        sender_last_processed_marker: dict[str, str] = {}
        thread_id: Optional[str] = None
        best_thread_updated_at = ""
        user_sender_id = ""
        routing_updated_at = ""
        routing_updated_by = ""
        if self.is_talker_context:
            if not self.routing_state_path.exists():
                self.write_routing_state("", "bootstrap")
            user_sender_id, routing_updated_at, routing_updated_by = self.read_routing_state()
            if user_sender_id:
                self.write_console_line(
                    f"[routing] Loaded user_sender_id: '{user_sender_id}'",
                    "darkyellow",
                )
            else:
                self.write_console_line(
                    "[routing] user_sender_id is not set. Relay delivery is blocked until `/routing set-user <SenderID>`.",
                    "darkyellow",
                )

        # --- Signal File Check Helper ---
        def check_reset_signal():
            signal_path = self.inbox_root / "reset_signal.json"
            if signal_path.exists():
                try:
                    self.write_console_line("[info] Reset signal detected. Clearing session state.", "yellow")
                    # Clear in-memory state
                    nonlocal thread_id, sender_last_processed_marker, user_sender_id, routing_updated_at, routing_updated_by
                    thread_id = None
                    sender_last_processed_marker.clear()
                    if self.is_talker_context:
                        user_sender_id = ""
                        self.write_routing_state("", "reset")
                        routing_updated_at = now_str()
                        routing_updated_by = "reset"
                    # Remove the signal file
                    try:
                        signal_path.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    self.write_console_line(f"[error] Failed to process reset signal: {e}", "red")

        for sender_dir in self.get_sender_dirs():
            sender_id = sender_dir.name
            state_thread_id, last_processed_marker, updated_at = self.read_sender_state(sender_dir)
            sender_last_processed_marker[sender_id] = last_processed_marker
            if state_thread_id and (not best_thread_updated_at or updated_at >= best_thread_updated_at):
                thread_id = state_thread_id
                best_thread_updated_at = updated_at

        legacy_thread_id, legacy_last_marker_map = self.read_legacy_inbox_state()
        for sender_id, marker in legacy_last_marker_map.items():
            sender_last_processed_marker.setdefault(sender_id, marker)

        if (not thread_id) and legacy_thread_id:
            thread_id = legacy_thread_id

        # Check signal AFTER loading state to ensure reset overrides stale disk state
        check_reset_signal()

        waiting_logged = False

        while True:
            check_reset_signal()
            picked = self.pick_next_prompt(sender_last_processed_marker)
            if picked is None:
                if not waiting_logged:
                    waiting_messages = self.get_waiting_sender_messages(sender_last_processed_marker)
                    if waiting_messages:
                        for message in waiting_messages:
                            self.write_console_line(message, "darkyellow")
                    else:
                        self.write_console_line(f"Waiting: no sender directories in {self.inbox_root}", "darkyellow")
                    waiting_logged = True
                time.sleep(0.5)
                continue

            waiting_logged = False
            sender_id, sender_dir, prompt_path, marker = picked
            self.write_console_line(f"Selected: {prompt_path}", "yellow")
            prompts_dir = prompt_path.parent
            prompt_name = prompt_path.name

            self.wait_for_file_ready(prompt_path)

            result_name = f"{prompt_path.stem}_Result.md"
            result_path = prompts_dir / result_name

            self.write_console_line(f"Processing {sender_id}/{prompt_name}")
            self.append_result_header(result_path, prompt_name)
            self.refresh_runtime_apply_rules()

            user_prompt_text = prompt_path.read_text(encoding="utf-8")
            stop_command = self.parse_stop_command(user_prompt_text)
            if stop_command == "stop":
                self.append_text(
                    result_path,
                    (
                        "Looper control command received: stop\n"
                        f"Sender: {sender_id}\n"
                        f"Stopped: {now_str()}\n"
                    ),
                )
                sender_last_processed_marker[sender_id] = marker
                self.write_sender_state(sender_dir, thread_id, marker)
                self.write_console_line(
                    f"Stop command received from {sender_id}/{prompt_name}. Exiting loop.",
                    "yellow",
                )
                return

            if self.is_talker_context:
                routing_command = self.parse_routing_command(user_prompt_text)
                if routing_command is not None:
                    command_name, command_arg = routing_command
                    user_sender_id, routing_updated_at, routing_updated_by = self.handle_routing_command(
                        command_name=command_name,
                        command_arg=command_arg,
                        result_path=result_path,
                        user_sender_id=user_sender_id,
                        routing_updated_at=routing_updated_at,
                        routing_updated_by=routing_updated_by,
                    )
                    self.append_text(result_path, f"\nFinished: {now_str()}\n")
                    sender_last_processed_marker[sender_id] = marker
                    self.write_sender_state(sender_dir, thread_id, marker)
                    continue

            prompt_text = self.build_loop_prompt(
                user_prompt_text,
                sender_id,
                user_sender_id,
                self.is_talker_context,
            )
            used_resume = bool(thread_id and thread_id.strip())

            lines, exit_code, detected_session_id = self.run_agent(prompt_text, thread_id if used_resume else None, result_path)

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

            if exit_code != 0:
                self.append_text(result_path, f"\nCommand failed with exit code: {exit_code}\n")
                raise RuntimeError(f"agent command failed with exit code {exit_code}")

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

            # --- Relay bypass: auto-deliver relay content to target inbox ---
            # NOTE: Relay is processed AFTER thread_id validation to avoid duplicate
            # deliveries if looper crashes/restarts due to missing thread_id.
            relay_result = self.detect_relay_block(result_path)
            if relay_result is not None:
                relay_target, relay_content = relay_result
                self.handle_relay_delivery(relay_target, relay_content, user_sender_id)

            self.append_text(result_path, f"\nFinished: {now_str()}\n")

            sender_last_processed_marker[sender_id] = marker
            self.write_sender_state(sender_dir, thread_id, marker)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loop: waits for Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md files in agent inbox and processes them via codex."
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Path to project root.",
    )
    parser.add_argument(
        "--agent-path",
        help=(
            "Agent directory path. Can be absolute or relative to project root "
            "(for example, Orchestrator or Workers/Worker_001)."
        ),
    )
    parser.add_argument(
        "--worker-id",
        help="Legacy shortcut for agent path under Workers (for example, Worker_001).",
    )
    parser.add_argument(
        "--sandbox",
        default="danger-full-access",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="Sandbox mode used for codex command execution.",
    )
    parser.add_argument(
        "--approval",
        default="never",
        choices=["untrusted", "on-failure", "on-request", "never"],
        help="Approval policy used by codex.",
    )
    parser.add_argument(
        "--allow-web-search",
        action="store_true",
        help="Enable Codex native web_search tool for this loop (disabled by default).",
    )
    parser.add_argument(
        "--dangerously-bypass-sandbox",
        action="store_true",
        help="Pass --dangerously-bypass-approvals-and-sandbox to codex.",
    )
    parser.add_argument(
        "--codex-bin",
        help="Optional explicit path to codex executable (.exe/.cmd).",
    )
    parser.add_argument(
        "--runner",
        default="codex",
        choices=["codex", "kimi"],
        help="CLI agent backend to use (default: codex).",
    )
    parser.add_argument(
        "--model",
        help="Optional model override passed to the active CLI backend.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        help="Per-call reasoning override for Codex only.",
    )
    parser.add_argument(
        "--talker-routing",
        action="store_true",
        help="Enable Talker-only routing_state/user_sender_id relay contract for this loop.",
    )
    args = parser.parse_args()
    if args.reasoning_effort and args.runner != "codex":
        parser.error("--reasoning-effort is supported only for runner=codex")
    return args


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    if args.agent_path:
        candidate = Path(args.agent_path).expanduser()
        if candidate.is_absolute():
            agent_dir = candidate.resolve()
        else:
            agent_dir = (project_root / candidate).resolve()
    elif args.worker_id:
        # Backward compatibility for older launchers.
        agent_dir = (project_root / "Workers" / args.worker_id).resolve()
    else:
        raise RuntimeError("Either --agent-path or --worker-id must be provided.")

    inbox_root = agent_dir / "Prompts" / "Inbox"

    if not agent_dir.exists():
        raise RuntimeError(f"Agent directory not found: {agent_dir}")
    if (agent_dir / "ROLE_TALKER.md").exists() and not args.talker_routing:
        raise RuntimeError(
            "ROLE_TALKER agent requires '--talker-routing' flag for strict routing contract."
        )

    if args.runner == "codex":
        runner = CodexRunner(
            codex_bin=args.codex_bin,
            sandbox_mode=args.sandbox,
            approval_policy=args.approval,
            web_search_enabled=args.allow_web_search,
            dangerously_bypass_sandbox=args.dangerously_bypass_sandbox,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
        )
    elif args.runner == "kimi":
        # KimiRunner добавляется на Этапе 3. До реализации --runner kimi даст ImportError.
        from agent_runners import KimiRunner
        runner = KimiRunner(model=args.model)
    else:
        raise RuntimeError(f"Unknown runner: {args.runner}")

    loop_runner = LoopRunner(
        worker_dir=agent_dir,
        inbox_root=inbox_root,
        runner=runner,
        is_talker_context=bool(args.talker_routing),
        cli_reasoning_effort_pinned=bool(args.reasoning_effort),
    )
    loop_runner.run_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
