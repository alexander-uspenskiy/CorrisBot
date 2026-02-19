import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "send_reply_to_report.py"


class SendReplyToReportTests(unittest.TestCase):
    def _run_script(self, args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_e2e_valid_reply_to_delivers_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            inbox = temp_root / "Talker" / "Prompts" / "Inbox" / "Orc_ProjectA"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectA",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                        "",
                        "Task payload here",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text("delivery payload", encoding="utf-8")

            code, stdout, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                ]
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            delivered = Path(payload["delivered_file"])
            self.assertTrue(delivered.exists())
            self.assertEqual("delivery payload", delivered.read_text(encoding="utf-8"))
            self.assertEqual(str(inbox.resolve()), payload["inbox_path"])

    def test_negative_unsupported_file_pattern_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Reply-To:",
                        f"- InboxPath: {temp_root / 'Inbox'}",
                        "- FilePattern: Prompt_CUSTOM.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text("data", encoding="utf-8")

            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("unsupported FilePattern", stderr)


if __name__ == "__main__":
    unittest.main()
