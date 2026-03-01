import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "send_orchestrator_handoff.py"
sys.path.insert(0, str(REPO_ROOT / "Looper"))

from project_registry import register_project, remove_project, update_project  # noqa: E402


class SendOrchestratorHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.talker_root = REPO_ROOT / "Talker"
        self.registry_path = self.talker_root / "Temp" / "project_registry.json"
        if self.registry_path.exists():
            self._registry_backup: bytes | None = self.registry_path.read_bytes()
        else:
            self._registry_backup = None
        self._cleanup_paths: list[Path] = []

    def tearDown(self) -> None:
        for path in self._cleanup_paths:
            try:
                if path.exists():
                    shutil.rmtree(path)
            except Exception:
                pass

        try:
            if self._registry_backup is None:
                if self.registry_path.exists():
                    self.registry_path.unlink()
            else:
                self.registry_path.parent.mkdir(parents=True, exist_ok=True)
                self.registry_path.write_bytes(self._registry_backup)
        except Exception:
            pass

    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _register_temp_project(self, project_root: Path) -> str:
        talker_root = REPO_ROOT / "Talker"
        project = register_project(talker_root, str(project_root), "")
        return Path(project["project_root"]).name

    def _remove_project_if_exists(self, project_tag: str) -> None:
        talker_root = REPO_ROOT / "Talker"
        try:
            remove_project(talker_root, project_tag)
        except Exception:
            pass

    def test_e2e_include_reply_to_creates_prompt_with_contract_without_edit_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / f"CorrisBot_TestProject_{uuid.uuid4().hex[:8]}"
            (project_root / "Orchestrator" / "Prompts" / "Inbox" / "Talker").mkdir(parents=True, exist_ok=True)
            message_file = temp_root / "user_message.md"
            message_file.write_text("Line 1\nLine 2", encoding="utf-8")
            sender_id = f"Orc_Test_{uuid.uuid4().hex[:8]}"
            self._cleanup_paths.append(self.talker_root / "Prompts" / "Inbox" / sender_id)

            project_tag = self._register_temp_project(project_root)
            try:
                exit_code, stdout, stderr = self._run_script(
                    [
                        "--project-tag",
                        project_tag,
                        "--user-message-file",
                        str(message_file),
                        "--include-reply-to",
                        "--created-at-utc",
                        "2026-03-01T00:00:00Z",
                        "--sender-id",
                        sender_id,
                        "--local-handoff-file",
                        str(temp_root / "handoff.md"),
                        "--routing-contract-file",
                        str(temp_root / "routing_contract.json"),
                    ]
                )

                self.assertEqual(0, exit_code, msg=stderr)
                payload = json.loads(stdout.strip())
                delivered = Path(payload["delivered_file"])
                contract_file = Path(payload["routing_contract_file"])
                self.assertTrue(delivered.exists())
                self.assertTrue(contract_file.exists())

                contract = json.loads(contract_file.read_text(encoding="utf-8"))
                self.assertNotIn("EditRoot", contract)

                text = delivered.read_text(encoding="utf-8")
                self.assertIn("Route-Meta:", text)
                self.assertIn("Routing-Contract:", text)
                self.assertIn(f"- AppRoot: {REPO_ROOT.resolve()}", text)
                self.assertIn(f"- AgentsRoot: {project_root.resolve()}", text)
                self.assertNotIn("- EditRoot:", text)
                self.assertIn("Reply-To:", text)
                self.assertIn(f"- SenderID: {sender_id}", text)
                self.assertIn("---BEGIN USER MESSAGE (VERBATIM)---", text)
                self.assertIn("Line 1\nLine 2", text)
                self.assertIn("---END USER MESSAGE (VERBATIM)---", text)
            finally:
                self._remove_project_if_exists(project_tag)

    def test_e2e_omit_reply_to_keeps_verbatim_wrapper_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / f"MyProject_{uuid.uuid4().hex[:8]}"
            (project_root / "Orchestrator" / "Prompts" / "Inbox" / "Talker").mkdir(parents=True, exist_ok=True)
            message_file = temp_root / "user_message.md"
            message_file.write_text("No routing update", encoding="utf-8")
            sender_id = f"Orc_Test_{uuid.uuid4().hex[:8]}"

            project_tag = self._register_temp_project(project_root)
            try:
                exit_code, stdout, stderr = self._run_script(
                    [
                        "--project-tag",
                        project_tag,
                        "--user-message-file",
                        str(message_file),
                        "--omit-reply-to",
                        "--created-at-utc",
                        "2026-03-01T00:00:00Z",
                        "--sender-id",
                        sender_id,
                        "--local-handoff-file",
                        str(temp_root / "handoff.md"),
                        "--routing-contract-file",
                        str(temp_root / "routing_contract.json"),
                    ]
                )

                self.assertEqual(0, exit_code, msg=stderr)
                payload = json.loads(stdout.strip())
                delivered = Path(payload["delivered_file"])
                self.assertTrue(delivered.exists())
                text = delivered.read_text(encoding="utf-8")
                self.assertIn("Route-Meta:", text)
                self.assertIn("Routing-Contract:", text)
                self.assertNotIn("- EditRoot:", text)
                self.assertNotIn("Reply-To:", text)
                self.assertIn("---BEGIN USER MESSAGE (VERBATIM)---", text)
                self.assertIn("No routing update", text)
                self.assertIn("---END USER MESSAGE (VERBATIM)---", text)
            finally:
                self._remove_project_if_exists(project_tag)

    def test_negative_invalid_route_session_id_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / f"MyProject_{uuid.uuid4().hex[:8]}"
            (project_root / "Orchestrator" / "Prompts" / "Inbox" / "Talker").mkdir(parents=True, exist_ok=True)
            message_file = temp_root / "user_message.md"
            message_file.write_text("Invalid route session", encoding="utf-8")

            project_tag = self._register_temp_project(project_root)
            try:
                update_project(REPO_ROOT / "Talker", project_tag, route_session_id="BAD SESSION ID")

                exit_code, _, stderr = self._run_script(
                    [
                        "--project-tag",
                        project_tag,
                        "--user-message-file",
                        str(message_file),
                        "--local-handoff-file",
                        str(temp_root / "handoff.md"),
                        "--routing-contract-file",
                        str(temp_root / "routing_contract.json"),
                    ]
                )

                self.assertEqual(2, exit_code)
                self.assertIn("route-session-id has unsupported format", stderr)
            finally:
                self._remove_project_if_exists(project_tag)


if __name__ == "__main__":
    unittest.main()
