import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "Looper" / "send_reply_to_report.py"


class SendReplyToReportTests(unittest.TestCase):
    def _run_script(self, args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None
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
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_123\n"
                "- RouteSessionID: RS_A\n"
                "- ProjectTag: ProjectA\n\n"
                "delivery payload", 
                encoding="utf-8"
            )

            audit_file = talker_root / "Temp" / "report_delivery_audit.jsonl"
            
            code, stdout, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
                ],
                cwd=temp_root
            )

            self.assertEqual(0, code, msg=stderr)
            payload = json.loads(stdout.strip())
            delivered = Path(payload["delivered_file"])
            self.assertTrue(delivered.exists())
            self.assertEqual(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_123\n"
                "- RouteSessionID: RS_A\n"
                "- ProjectTag: ProjectA\n\n"
                "delivery payload", 
                delivered.read_text(encoding="utf-8")
            )
            self.assertEqual(str(inbox.resolve()), payload["inbox_path"])
            # Verify audit file was created
            self.assertTrue(audit_file.exists())

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
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_124\n"
                "- RouteSessionID: RS_B\n"
                "- ProjectTag: ProjectB\n\n"
                "data", 
                encoding="utf-8"
            )

            audit_file = temp_root / "Talker" / "Temp" / "report_delivery_audit.jsonl"
            
            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
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
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_125\n"
                "- RouteSessionID: RS_C\n"
                "- ProjectTag: ProjectC\n\n"
                "data", 
                encoding="utf-8"
            )

            audit_file = temp_root / "Talker" / "Temp" / "report_delivery_audit.jsonl"
            
            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
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
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_126\n"
                "- RouteSessionID: RS_D\n"
                "- ProjectTag: ProjectD\n\n"
                "data", 
                encoding="utf-8"
            )

            audit_file = temp_root / "Talker" / "Temp" / "report_delivery_audit.jsonl"
            
            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
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
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_127\n"
                "- RouteSessionID: RS_E\n"
                "- ProjectTag: ProjectE\n\n"
                "data", 
                encoding="utf-8"
            )

            audit_file = temp_root / "Talker" / "Temp" / "report_delivery_audit.jsonl"
            
            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("must be absolute path", stderr)

    def test_negative_missing_audit_file_returns_error(self) -> None:
        """Missing --audit-file should fail with report_audit_path_missing_or_invalid."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_F"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectF"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_F",
                        "- ProjectTag: ProjectF",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_F",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectF",
                        "- OrchestratorSenderID: Orc_ProjectF",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectF",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_128\n"
                "- RouteSessionID: RS_F\n"
                "- ProjectTag: ProjectF\n\n"
                "data", 
                encoding="utf-8"
            )

            # Do NOT pass --audit-file
            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("--audit-file", stderr)

    def test_negative_relative_audit_file_rejected(self) -> None:
        """Relative --audit-file path should fail with report_audit_path_missing_or_invalid."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_G"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectG"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_G",
                        "- ProjectTag: ProjectG",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_G",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectG",
                        "- OrchestratorSenderID: Orc_ProjectG",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectG",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_129\n"
                "- RouteSessionID: RS_G\n"
                "- ProjectTag: ProjectG\n\n"
                "data", 
                encoding="utf-8"
            )

            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    "relative/path/audit.jsonl",  # Relative path
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("report_audit_path_missing_or_invalid", stderr)

    def test_negative_out_of_scope_audit_file_rejected(self) -> None:
        """Audit file outside allowed scope should fail with report_audit_path_missing_or_invalid."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_H"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectH"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            # Out-of-scope audit file location
            out_of_scope_audit = temp_root / "WrongLocation" / "audit.jsonl"
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_H",
                        "- ProjectTag: ProjectH",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_H",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectH",
                        "- OrchestratorSenderID: Orc_ProjectH",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectH",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_130\n"
                "- RouteSessionID: RS_H\n"
                "- ProjectTag: ProjectH\n\n"
                "data", 
                encoding="utf-8"
            )

            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(out_of_scope_audit),
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("report_audit_path_missing_or_invalid", stderr)
            self.assertIn("outside allowed scope", stderr)

    def test_negative_worker_non_temp_audit_file_rejected(self) -> None:
        """Worker audit file must be under Workers\\<WorkerId>\\Temp\\... only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_H2"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectH2"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            bad_worker_audit = (
                agents_root / "Workers" / "Worker_001" / "NOT_TEMP" / "report_delivery_audit.jsonl"
            )
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_H2",
                        "- ProjectTag: ProjectH2",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_H2",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectH2",
                        "- OrchestratorSenderID: Orc_ProjectH2",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectH2",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_130_h2\n"
                "- RouteSessionID: RS_H2\n"
                "- ProjectTag: ProjectH2\n\n"
                "data",
                encoding="utf-8",
            )

            code, _, stderr = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(bad_worker_audit),
                ]
            )

            self.assertEqual(2, code)
            self.assertIn("report_audit_path_missing_or_invalid", stderr)
            self.assertIn("outside allowed scope", stderr)

    def test_idempotency_skip_with_explicit_audit_file(self) -> None:
        """Idempotency skip should work with explicit --audit-file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            app_root = temp_root / "_RUN_CorrisBot"
            talker_root = app_root / "Talker"
            agents_root = temp_root / "Project_I"
            edit_root = temp_root / "EditRepo"
            talker_root.mkdir(parents=True, exist_ok=True)
            agents_root.mkdir(parents=True, exist_ok=True)
            edit_root.mkdir(parents=True, exist_ok=True)
            inbox = talker_root / "Prompts" / "Inbox" / "Orc_ProjectI"
            prompt_file = temp_root / "incoming.md"
            report_file = temp_root / "report.md"
            audit_file = talker_root / "Temp" / "report_delivery_audit.jsonl"
            
            prompt_file.write_text(
                "\n".join(
                    [
                        "Route-Meta:",
                        "- RouteSessionID: RS_I",
                        "- ProjectTag: ProjectI",
                        "",
                        "Routing-Contract:",
                        "- Version: 1",
                        f"- RouteSessionID: RS_I",
                        f"- AppRoot: {app_root.resolve()}",
                        f"- AgentsRoot: {agents_root.resolve()}",
                        f"- EditRoot: {edit_root.resolve()}",
                        "- ProjectTag: ProjectI",
                        "- OrchestratorSenderID: Orc_ProjectI",
                        "- CreatedAtUTC: 2026-02-20T12:00:00Z",
                        "",
                        "Reply-To:",
                        f"- InboxPath: {inbox}",
                        "- SenderID: Orc_ProjectI",
                        "- FilePattern: Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md",
                    ]
                ),
                encoding="utf-8",
            )
            report_file.write_text(
                "Message-Meta:\n"
                "- MessageClass: report\n"
                "- ReportType: phase_gate\n"
                "- ReportID: rep_idem_001\n"
                "- RouteSessionID: RS_I\n"
                "- ProjectTag: ProjectI\n\n"
                "delivery payload", 
                encoding="utf-8"
            )

            # First execution
            code1, stdout1, stderr1 = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
                ]
            )
            self.assertEqual(0, code1, msg=stderr1)
            out1 = json.loads(stdout1.strip())
            self.assertNotEqual("<idempotent_skip>", out1["delivered_file"])
            
            # Count files in inbox
            files_after_first = list(inbox.iterdir())
            self.assertEqual(1, len(files_after_first))
            
            # Second execution (should skip)
            code2, stdout2, stderr2 = self._run_script(
                [
                    "--incoming-prompt",
                    str(prompt_file),
                    "--report-file",
                    str(report_file),
                    "--audit-file",
                    str(audit_file),
                ]
            )
            self.assertEqual(0, code2, msg=stderr2)
            out2 = json.loads(stdout2.strip())
            self.assertEqual("<idempotent_skip>", out2["delivered_file"])
            
            # Verify no new file was created
            files_after_second = list(inbox.iterdir())
            self.assertEqual(1, len(files_after_second))


if __name__ == "__main__":
    unittest.main()
