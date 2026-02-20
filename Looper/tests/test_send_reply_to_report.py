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
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_A"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectA"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_A",
                        "- ProjectTag: ProjectA",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_A",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectA",
                        "- OrchestratorSenderID: Orc_ProjectA",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
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
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_B"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_B",
                        "- ProjectTag: ProjectB",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_B",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectB",
                        "- OrchestratorSenderID: Orc_ProjectB",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {talker_root / 'Prompts' / 'Inbox' / 'Orc_ProjectB'}",
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

    def test_negative_missing_route_meta_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_C"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_C",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectC",
                        "- OrchestratorSenderID: Orc_ProjectC",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {talker_root / 'Prompts' / 'Inbox' / 'Orc_ProjectC'}",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
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
            self.assertIn("Route-Meta block is missing required fields", stderr)

    def test_negative_reply_to_out_of_scope_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_D"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_D",
                        "- ProjectTag: ProjectD",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_D",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectD",
                        "- OrchestratorSenderID: Orc_ProjectD",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {temp_root / 'WrongRoot' / 'Prompts' / 'Inbox' / 'Orc_ProjectD'}",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
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
            self.assertIn("out of allowed scope", stderr)

    def test_negative_relative_reply_to_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_E"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_E",
                        "- ProjectTag: ProjectE",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_E",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectE",
                        "- OrchestratorSenderID: Orc_ProjectE",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        "- InboxPath: Talker/Prompts/Inbox/Orc_ProjectE",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
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
            self.assertIn("must be absolute path", stderr)


if __name__ == "__main__":
    unittest.main()
