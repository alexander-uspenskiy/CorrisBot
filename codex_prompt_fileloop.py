import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LoopRunner:
    def __init__(
        self,
        executor_dir: Path,
        inbox_root: Path,
        sandbox_mode: str,
        approval_policy: str,
        web_search_enabled: bool,
        dangerously_bypass_sandbox: bool,
        codex_bin: Optional[str],
    ) -> None:
        self.executor_dir = executor_dir
        self.inbox_root = inbox_root
        self.sandbox_mode = sandbox_mode
        self.approval_policy = approval_policy
        self.web_search_enabled = web_search_enabled
        self.dangerously_bypass_sandbox = dangerously_bypass_sandbox
        self.codex_executable = self.resolve_codex_executable(codex_bin)
        self.inbox_root.mkdir(parents=True, exist_ok=True)
        self.prompts_dir: Optional[Path] = None
        self.state_path: Optional[Path] = None
        self.console_log_path: Optional[Path] = None

    def write_console_line(self, text: str) -> None:
        print(text, flush=True)
        if self.console_log_path:
            line = f"[{now_str()}] {text}\n"
            with self.console_log_path.open("a", encoding="utf-8") as f:
                f.write(line)

    def resolve_single_sender_prompts_dir(self) -> Path:
        waiting_logged = False
        while True:
            sender_dirs = sorted(p for p in self.inbox_root.iterdir() if p.is_dir()) if self.inbox_root.exists() else []
            if len(sender_dirs) == 1:
                return sender_dirs[0]

            if len(sender_dirs) > 1:
                names = ", ".join(p.name for p in sender_dirs)
                raise RuntimeError(
                    "Multiple sender directories detected in Inbox. "
                    "Current runner supports one sender only. "
                    f"Found: {names}"
                )

            if not waiting_logged:
                self.write_console_line(f"Waiting for sender directory in {self.inbox_root} ...")
                waiting_logged = True
            time.sleep(0.5)

    def read_state(self) -> tuple[Optional[str], int]:
        if self.state_path is None:
            raise RuntimeError("state_path is not initialized")
        if not self.state_path.exists():
            return None, 0

        try:
            raw = self.state_path.read_text(encoding="utf-8")
            obj = json.loads(raw)
            thread_id = obj.get("thread_id")
            next_index = int(obj.get("next_index", 0))
            return thread_id, next_index
        except Exception:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if self.prompts_dir is None:
                raise RuntimeError("prompts_dir is not initialized")
            corrupt_path = self.prompts_dir / f"loop_state.corrupt.{stamp}.json"
            try:
                self.state_path.replace(corrupt_path)
            except Exception:
                pass
            self.write_console_line(
                f"[warning] State file is invalid JSON. Moved to '{corrupt_path}'. Starting with empty state."
            )
            return None, 0

    def write_state(self, thread_id: str, next_index: int) -> None:
        if self.state_path is None:
            raise RuntimeError("state_path is not initialized")
        payload = {
            "thread_id": thread_id,
            "next_index": next_index,
            "updated_at": now_str(),
        }
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.state_path)

    def wait_for_prompt_file(self, file_path: Path) -> None:
        if file_path.exists():
            return

        if self.prompts_dir is None:
            raise RuntimeError("prompts_dir is not initialized")
        self.write_console_line(f"Waiting for {file_path.name} in {self.prompts_dir} ...")
        while not file_path.exists():
            time.sleep(0.5)

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

    @staticmethod
    def get_thread_id_from_output(lines: list[str]) -> Optional[str]:
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

    def show_codex_events(self, lines: list[str]) -> None:
        started_commands: dict[str, bool] = {}

        for line in lines:
            trim = line.strip()
            if not trim:
                continue

            if not (trim.startswith("{") and trim.endswith("}")):
                if re.search(r"\b(error|exception|failed|fatal)\b", trim, flags=re.IGNORECASE):
                    self.write_console_line(trim)
                elif re.search(r"\bwarn\b", trim, flags=re.IGNORECASE):
                    self.write_console_line(trim)
                continue

            try:
                obj = json.loads(trim)
            except Exception:
                continue

            if obj.get("type") == "item.completed" and obj.get("item"):
                item = obj["item"]
                item_type = item.get("type")

                if item_type == "reasoning" and item.get("text"):
                    self.write_console_line(f"[reasoning] {item['text']}")
                    continue

                if item_type == "agent_message" and item.get("text"):
                    self.write_console_line(f"[agent] {item['text']}")
                    continue

                if item_type == "command_execution":
                    item_id = str(item.get("id") or "")
                    cmd = str(item.get("command") or "")
                    status = str(item.get("status") or "")
                    code = item.get("exit_code")

                    if item_id and item_id in started_commands:
                        if status == "completed":
                            self.write_console_line(f"[command] (exit={code})")
                        elif status == "failed":
                            self.write_console_line(f"[command] (failed, exit={code})")
                        elif status:
                            self.write_console_line(f"[command] ({status})")
                        else:
                            self.write_console_line("[command]")
                    else:
                        if status == "completed":
                            self.write_console_line(f"[command] {cmd} (exit={code})")
                        elif status == "failed":
                            self.write_console_line(f"[command] {cmd} (failed, exit={code})")
                        elif status:
                            self.write_console_line(f"[command] {cmd} ({status})")
                        else:
                            self.write_console_line(f"[command] {cmd}")

                    aggregated_output = item.get("aggregated_output")
                    if aggregated_output:
                        self.write_console_line(f"[command-output] {aggregated_output}")
                    continue

            if obj.get("type") == "item.started" and obj.get("item", {}).get("type") == "command_execution":
                item = obj["item"]
                item_id = str(item.get("id") or "")
                cmd = str(item.get("command") or "")
                if item_id:
                    started_commands[item_id] = True
                self.write_console_line(f"[command] {cmd} (in_progress)")
                continue

            if re.search(r"(error|failed)", str(obj.get("type") or ""), flags=re.IGNORECASE):
                self.write_console_line(f"[error] {trim}")
                continue

    @staticmethod
    def build_loop_prompt(user_prompt: str) -> str:
        rules = (
            "Loop execution rules (strict):\n"
            "- Process exactly one user prompt from this iteration.\n"
            "- For app launch/close tasks, execute action immediately, then do a quick verification.\n"
            "- If quick verification is negative or uncertain, wait at least 5 seconds and verify again before concluding failure.\n"
            "- If still not in expected state after that wait+recheck, do at most one retry and report both attempts.\n"
            "- Do not use internet/network resources (no web access, no API calls, no downloads).\n"
            "- Keep the final answer concise.\n\n"
            "User prompt:\n"
        )
        return f"{rules}\n{user_prompt}"

    @staticmethod
    def resolve_codex_executable(codex_bin: Optional[str]) -> str:
        if codex_bin:
            candidate = Path(codex_bin).expanduser()
            if candidate.exists():
                return str(candidate.resolve())
            return codex_bin

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
            "codex command was not found. Set PATH or pass --codex-bin with full path "
            "(for example, C:\\Users\\<user>\\AppData\\Roaming\\npm\\codex.cmd)."
        )

    def run_codex(self, prompt_text: str, thread_id: Optional[str]) -> tuple[list[str], int]:
        base_cmd = [self.codex_executable, "-C", str(self.executor_dir)]
        if self.dangerously_bypass_sandbox:
            base_cmd.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            base_cmd.extend(["-a", self.approval_policy, "-s", self.sandbox_mode])
        if not self.web_search_enabled:
            base_cmd.extend(["-c", "tools.web_search=false"])

        if thread_id:
            cmd = base_cmd + [
                "exec",
                "resume",
                thread_id,
                "--skip-git-repo-check",
                "--json",
                "-",
            ]
        else:
            cmd = base_cmd + [
                "exec",
                "--skip-git-repo-check",
                "--json",
                "-",
            ]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.executor_dir,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"codex executable not found: {self.codex_executable}") from exc

        output_text = proc.stdout or ""
        lines = output_text.splitlines()
        return lines, proc.returncode

    def append_result_header(self, result_path: Path, prompt_name: str) -> None:
        header = (
            f"# Codex Result for {prompt_name}\n\n"
            f"Started: {now_str()}\n\n"
        )
        result_path.write_text(header, encoding="utf-8")

    def append_lines(self, path: Path, lines: list[str]) -> None:
        if not lines:
            return
        with path.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                f.write("\n")

    def append_text(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text)

    def run_forever(self) -> None:
        self.prompts_dir = self.resolve_single_sender_prompts_dir()
        self.state_path = self.prompts_dir / "loop_state.json"
        self.console_log_path = self.prompts_dir / "Console.log"
        self.write_console_line(f"Using sender directory: {self.prompts_dir}")

        thread_id, index = self.read_state()

        while True:
            prompt_name = f"Promp_{index:04d}.md"
            prompt_path = self.prompts_dir / prompt_name

            self.wait_for_prompt_file(prompt_path)
            self.wait_for_file_ready(prompt_path)

            result_name = f"Promp_{index:04d}_Result.md"
            result_path = self.prompts_dir / result_name

            self.write_console_line(f"Processing {prompt_name}")
            self.append_result_header(result_path, prompt_name)

            user_prompt_text = prompt_path.read_text(encoding="utf-8")
            prompt_text = self.build_loop_prompt(user_prompt_text)
            used_resume = bool(thread_id and thread_id.strip())

            lines, exit_code = self.run_codex(prompt_text, thread_id if used_resume else None)
            self.append_lines(result_path, lines)
            self.show_codex_events(lines)

            if exit_code != 0 and used_resume:
                resume_err = "\n".join(lines)
                if re.search(
                    r"(?i)(session|thread).*(not found|missing|unknown)|not found.*(session|thread)",
                    resume_err,
                ):
                    self.append_text(
                        result_path,
                        "\nResume failed because session was not found. Starting a new session for this prompt.\n",
                    )
                    thread_id = None

                    lines, exit_code = self.run_codex(prompt_text, None)
                    self.append_text(result_path, "\n--- Fallback: new session attempt ---\n\n")
                    self.append_lines(result_path, lines)
                    self.show_codex_events(lines)

            if exit_code != 0:
                self.append_text(result_path, f"\nCommand failed with exit code: {exit_code}\n")
                raise RuntimeError(f"codex command failed with exit code {exit_code}")

            detected_thread_id = self.get_thread_id_from_output(lines)
            if detected_thread_id:
                thread_id = detected_thread_id

            if not (thread_id and thread_id.strip()):
                self.append_text(result_path, "\nCould not detect thread_id from codex output.\n")
                raise RuntimeError("thread_id was not detected; refusing to continue without explicit session id.")

            self.append_text(result_path, f"\nFinished: {now_str()}\n")

            index += 1
            self.write_state(thread_id, index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loop: waits for Promp_XXXX.md files in executor inbox and processes them via codex."
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Path to .CorrisBot project root.",
    )
    parser.add_argument(
        "--executor-id",
        required=True,
        help="Executor directory name (for example, Executor_001).",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    executor_dir = project_root / "Executors" / args.executor_id
    inbox_root = executor_dir / "Prompts" / "Inbox"

    if not executor_dir.exists():
        raise RuntimeError(f"Executor directory not found: {executor_dir}")

    runner = LoopRunner(
        executor_dir=executor_dir,
        inbox_root=inbox_root,
        sandbox_mode=args.sandbox,
        approval_policy=args.approval,
        web_search_enabled=args.allow_web_search,
        dangerously_bypass_sandbox=args.dangerously_bypass_sandbox,
        codex_bin=args.codex_bin,
    )
    runner.run_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
