import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "send_orchestrator_handoff.py"


class SendOrchestratorHandoffTests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_e2e_include_reply_to_creates_prompt_with_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / "CorrisBot_TestProject_8"
            talker_root = temp_root / "Talker"
            project_root.mkdir(parents=True, exist_ok=True)
            talker_root.mkdir(parents=True, exist_ok=True)
            message_file = temp_root / "user_message.md"
            message_file.write_text("Line 1\nLine 2", encoding="utf-8")

            exit_code, stdout, stderr = self._run_script(
                [
                    "--project-root",
                    str(project_root),
                    "--talker-root",
                    str(talker_root),
                    "--user-message-file",
                    str(message_file),
                    "--include-reply-to",
                ]
            )

            self.assertEqual(0, exit_code, msg=stderr)
            payload = json.loads(stdout.strip())
            delivered = Path(payload["delivered_file"])
            self.assertTrue(delivered.exists())
            text = delivered.read_text(encoding="utf-8")
            self.assertIn("Reply-To:", text)
            self.assertIn("- SenderID: Orc_CorrisBot_TestProject_8", text)
            self.assertIn("---BEGIN USER MESSAGE (VERBATIM)---", text)
            self.assertIn("Line 1\nLine 2", text)
            self.assertIn("---END USER MESSAGE (VERBATIM)---", text)

    def test_e2e_omit_reply_to_keeps_verbatim_wrapper_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_root = temp_root / "MyProject"
            talker_root = temp_root / "Talker"
            project_root.mkdir(parents=True, exist_ok=True)
            talker_root.mkdir(parents=True, exist_ok=True)
            message_file = temp_root / "user_message.md"
            message_file.write_text("No routing update", encoding="utf-8")

            exit_code, stdout, stderr = self._run_script(
                [
                    "--project-root",
                    str(project_root),
                    "--talker-root",
                    str(talker_root),
                    "--user-message-file",
                    str(message_file),
                    "--omit-reply-to",
                ]
            )

            self.assertEqual(0, exit_code, msg=stderr)
            payload = json.loads(stdout.strip())
            delivered = Path(payload["delivered_file"])
            self.assertTrue(delivered.exists())
            text = delivered.read_text(encoding="utf-8")
            self.assertNotIn("Reply-To:", text)
            self.assertIn("---BEGIN USER MESSAGE (VERBATIM)---", text)
            self.assertIn("No routing update", text)
            self.assertIn("---END USER MESSAGE (VERBATIM)---", text)


if __name__ == "__main__":
    unittest.main()
