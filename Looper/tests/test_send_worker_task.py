import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "send_worker_task.py"


class SendWorkerTaskTests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _init_project(self, project_root: Path) -> None:
        (project_root / "Orchestrator" / "Prompts" / "Inbox").mkdir(parents=True, exist_ok=True)
        (project_root / "Workers" / "Worker_001" / "Prompts" / "Inbox").mkdir(parents=True, exist_ok=True)

    def _write_contract(
        self,
        path: Path,
        app_root: Path,
        agents_root: Path,
        edit_root: Path,
        sender_id: str = "Orc_ProjectA",
    ) -> None:
        payload = {
            "Version": "1",
            "RouteSessionID": "RS_TEST",
            "AppRoot": str(app_root.resolve()),
            "AgentsRoot": str(agents_root.resolve()),
            "EditRoot": str(edit_root.resolve()),
            "ProjectTag": "ProjectA",
            "OrchestratorSenderID": sender_id,
            "CreatedAtUTC": "2026-02-20T12:00:00Z",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_e2e_delivers_worker_prompt_with_route_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            agents_root = temp_root / "ProjectA"
            edit_root = temp_root / "EditRepo"
            self._init_project(agents_root)
            app_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            contract_file = temp_root / "routing_contract.json"
            self._write_contract(contract_file, app_root, agents_root, edit_root)
            task_file = temp_root / "task.md"
            task_file.write_text("Implement phase 1 changes", encoding="utf-8")

            code, stdout, stderr = self._run_script(
                [
                    "--routing-contract-file",
                    str(contract_file),
                    "--worker-id",
                    "Worker_001",
                    "--task-file",
                    str(task_file),
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            delivered = Path(payload["delivered_file"])
            self.assertTrue(delivered.exists())
            expected_inbox = agents_root / "Workers" / "Worker_001" / "Prompts" / "Inbox" / "Orc_ProjectA"
            self.assertEqual(str(expected_inbox.resolve()), payload["worker_inbox"])
            text = delivered.read_text(encoding="utf-8")
            self.assertIn("Route-Meta:", text)
            self.assertIn("- RouteSessionID: RS_TEST", text)
            self.assertIn("Routing-Contract:", text)
            self.assertIn("Reply-To:", text)
            self.assertIn("Implement phase 1 changes", text)

    def test_negative_missing_contract_file_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            missing = temp_root / "missing.json"
            code, _, stderr = self._run_script(
                [
                    "--routing-contract-file",
                    str(missing),
                    "--worker-id",
                    "Worker_001",
                    "--text",
                    "task",
                ]
            )
            self.assertEqual(2, code)
            self.assertIn("routing contract file not found", stderr)

    def test_negative_worker_out_of_contract_scope_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            agents_root = temp_root / "ProjectA"
            edit_root = temp_root / "EditRepo"
            self._init_project(agents_root)
            app_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            contract_file = temp_root / "routing_contract.json"
            self._write_contract(contract_file, app_root, agents_root, edit_root)

            code, _, stderr = self._run_script(
                [
                    "--routing-contract-file",
                    str(contract_file),
                    "--worker-id",
                    "Worker_002",
                    "--text",
                    "task",
                ]
            )
            self.assertEqual(2, code)
            self.assertIn("worker root not found", stderr)

    def test_sender_id_with_spaces_allowed_as_path_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            agents_root = temp_root / "ProjectA"
            edit_root = temp_root / "EditRepo"
            self._init_project(agents_root)
            app_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            contract_file = temp_root / "routing_contract.json"
            self._write_contract(
                contract_file,
                app_root,
                agents_root,
                edit_root,
                sender_id="Orc ProjectA v1",
            )

            code, stdout, stderr = self._run_script(
                [
                    "--routing-contract-file",
                    str(contract_file),
                    "--worker-id",
                    "Worker_001",
                    "--text",
                    "task",
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            expected_inbox = agents_root / "Workers" / "Worker_001" / "Prompts" / "Inbox" / "Orc ProjectA v1"
            self.assertEqual(str(expected_inbox.resolve()), payload["worker_inbox"])


if __name__ == "__main__":
    unittest.main()
